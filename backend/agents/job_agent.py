"""
AutoApplier — LangGraph Agent (Industry Ready)
Uses central Config — no stale module-level env values.
Pipeline: profile → search → score → apply → finalize
"""
from __future__ import annotations

import sys
from pathlib import Path

# ✅ Project root ko path mein add karo (CORRECT WAY)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import asyncio, json, os, uuid
from datetime import datetime
import re
from urllib.parse import urlparse
from typing import Annotated, Any, Dict, List, Optional, TypedDict
import operator

from config import cfg

from langgraph.graph import END, StateGraph
from langgraph.checkpoint.memory import MemorySaver


def _ts(): return datetime.now().strftime("%H:%M:%S")


_PLACEHOLDER_HOSTS = {"example.com", "jobs.example.com", "localhost", "127.0.0.1"}


def _is_real_job(job: Dict[str, Any]) -> bool:
    url = (job.get("url") or "").strip()
    if not url:
        return False
    parsed = urlparse(url)
    host = (parsed.netloc or "").lower()
    if parsed.scheme not in {"http", "https"} or not host:
        return False
    return not any(host == h or host.endswith(f".{h}") for h in _PLACEHOLDER_HOSTS)


def _matches_requested_location(job: Dict[str, Any], requested_locations: List[str]) -> bool:
    job_location = (job.get("location") or "").strip().lower()
    if not job_location:
        return True
    if any(term in job_location for term in ("remote", "work from home", "anywhere")):
        return True

    for requested in requested_locations:
        req = (requested or "").strip().lower()
        if not req or req in {"any", "anywhere", "all"}:
            return True
        if req in {"remote", "work from home"}:
            if any(term in job_location for term in ("remote", "work from home", "anywhere")):
                return True
            continue
        if req in {"delhi", "new delhi", "delhi ncr", "ncr"}:
            if any(area in job_location for area in ("delhi", "new delhi", "noida", "gurugram", "gurgaon", "ncr")):
                if "india" in job_location:
                    return True
                if re.search(r",\s*[a-z]{2}\b", job_location):
                    return False
                if any(token in job_location for token in ("usa", "united states", "ohio", "kentucky")):
                    return False
                return True
            continue
        if req in job_location or job_location in req:
            return True
    return False


def _get_llm(temperature=0.3):
    cfg.reload()
    from langchain_groq import ChatGroq
    return ChatGroq(
        model=cfg.groq_model(),
        temperature=temperature,
        groq_api_key=cfg.groq_api_key(),
        max_tokens=2048,
    )


# ── State ─────────────────────────────────────────────────────────────────────
class AgentState(TypedDict):
    run_id:            str
    user_id:           str
    job_titles:        List[str]
    locations:         List[str]
    sites:             List[str]
    max_applications:  int
    min_match_score:   float
    profile:           Dict[str, Any]
    resume_text:       str
    raw_jobs:          List[Dict[str, Any]]
    scored_jobs:       List[Dict[str, Any]]
    current_job_index: int
    applications:      Annotated[List[Dict[str, Any]], operator.add]
    status:            str
    current_step:      str
    progress_pct:      float
    log_messages:      Annotated[List[str], operator.add]
    error:             Optional[str]


# ── Node 1: Profile ───────────────────────────────────────────────────────────
async def profile_analysis_node(state: AgentState) -> Dict[str, Any]:
    cfg.reload()
    profile = state["profile"]
    skills  = profile.get("skills") or []
    years   = profile.get("years_experience", 0)

    resume_text = state.get("resume_text") or profile.get("resume_text") or ""
    if not resume_text:
        exp_text = "\n".join(
            f"- {e.get('title')} at {e.get('company')} ({e.get('start_date')}–{e.get('end_date','Present')}): {e.get('description','')}"
            for e in (profile.get("experience") or [])[:5]
        )
        resume_text = (
            f"Name: {profile.get('full_name','')}\n"
            f"Skills: {', '.join(skills)}\nExperience: {years} years\n"
            f"EXPERIENCE:\n{exp_text}\nSUMMARY: {profile.get('summary','')}"
        ).strip()

    summary = cfg.summary()
    return {
        "resume_text":  resume_text,
        "current_step": "profile_analyzed",
        "progress_pct": 5.0,
        "status":       "running",
        "log_messages": [
            f"[{_ts()}] 🔍 Profile ready — {len(skills)} skills, {years} yrs exp",
            f"[{_ts()}] 🔑 LinkedIn: {summary['linkedin_email']}",
            f"[{_ts()}] 🤖 Groq: {'✅ configured' if summary['groq_configured'] else '❌ NOT SET'}",
            f"[{_ts()}] 🖥️  Browser: {'headless' if summary['headless'] else 'visible (screen pe dikhega)'}",
        ],
    }


