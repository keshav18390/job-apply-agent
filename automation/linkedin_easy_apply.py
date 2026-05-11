from __future__ import annotations

import argparse
import asyncio
import json
import sqlite3
import sys
import uuid
from datetime import datetime
from pathlib import Path
from urllib.parse import quote_plus

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from automation.browser_agent import _fill_fields, _first_visible
from automation.job_scraper import ANTI_DETECTION_SCRIPT, REAL_USER_AGENT, linkedin_login_from_env
from config import cfg


DEFAULT_SEARCHES = [
    ("mlops engineer", "India"),
    ("data scientist", "Bengaluru, Karnataka, India"),
    ("data analyst", "India"),
    ("python developer", "India"),
    ("machine learning engineer", "India"),
    ("backend developer", "India"),
]


def _connect_db() -> sqlite3.Connection:
    db_path = ROOT / "data" / "autoapplier.db"
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    return con


def _first_user_id() -> str:
    con = _connect_db()
    row = con.execute("select id from users order by created_at limit 1").fetchone()
    if not row:
        raise SystemExit("No users found in data/autoapplier.db. Create a profile in the app first.")
    return row["id"]


def _load_profile(user_id: str) -> dict:
    con = _connect_db()
    user = con.execute("select * from users where id=?", (user_id,)).fetchone()
    profile_row = con.execute("select * from user_profiles where user_id=?", (user_id,)).fetchone()
    if not user or not profile_row:
        raise SystemExit(f"Profile not found for user_id={user_id}")

    profile = {
        "full_name": user["full_name"],
        "email": user["email"],
        "phone": profile_row["phone"],
        "location": profile_row["location"],
        "linkedin_url": profile_row["linkedin_url"],
        "github_url": profile_row["github_url"],
        "portfolio_url": profile_row["portfolio_url"],
        "years_experience": profile_row["years_experience"],
        "summary": profile_row["summary"],
        "resume_text": profile_row["resume_text"],
        "salary_min": profile_row["salary_min"],
        "work_authorization": profile_row["work_authorization"],
    }
    for key in ("skills", "experience", "education"):
        try:
            profile[key] = json.loads(profile_row[key] or "[]")
        except Exception:
            profile[key] = []
    return profile


def _applied_job_ids(user_id: str) -> set[str]:
    con = _connect_db()
    ids: set[str] = set()
    rows = con.execute(
        "select job_url from job_applications where user_id=? and status='applied'",
        (user_id,),
    ).fetchall()
    for row in rows:
        url = row["job_url"] or ""
        if "currentJobId=" in url:
            ids.add(url.split("currentJobId=", 1)[1].split("&", 1)[0])
        elif "/jobs/view/" in url:
            ids.add(url.split("/jobs/view/", 1)[1].split("/", 1)[0].split("?", 1)[0])
    return ids


