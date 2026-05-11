from __future__ import annotations
import asyncio, os, random, sys, tempfile
from pathlib import Path
from typing import Any, Dict
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import cfg
from automation.playwright_runtime import run_with_browser_loop

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
_ANTI = """
Object.defineProperty(navigator,'webdriver',{get:()=>undefined});
Object.defineProperty(navigator,'plugins',{get:()=>[1,2,3,4,5]});
window.chrome={runtime:{},loadTimes:function(){},csi:function(){}};
"""
_PLACEHOLDER_HOSTS = {"example.com", "jobs.example.com", "localhost", "127.0.0.1"}

async def _wait(lo=0.4, hi=1.5):
    await asyncio.sleep(random.uniform(lo, hi))


async def _first_visible(page, selectors, timeout_ms=0):
    for sel in selectors:
        try:
            if timeout_ms:
                el = await page.wait_for_selector(sel, timeout=timeout_ms, state="visible")
            else:
                el = await page.query_selector(sel)
            if el and await el.is_visible():
                return el
        except:
            continue
    return None


def _make_resume_txt(profile: Dict[str, Any]) -> str:
    resume_text = (profile.get("resume_text") or "").strip()
    if not resume_text:
        resume_text = "\n".join([
            profile.get("full_name", "Candidate"),
            profile.get("email", ""),
            profile.get("phone", ""),
            profile.get("location", ""),
            "",
            profile.get("summary", ""),
            "",
            "Skills: " + ", ".join(profile.get("skills") or []),
        ]).strip()

    fd, path = tempfile.mkstemp(prefix="autoapplier_resume_", suffix=".txt", text=True)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(resume_text)
    return path


async def _upload_resume_if_present(page, profile):
    path = _make_resume_txt(profile)
    uploaded = False
    try:
        inputs = await page.query_selector_all("input[type='file']")
        for inp in inputs:
            try:
                accept = (await inp.get_attribute("accept") or "").lower()
                name = (await inp.get_attribute("name") or "").lower()
                aria = (await inp.get_attribute("aria-label") or "").lower()
                hint = f"{accept} {name} {aria}"
                if not hint.strip() or any(k in hint for k in ["resume", "cv", ".txt", ".pdf", ".doc"]):
                    await inp.set_input_files(path)
                    uploaded = True
                    await asyncio.sleep(1)
                    break
            except:
                continue
    finally:
        try:
            os.remove(path)
        except:
            pass
    return uploaded


class BrowserAgent:

    async def apply_to_job(self, job_url, job, profile, cover_letter):
        return await run_with_browser_loop(
            self._apply_to_job_impl, job_url, job, profile, cover_letter
        )

    async def _apply_to_job_impl(self, job_url, job, profile, cover_letter):
        cfg.reload()
        parsed = urlparse((job_url or "").strip())
        host = (parsed.netloc or "").lower()
        if parsed.scheme not in {"http", "https"} or not host:
            return {"status": "failed", "error": "Missing or invalid job URL"}
        if any(host == h or host.endswith(f".{h}") for h in _PLACEHOLDER_HOSTS):
            return {"status": "failed", "error": "Refusing placeholder/demo job URL"}

        try:
            from playwright.async_api import async_playwright
            async with async_playwright() as p:
                if "linkedin.com" in job_url:
                    ctx = await p.chromium.launch_persistent_context(
                        user_data_dir=cfg.linkedin_user_data_dir(),
                        headless=cfg.headless(), slow_mo=cfg.slow_mo(),
                        viewport={"width":1366,"height":768},
                        user_agent=_UA, locale="en-US",
                        args=["--no-sandbox","--disable-blink-features=AutomationControlled"],
                    )
                    browser = None
                else:
                    browser = await p.chromium.launch(
                        headless=cfg.headless(), slow_mo=cfg.slow_mo(),
                        args=["--no-sandbox","--disable-blink-features=AutomationControlled"],
                    )
                    ctx = await browser.new_context(
                    viewport={"width":1366,"height":768},
                    user_agent=_UA, locale="en-US",
                    )
                await ctx.add_init_script(_ANTI)
                page = await ctx.new_page()
                page.set_default_timeout(cfg.timeout())

                if "linkedin.com" in job_url:
                    result = await _apply_linkedin(page, job_url, profile, cover_letter)
                elif "indeed.com" in job_url:
                    result = await _apply_indeed(page, job_url, profile, cover_letter)
                elif "wellfound.com" in job_url:
                    result = await _apply_wellfound(page, job_url, profile, cover_letter)
                elif any(x in job_url for x in ["greenhouse.io","lever.co","workday","taleo"]):
                    result = await _apply_ats(page, job_url, profile, cover_letter)
                else:
                    result = await _apply_generic(page, job_url, profile, cover_letter)

                await ctx.close()
                if browser:
                    await browser.close()
                return result
        except Exception as e:
            import traceback; traceback.print_exc()
            return {"status":"failed","error":str(e)}