# ── Node 2: Job Search ────────────────────────────────────────────────────────
async def job_search_node(state: AgentState) -> Dict[str, Any]:
    cfg.reload()
    from automation.job_scraper import JobScraper

    linkedin_sites = [site for site in state["sites"] if site == "linkedin"] or ["linkedin"]
    logs = [f"[{_ts()}] 🌐 Searching on: linkedin only"]
    all_jobs: List[Dict[str, Any]] = []
    scraper = JobScraper()

    for title in state["job_titles"][:3]:
        for loc in state["locations"][:2]:
            try:
                logs.append(f"[{_ts()}] 🔎 '{title}' in '{loc}'...")
                jobs = await scraper.search_jobs(
                    query=title, location=loc,
                    sites=linkedin_sites,
                    max_results=max(50, state["max_applications"] * 15),
                )
                all_jobs.extend(jobs)
                logs.append(f"[{_ts()}] {'✅' if jobs else '⚠️'} '{title}' → {len(jobs)} jobs")
            except Exception as e:
                detail = str(e) or repr(e)
                logs.append(f"[{_ts()}] ❌ Search error ({type(e).__name__}): {detail}")

    # Deduplicate and keep only real, applicable postings.
    seen: set = set()
    unique = []
    for job in all_jobs:
        if not _is_real_job(job):
            logs.append(f"[{_ts()}] Skipping non-real job URL: {job.get('title','Untitled')} ({job.get('url','missing URL')})")
            continue
        if job.get("source") != "linkedin":
            logs.append(f"[{_ts()}] Skipping non-LinkedIn job: {job.get('title','Untitled')} ({job.get('source','unknown')})")
            continue
        if job.get("source") == "linkedin" and job.get("easy_apply") is False:
            logs.append(f"[{_ts()}] Skipping LinkedIn job without Easy Apply: {job.get('title','Untitled')} @ {job.get('company','unknown')}")
            continue
        if not _matches_requested_location(job, state["locations"]):
            logs.append(f"[{_ts()}] Skipping location mismatch: {job.get('title','Untitled')} ({job.get('location','unknown')})")
            continue
        k = job.get("url") or (job.get("title","") + job.get("company",""))
        if k not in seen:
            seen.add(k); unique.append(job)

    if not unique:
        logs.append(f"[{_ts()}] No real job postings found. Demo fallback is disabled for production runs.")
        logs.append(f"[{_ts()}] Check credentials, selected sites, location, and backend scraper logs.")
    else:
        logs.append(f"[{_ts()}] {len(unique)} unique real jobs found.")

    return {"raw_jobs": unique, "current_step": "jobs_found", "progress_pct": 25.0, "log_messages": logs}


