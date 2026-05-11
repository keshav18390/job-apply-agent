from __future__ import annotations

import asyncio
import os
from pathlib import Path

from dotenv import load_dotenv

from automation.job_scraper import (
    ANTI_DETECTION_SCRIPT,
    REAL_USER_AGENT,
    linkedin_login_from_env,
    scrape_linkedin_jobs,
)


ROOT = Path(__file__).resolve().parent
DEBUG_DIR = ROOT / "debug_screenshots"


def load_env_for_test() -> None:
    env_path = ROOT / ".env"
    if env_path.exists():
        load_dotenv(env_path, override=True)
        print(f"[Test] .env loaded from: {env_path}")
    else:
        load_dotenv(override=True)
        print("[Test] .env missing at project root")


async def save_test_screenshot(page, name: str) -> None:
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    path = DEBUG_DIR / f"test_{name}.png"
    await page.screenshot(path=str(path), full_page=True)
    print(f"[Test] Screenshot saved: {path}")


async def main() -> None:
    load_env_for_test()

    email = os.getenv("LINKEDIN_EMAIL", "").strip()
    password = os.getenv("LINKEDIN_PASSWORD", "").strip()
    if not email or not password:
        print("[Test] FAIL: LINKEDIN_EMAIL or LINKEDIN_PASSWORD missing in .env")
        return

    query = os.getenv("TEST_JOB_QUERY", "data analyst")
    location = os.getenv("TEST_JOB_LOCATION", "Remote")
    max_results = int(os.getenv("TEST_MAX_RESULTS", "10"))

    print("=" * 72)
    print("[Test] LinkedIn scraper standalone test")
    print(f"[Test] Query: {query}")
    print(f"[Test] Location: {location}")
    print(f"[Test] Max results: {max_results}")
    print("[Test] Browser: Chromium, headless=False")
    print("=" * 72)

    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            slow_mo=int(os.getenv("PLAYWRIGHT_SLOW_MO", "80")),
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-infobars",
                "--no-sandbox",
                "--start-maximized",
            ],
        )
        context = await browser.new_context(
            viewport={"width": 1366, "height": 768},
            user_agent=REAL_USER_AGENT,
            locale="en-US",
            timezone_id="Asia/Kolkata",
        )
        await context.add_init_script(ANTI_DETECTION_SCRIPT)
        page = await context.new_page()
        page.set_default_timeout(30000)

        try:
            print("[Test] Step 1: Testing LinkedIn login...")
            logged_in = await linkedin_login_from_env(page)
            if not logged_in:
                print(f"[Test] FAIL: Login failed. URL: {page.url}")
                await save_test_screenshot(page, "login_failed")
                return

            print("[Test] PASS: Login successful")
            print("[Test] Step 2: Testing Easy Apply job scraping...")
            jobs = await scrape_linkedin_jobs(page, query, location, max_results)

            print("=" * 72)
            print(f"[Test] Scrape result: {len(jobs)} jobs")
            for idx, job in enumerate(jobs, start=1):
                print("-" * 72)
                print(f"[Test] #{idx}")
                print(f"Title: {job.get('title')}")
                print(f"Company: {job.get('company')}")
                print(f"Location: {job.get('location')}")
                print(f"URL: {job.get('url')}")
                print(f"Description chars: {len(job.get('description', ''))}")

            if not jobs:
                print("[Test] FAIL: Login worked but scraper returned 0 jobs")
                print(f"[Test] Exact URL: {page.url}")
                await save_test_screenshot(page, "zero_jobs")
            else:
                print("[Test] PASS: Scraper returned real LinkedIn jobs")
        except Exception as exc:
            print(f"[Test] ERROR: {type(exc).__name__}: {exc}")
            print(f"[Test] Exact URL: {page.url}")
            await save_test_screenshot(page, "exception")
        finally:
            print("[Test] Closing browser")
            await context.close()
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