async def _apply_linkedin(page, url, profile, cover_letter):
    from automation.job_scraper import linkedin_login
    try:
        email    = cfg.linkedin_email()
        password = cfg.linkedin_password()

        await page.goto("https://www.linkedin.com/feed/",
                        wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(2)

        if not any(x in page.url for x in ["feed","mynetwork","jobs"]):
            if not email or not password:
                return {"status":"failed","error":"LinkedIn credentials missing in .env"}
            ok = await linkedin_login(page, email, password, cfg.timeout())
            if not ok:
                return {"status":"failed","error":"LinkedIn login failed"}

        await page.goto(url, wait_until="domcontentloaded", timeout=cfg.timeout())
        await asyncio.sleep(3)

        if "/jobs/search/" in url:
            current_job_id = ""
            if "currentJobId=" in url:
                current_job_id = url.split("currentJobId=", 1)[1].split("&", 1)[0]
            if current_job_id:
                try:
                    card = await page.query_selector(f"[data-job-id='{current_job_id}']")
                    if card:
                        await card.click()
                        await asyncio.sleep(2)
                except:
                    pass
            else:
                cards = await page.query_selector_all("[data-job-id]")
                for card in cards:
                    try:
                        if "easy apply" in (await card.inner_text()).lower():
                            await card.click()
                            await asyncio.sleep(2)
                            break
                    except:
                        continue

        easy_btn = await _first_visible(page, [
            "button.jobs-apply-button",
            ".jobs-apply-button--top-card button",
            ".jobs-s-apply button",
            "button[aria-label*='Easy Apply']",
            "button[data-control-name*='apply']",
            "button:has-text('Easy Apply')",
        ], timeout_ms=10000)

        if not easy_btn:
            return {"status":"skipped","error":"Easy Apply button not found"}

        await easy_btn.click()
        await asyncio.sleep(2)

        for step in range(15):
            await asyncio.sleep(1.5)
            print(f"[Apply] Step {step+1}")
            await _fill_fields(page, profile, cover_letter)

            submit = await _first_visible(page, [
                "button[aria-label='Submit application']",
                "button[aria-label*='Submit application']",
                "button:has-text('Submit application')",
                "button:has-text('Submit')",
            ])

            if submit:
                await submit.click(); await asyncio.sleep(3)
                print("[Apply] SUBMITTED")
                try:
                    done = await page.query_selector("button[aria-label='Dismiss'],button:has-text('Done')")
                    if done: await done.click()
                except: pass
                return {"status":"applied","error":None}

            nxt = await _first_visible(page, [
                "button[aria-label='Continue to next step']",
                "button[aria-label='Review your application']",
                "button[aria-label*='Continue']",
                "button[aria-label*='Review']",
                "button:has-text('Next')",
                "button:has-text('Review')",
                "button:has-text('Continue')",
            ])

            if nxt: await nxt.click(); await asyncio.sleep(1.5); continue
            break

        return {"status":"failed","error":"Could not reach submit"}
    except Exception as e:
        return {"status":"failed","error":f"LinkedIn: {e}"}


async def _fill_fields(page, profile, cover_letter):
    name_parts = (profile.get("full_name") or "").split()
    first = name_parts[0] if name_parts else ""
    last  = name_parts[-1] if len(name_parts) > 1 else ""

    inputs = await page.query_selector_all("input[type='text']:not([disabled]):not([readonly])")
    for inp in inputs:
        try:
            if (await inp.input_value()).strip(): continue
            aria = (await inp.get_attribute("aria-label") or "").lower()
            iid  = (await inp.get_attribute("id") or "").lower()
            h    = aria + " " + iid
            for keys, val in [
                (("first","given"),           first),
                (("last","family","sur"),      last),
                (("phone","mobile","tel"),     profile.get("phone","")),
                (("email",),                  profile.get("email","")),
                (("linkedin",),               profile.get("linkedin_url","")),
                (("github","portfolio","website"), profile.get("github_url","") or profile.get("portfolio_url","")),
                (("city","location"),          profile.get("location","")),
                (("salary","ctc"),             str(profile.get("salary_min") or 600000)),
                (("experience","years"),       str(profile.get("years_experience") or 1)),
            ]:
                if val and any(k in h for k in keys):
                    await inp.fill(val)
                    if any(k in h for k in ("city","location")):
                        await asyncio.sleep(1.2)
                        sug = await page.query_selector(".basic-typeahead__selectable,[role='option']")
                        if sug: await sug.click()
                    break
        except: continue

    for ta in await page.query_selector_all("textarea:not([disabled])"):
        try:
            if (await ta.input_value()).strip(): continue
            aria = (await ta.get_attribute("aria-label") or "").lower()
            ph   = (await ta.get_attribute("placeholder") or "").lower()
            h    = aria + " " + ph
            if any(k in h for k in ["cover","letter","message","additional","tell","why"]):
                await ta.fill(cover_letter[:2000])
            elif any(k in h for k in ["summary","about"]):
                await ta.fill(profile.get("summary","")[:500])
        except: continue

    for ni in await page.query_selector_all("input[type='number']:not([disabled])"):
        try:
            if (await ni.input_value()).strip(): continue
            aria = (await ni.get_attribute("aria-label") or "").lower()
            if any(k in aria for k in ["salary","ctc"]): await ni.fill(str(profile.get("salary_min") or 600000))
            elif any(k in aria for k in ["year","exp"]): await ni.fill(str(profile.get("years_experience") or 1))
            else: await ni.fill("1")
        except: continue

    for r in (await page.query_selector_all("input[type='radio']:not([disabled])"))[:8]:
        try:
            val = (await r.get_attribute("value") or "").lower()
            if val in ["yes","true","1"] and not await r.is_checked():
                await r.click(); await asyncio.sleep(0.3)
        except: continue

    for sel_el in await page.query_selector_all("select:not([disabled])"):
        try:
            aria = (await sel_el.get_attribute("aria-label") or "").lower()
            opts = await sel_el.query_selector_all("option")
            opt_list = [(await o.get_attribute("value") or "", await o.inner_text()) for o in opts]
            if "country" in aria:
                for v, t in opt_list:
                    if "india" in t.lower(): await sel_el.select_option(value=v); break
            elif any(k in aria for k in ["year","exp"]):
                yrs = profile.get("years_experience") or 1
                for v, t in opt_list:
                    try:
                        n = int(''.join(c for c in t.split()[0] if c.isdigit()) or "0")
                        if abs(n - yrs) <= 1: await sel_el.select_option(value=v); break
                    except: continue
            elif any(k in aria for k in ["authoriz","visa","sponsor"]):
                for v, t in opt_list:
                    if "yes" in t.lower(): await sel_el.select_option(value=v); break
        except: continue


async def _apply_indeed(page, url, profile, cover_letter):
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=cfg.timeout())
        await asyncio.sleep(2)
        apply_btn = await _first_visible(page, [
            "button#indeedApplyButton",
            "[data-testid='indeedApplyButton']",
            "button:has-text('Apply now')",
            "a:has-text('Apply now')",
            "button:has-text('Apply')",
            "a:has-text('Apply')",
            "a[id*='apply']",
        ], timeout_ms=8000)
        if not apply_btn: return {"status":"skipped","error":"Indeed apply button not found"}
        await apply_btn.click(); await asyncio.sleep(3)
        name = (profile.get("full_name") or "").split()
        for sels, val in [
            (["input[name='name.given']"],  name[0] if name else ""),
            (["input[name='name.family']"], name[-1] if len(name)>1 else ""),
            (["input[type='email']"],        profile.get("email","")),
            (["input[name='phoneNumber']","input[type='tel']"], profile.get("phone","")),
        ]:
            if not val: continue
            for s in sels:
                try:
                    f = await page.query_selector(s)
                    if f: await f.fill(val); break
                except: continue
        for s in ["textarea[name='coverletter']","textarea[id*='cover']"]:
            try:
                f = await page.query_selector(s)
                if f: await f.fill(cover_letter[:3000]); break
            except: continue
        for s in ["button[type='submit']","button:has-text('Submit')"]:
            try:
                sub = await page.query_selector(s)
                if sub and await sub.is_visible():
                    await sub.click(); await asyncio.sleep(3)
                    return {"status":"applied","error":None}
            except: continue
        return {"status":"failed","error":"Indeed submit not found"}
    except Exception as e:
        return {"status":"failed","error":f"Indeed: {e}"}