# ── Node 3: AI Scoring ────────────────────────────────────────────────────────
async def job_scoring_node(state: AgentState) -> Dict[str, Any]:
    cfg.reload()
    from langchain_core.messages import HumanMessage

    if not state["raw_jobs"]:
        return {
            "scored_jobs": [],
            "current_step": "no_real_jobs",
            "progress_pct": 40.0,
            "log_messages": [f"[{_ts()}] No real jobs to score or apply."],
        }

    logs = [f"[{_ts()}] 🤖 Scoring {len(state['raw_jobs'])} jobs with Groq AI..."]
    profile   = state["profile"]
    blacklist = {c.lower() for c in (profile.get("blacklisted_companies") or [])}
    llm       = _get_llm(temperature=0.1)
    scored: List[Dict[str, Any]] = []

    apply_target = max(1, state["max_applications"])
    jobs_to_score = state["raw_jobs"][:max(15, apply_target * 10)]
    chunk_size = 5

    for i in range(0, len(jobs_to_score), chunk_size):
        chunk = jobs_to_score[i:i+chunk_size]
        jobs_text = "\n\n".join(
            f"JOB {j+1}:\nTitle: {job.get('title','')}\nCompany: {job.get('company','')}\nDesc: {job.get('description','')[:400]}"
            for j, job in enumerate(chunk)
        )
        prompt = f"""Score these jobs 0-100 for this candidate. Be realistic.

CANDIDATE:
Skills: {', '.join(profile.get('skills') or [])}
Experience: {profile.get('years_experience',0)} years
Target Roles: {', '.join(state['job_titles'])}
Summary: {profile.get('summary','')[:200]}

JOBS:
{jobs_text}

Return ONLY a JSON array (no markdown):
[{{"job_index":1,"score":85,"reason":"Strong Python/SQL match"}}]"""

        try:
            res  = await llm.ainvoke([HumanMessage(content=prompt)])
            text = res.content.strip()
            if "```" in text:
                text = text.split("```")[1].lstrip("json").strip()
            scores = json.loads(text)
            for sd in scores:
                idx = sd.get("job_index",1) - 1
                if 0 <= idx < len(chunk):
                    job = chunk[idx].copy()
                    co  = job.get("company","").lower()
                    if any(bl in co for bl in blacklist):
                        job["match_score"] = 0
                    else:
                        job["match_score"]  = sd.get("score", 50)
                        job["score_reason"] = sd.get("reason","")
                    scored.append(job)
        except Exception as e:
            logs.append(f"[{_ts()}] ⚠️ Scoring batch error: {e}")
            for job in chunk:
                job["match_score"] = 55.0; scored.append(job)

    scored.sort(key=lambda x: x.get("match_score",0), reverse=True)
    qualified = [j for j in scored if j.get("match_score",0) >= state["min_match_score"]]
    candidate_limit = max(15, apply_target * 10)
    qualified = qualified[:candidate_limit]

    logs.append(f"[{_ts()}] ✅ {len(qualified)}/{len(scored)} candidates qualify for up to {state['max_applications']} application(s) (≥{state['min_match_score']:.0f}%)")
    if qualified:
        top = qualified[0]
        logs.append(f"[{_ts()}] 🏆 Best match: {top.get('title')} @ {top.get('company')} ({top.get('match_score',0):.0f}%)")
    else:
        logs.append(f"[{_ts()}] 💡 Lower Min Match Score or add more relevant skills to profile")

    return {"scored_jobs": qualified, "current_step": "jobs_scored", "progress_pct": 40.0, "log_messages": logs}


# ── Node 4: Apply ─────────────────────────────────────────────────────────────
async def apply_job_node(state: AgentState) -> Dict[str, Any]:
    cfg.reload()
    from automation.browser_agent import BrowserAgent
    from backend.utils.ai_utils import generate_cover_letter

    scored = state["scored_jobs"]
    idx    = state.get("current_job_index", 0)

    if idx >= len(scored):
        return {"current_step":"applications_complete","status":"completing",
                "log_messages":[f"[{_ts()}] ✅ All jobs processed"]}

    job  = scored[idx]
    logs = [f"[{_ts()}] 📝 [{idx+1}/{len(scored)}] {job.get('title')} @ {job.get('company')} (score:{job.get('match_score',0):.0f}%)"]

    # Generate cover letter
    try:
        cover = await generate_cover_letter(
            profile=state["profile"],
            job_title=job.get("title",""),
            company_name=job.get("company",""),
            job_description=job.get("description",""),
        )
        logs.append(f"[{_ts()}] ✍️  Cover letter generated ({len(cover)} chars)")
    except Exception as e:
        p = state["profile"]
        cover = (
            f"Dear Hiring Manager,\n\n"
            f"I am excited to apply for the {job.get('title','')} position at {job.get('company','')}. "
            f"With {p.get('years_experience',1)} year(s) in {', '.join((p.get('skills') or [])[:3])}, "
            f"I'm confident I can contribute effectively.\n\n"
            f"Best regards,\n{p.get('full_name','Candidate')}"
        )
        logs.append(f"[{_ts()}] ⚠️ Cover letter fallback: {e}")

    # Apply via browser
    agent  = BrowserAgent()
    result = await agent.apply_to_job(
        job_url=job.get("url",""),
        job=job, profile=state["profile"], cover_letter=cover,
    )

    icon = "✅" if result.get("status")=="applied" else "⏭️" if result.get("status")=="skipped" else "❌"
    err  = f" ({result.get('error','')})" if result.get("error") else ""
    logs.append(f"[{_ts()}] {icon} {result.get('status','failed').upper()} — {job.get('company')}{err}")

    record = {
        "id": str(uuid.uuid4()),
        "job_title":      job.get("title",""),
        "company_name":   job.get("company",""),
        "job_url":        job.get("url",""),
        "job_description":job.get("description","")[:3000],
        "job_location":   job.get("location",""),
        "salary_range":   job.get("salary",""),
        "job_type":       job.get("job_type","full-time"),
        "source_site":    job.get("source",""),
        "status":         result.get("status","failed"),
        "applied_at":     datetime.utcnow().isoformat() if result.get("status")=="applied" else None,
        "match_score":    job.get("match_score",0),
        "cover_letter":   cover,
        "ai_notes":       job.get("score_reason",""),
        "error_message":  result.get("error",""),
    }

    progress = 40.0 + ((idx+1)/len(scored))*55.0
    await asyncio.sleep(cfg.apply_delay())

    return {"current_job_index":idx+1,"applications":[record],"progress_pct":progress,"log_messages":logs}


