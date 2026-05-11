from __future__ import annotations

import sys
from pathlib import Path

# ✅ FIX ROOT PATH
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import asyncio, random, uuid, re
from typing import List
from urllib.parse import quote_plus, urljoin

from config import cfg
from automation.playwright_runtime import run_with_browser_loop

# ---------------- CONFIG ----------------
_UA_LIST = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/121.0.0.0 Safari/537.36",
]

_ANTI_JS = """
Object.defineProperty(navigator,'webdriver',{get:()=>undefined});
Object.defineProperty(navigator,'plugins',{get:()=>[1,2,3,4,5]});
Object.defineProperty(navigator,'languages',{get:()=>['en-US','en']});
window.chrome={runtime:{},loadTimes:function(){},csi:function(){}};
"""

REAL_USER_AGENT = _UA_LIST[0]
ANTI_DETECTION_SCRIPT = _ANTI_JS

# ================= MAIN =================
class JobScraper:

    async def search_jobs(self, query, location, sites, max_results=30):
        return await run_with_browser_loop(
            self._search_jobs_impl, query, location, sites, max_results
        )

    async def _search_jobs_impl(self, query, location, sites, max_results=30):
        cfg.reload()

        email    = cfg.linkedin_email()
        password = cfg.linkedin_password()
        headless = cfg.headless()
        slow_mo  = cfg.slow_mo()
        timeout  = cfg.timeout()

        per_site = max(15, max_results // max(len(sites), 1))

        print(f"\n{'='*50}")
        print(f"[Scraper] Query={query} | Location={location}")
        print(f"[Scraper] LinkedIn Email: {email or 'NOT SET'}")
        print(f"{'='*50}")

        all_jobs = []

        try:
            from playwright.async_api import async_playwright
        except ImportError:
            print("[Scraper] Install playwright: playwright install chromium")
            return []

        try:
            async with async_playwright() as p:
                ctx = await p.chromium.launch_persistent_context(
                    user_data_dir=cfg.linkedin_user_data_dir(),
                    headless=headless,
                    slow_mo=slow_mo,
                    viewport={"width": 1366, "height": 768},
                    user_agent=random.choice(_UA_LIST),
                    args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
                )

                await ctx.add_init_script(_ANTI_JS)

                # -------- LINKEDIN --------
                if "linkedin" in sites:
                    page = await ctx.new_page()
                    try:
                        if email and password:
                            logged_in = await linkedin_login(page, email, password, timeout)
                            if logged_in:
                                jobs = await scrape_linkedin_loggedin(page, ctx, query, location, per_site, timeout)
                                if not jobs:
                                    print("[LinkedIn] Logged-in scrape returned 0 jobs, trying public fallback")
                                    jobs = await scrape_linkedin_public(page, query, location, per_site, timeout)
                            else:
                                jobs = await scrape_linkedin_public(page, query, location, per_site, timeout)
                        else:
                            jobs = await scrape_linkedin_public(page, query, location, per_site, timeout)

                        all_jobs.extend(jobs)
                        print(f"[LinkedIn] {len(jobs)} jobs")

                    except Exception as e:
                        print("[LinkedIn Error]", e)

                    await page.close()

                # -------- INDEED --------
                if "indeed" in sites:
                    page = await ctx.new_page()
                    try:
                        jobs = await scrape_indeed(page, query, location, per_site, timeout)
                        all_jobs.extend(jobs)
                    except Exception as e:
                        print("[Indeed Error]", e)
                    await page.close()

                # -------- WELLFOUND --------
                if "wellfound" in sites:
                    page = await ctx.new_page()
                    try:
                        jobs = await scrape_wellfound(page, query, location, per_site, timeout)
                        all_jobs.extend(jobs)
                    except Exception as e:
                        print("[Wellfound Error]", e)
                    await page.close()

                await ctx.close()
        except PermissionError as e:
            print(f"[Scraper] Browser launch blocked by OS permissions: {e}")
            return []
        except Exception as e:
            print(f"[Scraper] Browser launch/search failed: {e}")
            return []

            await ctx.close()

        # -------- DEDUP --------
        seen, unique = set(), []
        for job in all_jobs:
            key = job.get("url") or job.get("title", "")
            if key not in seen:
                seen.add(key)
                unique.append(job)

        print(f"[Scraper] Total jobs: {len(unique)}")
        return unique


# ================= LOGIN =================
async def linkedin_login(page, email, password, timeout):
    try:
        await page.goto("https://www.linkedin.com/feed/", timeout=timeout)
        await asyncio.sleep(2)
        if any(part in page.url for part in ("feed", "jobs", "mynetwork")):
            return True

        await page.goto("https://www.linkedin.com/login", timeout=timeout)
        await asyncio.sleep(2)

        await page.fill("#username", email)
        await page.fill("#password", password)
        await page.keyboard.press("Enter")

        await asyncio.sleep(5)
        return "feed" in page.url or "jobs" in page.url

    except:
        return False


async def linkedin_login_from_env(page):
    cfg.reload()
    return await linkedin_login(
        page,
        cfg.linkedin_email(),
        cfg.linkedin_password(),
        cfg.timeout(),
    )


async def scrape_linkedin_jobs(page, query, location, max_results=10):
    cfg.reload()
    return await scrape_linkedin_loggedin(
        page,
        page.context,
        query,
        location,
        max_results,
        cfg.timeout(),
    )


# ================= LINKEDIN (FINAL FIX) =================
async def scrape_linkedin_loggedin(page, ctx, query, location, limit, timeout):
    jobs = []

    try:
        search_url = (
            f"https://www.linkedin.com/jobs/search/"
            f"?keywords={quote_plus(query)}"
            f"&location={quote_plus(location)}"
            f"&f_AL=true&sortBy=DD"
        )

        print(f"[LinkedIn] URL: {search_url}")
        await page.goto(search_url, wait_until="domcontentloaded", timeout=timeout)
        await asyncio.sleep(4)

        # Scroll
        for _ in range(5):
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(1.5)

            try:
                panel = await page.query_selector(".jobs-search-results-list")
                if panel:
                    await panel.evaluate("el => el.scrollTop += 800")
            except:
                pass

        # -------- EXTRACT JOB IDs --------
        html = await page.content()
        job_ids = re.findall(r'/jobs/view/(\d{10,})', html)

        unique_ids = list(dict.fromkeys(job_ids))
        print(f"[LinkedIn] Found {len(unique_ids)} IDs")

        # Fallback
        if not unique_ids:
            cards = await page.query_selector_all("[data-job-id]")
            for c in cards:
                jid = await c.get_attribute("data-job-id")
                if jid:
                    unique_ids.append(jid)

        if not unique_ids:
            await page.screenshot(path="debug_no_ids.png")
            return jobs

        cards = await page.query_selector_all("[data-job-id]")
        for card in cards:
            try:
                jid = await card.get_attribute("data-job-id")
                if not jid or jid not in unique_ids:
                    continue

                text = (await card.inner_text()).strip()
                lines = [line.strip() for line in text.splitlines() if line.strip()]
                if not any("easy apply" in line.lower() for line in lines):
                    continue

                title = lines[0] if lines else query
                company = ""
                job_location = location
                for line in lines[1:]:
                    low = line.lower()
                    if line == title or "easy apply" in low or low in {"viewed", "promoted"}:
                        continue
                    if not company:
                        company = line
                    elif job_location == location:
                        job_location = line
                        break

                job_url = (
                    f"https://www.linkedin.com/jobs/search/"
                    f"?currentJobId={jid}"
                    f"&keywords={quote_plus(query)}"
                    f"&location={quote_plus(location)}"
                    f"&f_AL=true&sortBy=DD"
                )
                jobs.append({
                    "id": f"li-{jid}",
                    "title": title,
                    "company": company or "LinkedIn",
                    "location": job_location,
                    "url": job_url,
                    "description": text[:2000],
                    "salary": "",
                    "source": "linkedin",
                    "job_type": "full-time",
                    "easy_apply": True,
                })
                print(f"[LinkedIn] CARD OK {title} | {company or 'LinkedIn'}")
                if len(jobs) >= limit:
                    return jobs
            except Exception as e:
                print("[LinkedIn Card Error]", e)
                continue

        # -------- VISIT JOB PAGES --------
        job_data = [(jid, f"https://www.linkedin.com/jobs/view/{jid}") for jid in unique_ids[:limit]]

        for i, (jid, job_url) in enumerate(job_data):
            job_page = None
            try:
                print(f"[LinkedIn] [{i+1}] {job_url}")

                job_page = await ctx.new_page()
                await job_page.goto(job_url, timeout=20000)
                await asyncio.sleep(2)

                # Title
                title = ""
                for sel in [
                    ".job-details-jobs-unified-top-card__job-title h1",
                    ".job-details-jobs-unified-top-card__job-title",
                    ".jobs-unified-top-card__job-title h1",
                    ".jobs-unified-top-card__job-title",
                    ".t-24.t-bold.inline",
                    "h1.t-24",
                    "h1",
                ]:
                    el = await job_page.query_selector(sel)
                    if el:
                        title = (await el.inner_text()).strip()
                        if title:
                            break
                if not title:
                    page_title = (await job_page.title()).strip()
                    if page_title and "LinkedIn" in page_title:
                        title = page_title.split("|", 1)[0].strip()

                # Company
                company = ""
                for sel in [
                    ".job-details-jobs-unified-top-card__company-name a",
                    ".job-details-jobs-unified-top-card__company-name",
                    ".jobs-unified-top-card__company-name a",
                    ".jobs-unified-top-card__company-name",
                    ".topcard__org-name-link",
                ]:
                    el = await job_page.query_selector(sel)
                    if el:
                        company = (await el.inner_text()).strip()
                        if company:
                            break

                # Description
                desc = ""
                for sel in [".jobs-description", "#job-details", ".jobs-description__content", ".jobs-box__html-content"]:
                    el = await job_page.query_selector(sel)
                    if el:
                        desc = (await el.inner_text())[:2000]
                        if desc:
                            break

                easy_apply = False
                for sel in [
                    "button.jobs-apply-button",
                    ".jobs-apply-button--top-card button",
                    ".jobs-s-apply button",
                    "button[aria-label*='Easy Apply']",
                    "button:has-text('Easy Apply')",
                ]:
                    try:
                        btn = await job_page.query_selector(sel)
                        if btn and await btn.is_visible():
                            easy_apply = True
                            break
                    except:
                        continue

                await job_page.close()

                if title:
                    jobs.append({
                        "id": f"li-{jid}",
                        "title": title,
                        "company": company or "LinkedIn",
                        "location": location,
                        "url": job_url,
                        "description": desc,
                        "salary": "",
                        "source": "linkedin",
                        "job_type": "full-time",
                        "easy_apply": easy_apply,
                    })

                    print(f"[LinkedIn] OK {title} | Easy Apply={easy_apply}")

            except Exception as e:
                print("[LinkedIn Job Error]", e)
                if job_page:
                    try:
                        await job_page.close()
                    except:
                        pass

    except Exception as e:
        print("[LinkedIn Fatal Error]", e)

    return jobs


# ================= LINKEDIN PUBLIC =================
async def scrape_linkedin_public(page, query, location, limit, timeout):
    jobs = []

    search_url = f"https://www.linkedin.com/jobs/search/?keywords={quote_plus(query)}&location={quote_plus(location)}"
    await page.goto(search_url, wait_until="domcontentloaded", timeout=timeout)
    await asyncio.sleep(3)

    cards = await page.query_selector_all(".base-card")

    for card in cards[:limit]:
        try:
            title_el = await card.query_selector(".base-search-card__title")
            company_el = await card.query_selector(".base-search-card__subtitle")
            location_el = await card.query_selector(".job-search-card__location")
            link_el = await card.query_selector("a.base-card__full-link")

            title = (await title_el.inner_text()).strip() if title_el else (await card.inner_text()).strip()
            company = (await company_el.inner_text()).strip() if company_el else "LinkedIn"
            job_location = (await location_el.inner_text()).strip() if location_el else location
            href = await link_el.get_attribute("href") if link_el else ""
            job_url = href.split("?")[0] if href else ""
            if not job_url:
                continue

            jobs.append({
                "id": f"li-public-{abs(hash(job_url))}",
                "title": title,
                "company": company,
                "location": job_location,
                "url": job_url,
                "description": title,
                "source": "linkedin",
                "job_type": "full-time",
                "easy_apply": False,
            })
        except:
            continue

    return jobs


# ================= INDEED =================
async def scrape_indeed(page, query, location, limit, timeout):
    jobs = []

    search_url = f"https://in.indeed.com/jobs?q={quote_plus(query)}&l={quote_plus(location)}"
    await page.goto(search_url, wait_until="domcontentloaded", timeout=timeout)
    await asyncio.sleep(3)

    cards = await page.query_selector_all("[data-jk]")
    seen_jks = set()

    for card in cards[:limit]:
        try:
            jk = await card.get_attribute("data-jk")
            if jk and jk in seen_jks:
                continue
            if jk:
                seen_jks.add(jk)

            title_el = await card.query_selector("h2.jobTitle a, a[data-jk], a[href*='/viewjob']")
            title_span = await card.query_selector("h2.jobTitle span[title]")
            company_el = await card.query_selector("[data-testid='company-name'], .companyName")
            location_el = await card.query_selector("[data-testid='text-location'], .companyLocation")
            summary_el = await card.query_selector(".job-snippet, [data-testid='jobsnippet']")

            href = await title_el.get_attribute("href") if title_el else ""
            if jk:
                job_url = f"https://in.indeed.com/viewjob?jk={jk}"
            elif href:
                job_url = urljoin("https://in.indeed.com", href)
            else:
                continue

            title_attr = await title_span.get_attribute("title") if title_span else ""
            title = title_attr.strip() if title_attr else (await title_el.inner_text()).strip() if title_el else (await card.inner_text()).strip().splitlines()[0]
            company = (await company_el.inner_text()).strip() if company_el else "Indeed"
            job_location = (await location_el.inner_text()).strip() if location_el else location
            description = (await summary_el.inner_text()).strip() if summary_el else title

            jobs.append({
                "id": f"indeed-{jk or abs(hash(job_url))}",
                "title": title,
                "company": company,
                "location": job_location,
                "url": job_url,
                "description": description,
                "source": "indeed",
                "job_type": "full-time",
            })
        except:
            continue

    return jobs


# ================= WELLFOUND =================
async def scrape_wellfound(page, query, location, limit, timeout):
    jobs = []

    await page.goto(f"https://wellfound.com/jobs?q={quote_plus(query)}", wait_until="domcontentloaded", timeout=timeout)
    await asyncio.sleep(3)

    cards = await page.query_selector_all("[data-test='StartupResult']")

    for card in cards[:limit]:
        try:
            link_el = await card.query_selector("a[href*='/jobs/']")
            href = await link_el.get_attribute("href") if link_el else ""
            if not href:
                continue
            job_url = urljoin("https://wellfound.com", href)
            text = (await card.inner_text()).strip()
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            title = lines[0] if lines else query
            company = lines[1] if len(lines) > 1 else "Wellfound"

            jobs.append({
                "id": f"wellfound-{abs(hash(job_url))}",
                "title": title,
                "company": company,
                "location": location,
                "url": job_url,
                "description": text,
                "source": "wellfound",
                "job_type": "full-time",
            })
        except:
            continue

    return jobs