async def _apply_wellfound(page, url, profile, cover_letter):
    try:
        await page.goto(url, wait_until="networkidle", timeout=cfg.timeout())
        await asyncio.sleep(3)
        apply_btn = None
        for sel in ["button:has-text('Apply')","button:has-text('Apply Now')"]:
            try:
                b = await page.wait_for_selector(sel, timeout=6000)
                if b: apply_btn = b; break
            except: continue
        if not apply_btn: return {"status":"skipped","error":"Wellfound apply not found"}
        await apply_btn.click(); await asyncio.sleep(2)
        for s in ["textarea[placeholder*='intro' i]","textarea"]:
            try:
                f = await page.query_selector(s)
                if f: await f.fill(cover_letter[:1000]); break
            except: continue
        for s in ["button[type='submit']","button:has-text('Submit')"]:
            try:
                sub = await page.query_selector(s)
                if sub and await sub.is_visible():
                    await sub.click(); await asyncio.sleep(3)
                    return {"status":"applied","error":None}
            except: continue
        return {"status":"failed","error":"Wellfound submit not found"}
    except Exception as e:
        return {"status":"failed","error":f"Wellfound: {e}"}


async def _apply_ats(page, url, profile, cover_letter):
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=cfg.timeout())
        await asyncio.sleep(2)
        name = (profile.get("full_name") or "").split()
        first = name[0] if name else ""
        last  = name[-1] if len(name)>1 else ""
        for sels, val in [
            (["input[id*='first']","input[name='first_name']","input[name*='first_name']"], first),
            (["input[id*='last']", "input[name='last_name']","input[name*='last_name']"],  last),
            (["input[type='email']"],                            profile.get("email","")),
            (["input[type='tel']","input[id*='phone']","input[name='phone']","input[name*='phone']"], profile.get("phone","")),
            (["input[id*='linkedin']","input[name*='linkedin' i]"], profile.get("linkedin_url","")),
            (["input[id*='location']","input[name*='location' i]"], profile.get("location","")),
            (["input[id*='country']","input[name*='country' i]"], "India"),
        ]:
            if not val: continue
            for s in sels:
                try:
                    f = await page.query_selector(s)
                    if f: await f.fill(val); break
                except: continue

        await _upload_resume_if_present(page, profile)

        for s in ["textarea[name='cover_letter']","textarea[id*='cover']","textarea[aria-label*='cover' i]"]:
            try:
                f = await page.query_selector(s)
                if f: await f.fill(cover_letter[:3000]); break
            except: continue
        for s in ["input[type='submit']","button[type='submit']","button:has-text('Submit')"]:
            try:
                sub = await page.query_selector(s)
                if sub and await sub.is_visible():
                    await sub.click(); await asyncio.sleep(3)
                    return {"status":"applied","error":None}
            except: continue
        return {"status":"failed","error":"ATS submit not found"}
    except Exception as e:
        return {"status":"failed","error":f"ATS: {e}"}


async def _apply_generic(page, url, profile, cover_letter):
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=cfg.timeout())
        await asyncio.sleep(2)
        for text in ["Apply Now","Apply","Easy Apply","Quick Apply"]:
            try:
                btn = await page.query_selector(f"button:has-text('{text}'),a:has-text('{text}')")
                if btn and await btn.is_visible():
                    await btn.click()
                    await asyncio.sleep(3)
                    await _fill_fields(page, profile, cover_letter)
                    for sel in ["input[type='submit']","button[type='submit']","button:has-text('Submit')","button:has-text('Submit application')"]:
                        try:
                            sub = await page.query_selector(sel)
                            if sub and await sub.is_visible():
                                await sub.click()
                                await asyncio.sleep(3)
                                return {"status":"applied","error":None}
                        except:
                            continue
                    return {"status":"skipped","error":"Apply flow opened, but no submit confirmation was detected"}
            except: continue
        return {"status":"skipped","error":"No apply button found"}
    except Exception as e:
        return {"status":"failed","error":f"Generic: {e}"}