# ── Node 5: Finalize ──────────────────────────────────────────────────────────
async def finalize_node(state: AgentState) -> Dict[str, Any]:
    apps    = state.get("applications",[])
    applied = sum(1 for a in apps if a.get("status")=="applied")
    failed  = sum(1 for a in apps if a.get("status")=="failed")
    skipped = sum(1 for a in apps if a.get("status")=="skipped")
    return {
        "status":"completed","current_step":"completed","progress_pct":100.0,
        "log_messages":[
            f"[{_ts()}] 🎉 Done! ✅ Applied:{applied} ❌ Failed:{failed} ⏭️ Skipped:{skipped}",
            f"[{_ts()}] 📊 Check Applications tab for full list",
        ],
    }


# ── Routing ───────────────────────────────────────────────────────────────────
def _route(state: AgentState) -> str:
    idx     = state.get("current_job_index",0)
    jobs    = state.get("scored_jobs",[])
    max_app = state.get("max_applications",20)
    applied = sum(1 for a in state.get("applications",[]) if a.get("status")=="applied")
    return "finalize" if (idx >= len(jobs) or applied >= max_app) else "apply_next"


# ── Build & Run ───────────────────────────────────────────────────────────────
def build_graph():
    g = StateGraph(AgentState)
    g.add_node("profile_analysis", profile_analysis_node)
    g.add_node("job_search",       job_search_node)
    g.add_node("job_scoring",      job_scoring_node)
    g.add_node("apply_job",        apply_job_node)
    g.add_node("finalize",         finalize_node)
    g.set_entry_point("profile_analysis")
    g.add_edge("profile_analysis","job_search")
    g.add_edge("job_search","job_scoring")
    g.add_edge("job_scoring","apply_job")
    g.add_conditional_edges("apply_job",_route,{"apply_next":"apply_job","finalize":"finalize"})
    g.add_edge("finalize",END)
    return g.compile(checkpointer=MemorySaver())


class JobApplicationAgent:
    def __init__(self): self.graph = build_graph()

    async def run(self, run_id, user_id, profile, job_titles, locations,
                  sites, max_applications=20, min_match_score=60.0, on_update=None):
        cfg.reload()
        initial: AgentState = {
            "run_id":run_id,"user_id":user_id,"job_titles":job_titles,
            "locations":locations,"sites":sites,"max_applications":max_applications,
            "min_match_score":min_match_score,"profile":profile,
            "resume_text":profile.get("resume_text",""),
            "raw_jobs":[],"scored_jobs":[],"current_job_index":0,"applications":[],
            "status":"running","current_step":"starting","progress_pct":0.0,
            "log_messages":[f"[{_ts()}] 🚀 Agent started — {run_id[:8]}"],
            "error":None,
        }
        config = {"configurable":{"thread_id":run_id}}
        final  = {}
        async for chunk in self.graph.astream(initial, config=config):
            for node_name, node_out in chunk.items():
                if isinstance(node_out, dict) and on_update:
                    await on_update(run_id, node_name, node_out)
            final = chunk
        return final