def _record_application(user_id: str, job: dict, result: dict, cover_letter: str) -> None:
    con = _connect_db()
    con.execute(
        """
        insert into job_applications (
            id, user_id, agent_run_id, job_title, company_name, job_url,
            job_description, job_location, salary_range, job_type, source_site,
            status, applied_at, match_score, cover_letter, ai_notes,
            error_message, created_at
        ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            str(uuid.uuid4()),
            user_id,
            None,
            job.get("title", ""),
            job.get("company", ""),
            job.get("url", ""),
            (job.get("description") or "")[:3000],
            job.get("location", ""),
            "",
            "full-time",
            "linkedin",
            result.get("status", "failed"),
            datetime.utcnow().isoformat() if result.get("status") == "applied" else None,
            job.get("match_score", 55),
            cover_letter,
            "Terminal LinkedIn Easy Apply run",
            result.get("error") or "",
            datetime.utcnow().isoformat(),
        ),
    )
    con.commit()


def _parse_card_text(text: str, query: str, location: str) -> tuple[str, str, str]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    title = lines[0] if lines else query
    company = "LinkedIn"
    job_location = location
    for line in lines[1:]:
        low = line.lower()
        if line == title or "easy apply" in low or low in {"viewed", "promoted"}:
            continue
        if company == "LinkedIn":
            company = line
        elif job_location == location:
            job_location = line
            break
    return title, company, job_location


def _cover_letter(profile: dict, title: str, company: str) -> str:
    skills = ", ".join((profile.get("skills") or [])[:5])
    return (
        f"Dear Hiring Manager,\n\n"
        f"I am excited to apply for the {title} role at {company}. "
        f"My background includes {skills}, and I have hands-on experience with "
        f"Python, SQL, FastAPI, analytics workflows, and practical project delivery.\n\n"
        f"I would welcome the opportunity to contribute strong execution, curiosity, "
        f"and problem-solving ability to your team.\n\n"
        f"Sincerely,\n{profile.get('full_name', 'Candidate')}\n"
    )


async def _submit_easy_apply_modal(page, profile: dict, cover_letter: str) -> dict:
    for step in range(18):
        print(f"[Apply] Step {step + 1}")
        await asyncio.sleep(1.2)
        await _fill_fields(page, profile, cover_letter)

        submit = await _first_visible(page, [
            "button[aria-label='Submit application']",
            "button[aria-label*='Submit application']",
            "button:has-text('Submit application')",
            "button:has-text('Submit')",
        ])
        if submit:
            await submit.click()
            await asyncio.sleep(4)
            return {"status": "applied", "error": None}

        nxt = await _first_visible(page, [
            "button[aria-label='Continue to next step']",
            "button[aria-label='Review your application']",
            "button[aria-label*='Continue']",
            "button[aria-label*='Review']",
            "button:has-text('Next')",
            "button:has-text('Review')",
            "button:has-text('Continue')",
        ])
        if nxt:
            await nxt.click()
            await asyncio.sleep(1.5)
            continue

        return {"status": "failed", "error": "Easy Apply modal opened but no next/review/submit button found"}
    return {"status": "failed", "error": "Could not reach LinkedIn submit"}


async def apply_one(user_id: str, searches: list[tuple[str, str]], max_cards_per_search: int) -> bool:
    profile = _load_profile(user_id)
    applied_ids = _applied_job_ids(user_id)

    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            user_data_dir=cfg.linkedin_user_data_dir(),
            headless=cfg.headless(),
            slow_mo=cfg.slow_mo(),
            viewport={"width": 1366, "height": 900},
            user_agent=REAL_USER_AGENT,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
        )
        await ctx.add_init_script(ANTI_DETECTION_SCRIPT)
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()

        await page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded", timeout=cfg.timeout())
        await page.wait_for_timeout(3000)
        if "login" in page.url:
            await linkedin_login_from_env(page)
            await page.wait_for_timeout(2000)
        if not any(part in page.url for part in ("feed", "jobs", "mynetwork")):
            await ctx.close()
            raise SystemExit(f"LinkedIn login required. Current URL: {page.url}")

        for query, location in searches:
            url = (
                "https://www.linkedin.com/jobs/search/"
                f"?keywords={quote_plus(query)}"
                f"&location={quote_plus(location)}"
                "&f_AL=true&sortBy=DD"
            )
            print(f"[Search] {query} | {location}")
            await page.goto(url, wait_until="domcontentloaded", timeout=cfg.timeout())
            await page.wait_for_timeout(7000)
            for _ in range(3):
                await page.mouse.wheel(0, 900)
                await page.wait_for_timeout(1200)

            cards = await page.query_selector_all("[data-job-id]")
            print(f"[Search] Cards found: {len(cards)}")
            for card in cards[:max_cards_per_search]:
                job_id = await card.get_attribute("data-job-id")
                text = await card.inner_text()
                if not job_id or job_id in applied_ids or "easy apply" not in text.lower():
                    continue

                title, company, job_location = _parse_card_text(text, query, location)
                print(f"[Try] {title} @ {company} ({job_id})")
                await card.click()
                await page.wait_for_timeout(2500)

                easy = await _first_visible(page, [
                    "button.jobs-apply-button",
                    ".jobs-apply-button--top-card button",
                    ".jobs-s-apply button",
                    "button[aria-label*='Easy Apply']",
                    "button:has-text('Easy Apply')",
                ])
                if not easy:
                    print(f"[Skip] Easy Apply disappeared after card click: {job_id}")
                    continue

                await easy.click()
                await page.wait_for_timeout(2500)
                cover = _cover_letter(profile, title, company)
                result = await _submit_easy_apply_modal(page, profile, cover)
                job = {
                    "title": title,
                    "company": company,
                    "location": job_location,
                    "url": (
                        "https://www.linkedin.com/jobs/search/"
                        f"?currentJobId={job_id}"
                        f"&keywords={quote_plus(query)}"
                        f"&location={quote_plus(location)}"
                        "&f_AL=true&sortBy=DD"
                    ),
                    "description": text[:2000],
                    "match_score": 55,
                }
                _record_application(user_id, job, result, cover)
                print(f"[Result] {result}")
                await ctx.close()
                return result.get("status") == "applied"

        await ctx.close()
        print("[Done] No unapplied LinkedIn Easy Apply cards found.")
        return False


def _parse_search(values: list[str]) -> list[tuple[str, str]]:
    if not values:
        return DEFAULT_SEARCHES
    parsed = []
    for value in values:
        if "|" not in value:
            raise SystemExit(f"Invalid --search value: {value!r}. Use 'query|location'.")
        query, location = value.split("|", 1)
        parsed.append((query.strip(), location.strip()))
    return parsed


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply to one LinkedIn Easy Apply job from the terminal.")
    parser.add_argument("--user-id", default="", help="AutoApplier user id. Defaults to the first user in the DB.")
    parser.add_argument(
        "--search",
        action="append",
        default=[],
        help="Search pair as 'query|location'. Can be repeated.",
    )
    parser.add_argument("--max-cards", type=int, default=25, help="Cards to inspect per search.")
    args = parser.parse_args()

    user_id = args.user_id.strip() or _first_user_id()
    searches = _parse_search(args.search)
    applied = asyncio.run(apply_one(user_id, searches, args.max_cards))
    raise SystemExit(0 if applied else 1)


if __name__ == "__main__":
    main()
