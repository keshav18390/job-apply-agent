"""
AutoApplier — FastAPI Backend (complete)
All routes:
  /auth/register  /auth/login  /auth/me
  /profile/{user_id}  GET · PUT · POST /resume
  /agent/run  POST · GET  /agent/runs/{user_id}
  /agent/run/{run_id}  GET · stop · stream(SSE)
  /applications/{user_id}  GET  · /{app_id} GET · DELETE
  /ai/resume/{user_id}     POST
  /ai/cover-letter/{user_id} POST
  /ai/score-job/{user_id}  POST
  /ai/interview-tips/{user_id} POST
  /ai/pdf/resume          POST → PDF download
  /ai/pdf/cover-letter    POST → PDF download
  /dashboard/{user_id}    GET
  /health                 GET
"""
from __future__ import annotations

import asyncio
import json
import os
import uuid
from collections import Counter, defaultdict
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from fastapi import (
    BackgroundTasks, Depends, FastAPI, File,
    HTTPException, Query, UploadFile,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.database import (
    AgentRun, AsyncSessionLocal, GeneratedDocument,
    JobApplication, User, UserProfile, get_db, init_db,
)
from backend.models.schemas import (
    AgentRunCreate, AgentRunResponse, CoverLetterRequest,
    DashboardStats, JobApplicationResponse, ResumeGenerateRequest,
    Token, UserCreate, UserLogin, UserProfileCreate,
    UserProfileResponse, UserResponse,
)
from backend.utils.ai_utils import (
    generate_cover_letter, generate_interview_tips,
    generate_resume, score_job_match,
)
from backend.utils.auth import (
    create_access_token, decode_token,
    hash_password, password_needs_refresh, verify_password,
)
from backend.utils.pdf_export import (
    cover_letter_to_pdf_bytes, resume_text_to_pdf_bytes,
)

load_dotenv()

# ── in-memory SSE state ───────────────────────────────────────────────────────
_active_runs: Dict[str, Dict[str, Any]] = {}

bearer_scheme = HTTPBearer(auto_error=False)


# ── lifespan ──────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    os.makedirs("data", exist_ok=True)
    await init_db()
    yield


app = FastAPI(
    title="AutoApplier API",
    description="AI job application automation — powered by Groq LLM (free)",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ══════════════════════════════════════════════════════════════════════════════
# INTERNAL HELPERS
# ══════════════════════════════════════════════════════════════════════════════

async def _require_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    if not credentials:
        raise HTTPException(401, "Not authenticated")
    payload = decode_token(credentials.credentials)
    if not payload:
        raise HTTPException(401, "Invalid or expired token")
    uid = payload.get("sub", "")
    res = await db.execute(select(User).where(User.id == uid))
    user = res.scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(401, "User not found or deactivated")
    return user


def _ensure_owner(user_id: str, current_user: User) -> None:
    if current_user.id != user_id:
        raise HTTPException(403, "You can only access your own account data")


async def _profile_dict(user_id: str, db: AsyncSession) -> Dict[str, Any]:
    u = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    p = (await db.execute(select(UserProfile).where(UserProfile.user_id == user_id))).scalar_one_or_none()
    if not u:
        return {}
    return {
        "full_name":            u.full_name or "",
        "email":                u.email or "",
        "phone":                (p.phone or "")               if p else "",
        "location":             (p.location or "")            if p else "",
        "linkedin_url":         (p.linkedin_url or "")        if p else "",
        "github_url":           (p.github_url or "")          if p else "",
        "portfolio_url":        (p.portfolio_url or "")       if p else "",
        "years_experience":     (p.years_experience or 0)     if p else 0,
        "skills":               (p.skills or [])              if p else [],
        "experience":           (p.experience or [])          if p else [],
        "education":            (p.education or [])           if p else [],
        "summary":              (p.summary or "")             if p else "",
        "blacklisted_companies":(p.blacklisted_companies or []) if p else [],
        "resume_text":          (p.resume_text or "")         if p else "",
        "job_titles":           (p.job_titles or [])          if p else [],
        "preferred_locations":  (p.preferred_locations or ["Remote"]) if p else ["Remote"],
        "salary_min":           p.salary_min                  if p else None,
        "salary_max":           p.salary_max                  if p else None,
        "work_authorization":   (p.work_authorization or "")  if p else "",
        "job_types":            (p.job_types or [])           if p else [],
    }


# ══════════════════════════════════════════════════════════════════════════════
# AUTH
# ══════════════════════════════════════════════════════════════════════════════

@app.post("/auth/register", response_model=Token, tags=["Auth"])
async def register(body: UserCreate, db: AsyncSession = Depends(get_db)):
    dup = (await db.execute(select(User).where(User.email == body.email))).scalar_one_or_none()
    if dup:
        raise HTTPException(400, "Email already registered")
    user = User(
        id=str(uuid.uuid4()),
        email=body.email,
        hashed_password=hash_password(body.password),
        full_name=body.full_name,
    )
    db.add(user)
    db.add(UserProfile(
        id=str(uuid.uuid4()), user_id=user.id,
        job_titles=[], skills=[], preferred_locations=["Remote"],
        blacklisted_companies=[], job_types=["full-time","remote"],
        experience=[], education=[],
    ))
    await db.commit()
    return {"access_token": create_access_token({"sub": user.id}), "token_type": "bearer"}


@app.post("/auth/login", response_model=Token, tags=["Auth"])
async def login(body: UserLogin, db: AsyncSession = Depends(get_db)):
    res = (await db.execute(select(User).where(User.email == body.email))).scalar_one_or_none()
    if not res or not verify_password(body.password, res.hashed_password):
        raise HTTPException(401, "Invalid email or password")
    if password_needs_refresh(res.hashed_password):
        res.hashed_password = hash_password(body.password)
        await db.commit()
    return {"access_token": create_access_token({"sub": res.id}), "token_type": "bearer"}


@app.get("/auth/me", response_model=UserResponse, tags=["Auth"])
async def get_me(current_user: User = Depends(_require_user)):
    return current_user


# ══════════════════════════════════════════════════════════════════════════════
# PROFILE
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/profile/{user_id}", response_model=UserProfileResponse, tags=["Profile"])
async def get_profile(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_require_user),
):
    _ensure_owner(user_id, current_user)
    res = (await db.execute(select(UserProfile).where(UserProfile.user_id == user_id))).scalar_one_or_none()
    if not res:
        raise HTTPException(404, "Profile not found")
    return UserProfileResponse.model_validate(res)


@app.put("/profile/{user_id}", response_model=UserProfileResponse, tags=["Profile"])
async def update_profile(
    user_id: str,
    body: UserProfileCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_require_user),
):
    _ensure_owner(user_id, current_user)
    res = (await db.execute(select(UserProfile).where(UserProfile.user_id == user_id))).scalar_one_or_none()
    if not res:
        res = UserProfile(id=str(uuid.uuid4()), user_id=user_id)
        db.add(res)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(res, field, value)
    res.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(res)
    return UserProfileResponse.model_validate(res)


@app.post("/profile/{user_id}/resume", tags=["Profile"])
async def upload_resume(
    user_id: str,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_require_user),
):
    _ensure_owner(user_id, current_user)
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Only PDF files are accepted")
    content = await file.read()
    text = ""
    try:
        import io, PyPDF2
        reader = PyPDF2.PdfReader(io.BytesIO(content))
        for pg in reader.pages:
            text += (pg.extract_text() or "") + "\n"
    except Exception:
        text = f"[Could not parse {file.filename}]"

    res = (await db.execute(select(UserProfile).where(UserProfile.user_id == user_id))).scalar_one_or_none()
    if res:
        res.resume_text = text.strip()
        res.resume_filename = file.filename
        await db.commit()
    return {"filename": file.filename, "characters_extracted": len(text), "success": len(text) > 30}


# ══════════════════════════════════════════════════════════════════════════════
# AGENT RUNS
# ══════════════════════════════════════════════════════════════════════════════

@app.post("/agent/run", response_model=AgentRunResponse, tags=["Agent"])
async def create_run(
    user_id: str,
    body: AgentRunCreate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_require_user),
):
    _ensure_owner(user_id, current_user)
    run_id = str(uuid.uuid4())
    run = AgentRun(
        id=run_id, user_id=user_id,
        job_titles=body.job_titles, locations=body.locations,
        sites=body.sites, max_applications=body.max_applications,
        min_match_score=body.min_match_score,
        status="queued", current_step="queued",
        progress_pct=0.0, total_found=0, total_applied=0,
        total_failed=0, total_skipped=0, log_messages=[],
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)
    background_tasks.add_task(_run_agent_bg, run_id, user_id, body)
    return AgentRunResponse.model_validate(run)


@app.get("/agent/runs/{user_id}", response_model=List[AgentRunResponse], tags=["Agent"])
async def list_runs(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_require_user),
):
    _ensure_owner(user_id, current_user)
    res = await db.execute(
        select(AgentRun).where(AgentRun.user_id == user_id)
        .order_by(desc(AgentRun.created_at)).limit(30)
    )
    return [AgentRunResponse.model_validate(r) for r in res.scalars().all()]


@app.get("/agent/run/{run_id}", response_model=AgentRunResponse, tags=["Agent"])
async def get_run(
    run_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_require_user),
):
    res = (await db.execute(select(AgentRun).where(AgentRun.id == run_id))).scalar_one_or_none()
    if not res:
        raise HTTPException(404, "Run not found")
    _ensure_owner(res.user_id, current_user)
    return AgentRunResponse.model_validate(res)


@app.post("/agent/run/{run_id}/stop", tags=["Agent"])
async def stop_run(
    run_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_require_user),
):
    res = (await db.execute(select(AgentRun).where(AgentRun.id == run_id))).scalar_one_or_none()
    if not res:
        raise HTTPException(404, "Run not found")
    _ensure_owner(res.user_id, current_user)
    if res.status == "running":
        ts = datetime.now().strftime("%H:%M:%S")
        res.status = "paused"
        res.log_messages = (res.log_messages or []) + [f"[{ts}] ⏸️ Stopped by user"]
        await db.commit()
    if run_id in _active_runs:
        _active_runs[run_id]["status"] = "paused"
    return {"message": "Run stopped", "run_id": run_id}


@app.get("/agent/run/{run_id}/stream", tags=["Agent"])
async def stream_run(
    run_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_require_user),
):
    """Server-Sent Events — streams live progress to the frontend."""
    res = (await db.execute(select(AgentRun).where(AgentRun.id == run_id))).scalar_one_or_none()
    if not res:
        raise HTTPException(404, "Run not found")
    _ensure_owner(res.user_id, current_user)

    async def generator():
        last = 0
        for _ in range(3600):          # max 1 hour
            state = _active_runs.get(run_id)
            if not state:
                yield f"data: {json.dumps({'status':'not_found'})}\n\n"
                break
            logs = state.get("log_messages", [])
            payload = {
                "status":       state.get("status", "unknown"),
                "progress_pct": round(state.get("progress_pct", 0), 1),
                "current_step": state.get("current_step", ""),
                "new_logs":     logs[last:],
                "total_applied":state.get("total_applied", 0),
                "total_failed": state.get("total_failed", 0),
                "total_skipped":state.get("total_skipped", 0),
                "total_found":  state.get("total_found", 0),
            }
            last = len(logs)
            yield f"data: {json.dumps(payload)}\n\n"
            if state.get("status") in ("completed", "failed", "paused"):
                break
            await asyncio.sleep(1)

    return StreamingResponse(generator(), media_type="text/event-stream")


# ══════════════════════════════════════════════════════════════════════════════
# APPLICATIONS
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/applications/{user_id}", response_model=List[JobApplicationResponse], tags=["Applications"])
async def list_applications(
    user_id: str,
    status:      Optional[str] = Query(None),
    source_site: Optional[str] = Query(None),
    limit:       int           = Query(100, le=500),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_require_user),
):
    _ensure_owner(user_id, current_user)
    q = select(JobApplication).where(JobApplication.user_id == user_id)
    if status:      q = q.where(JobApplication.status == status)
    if source_site: q = q.where(JobApplication.source_site == source_site)
    q = q.order_by(desc(JobApplication.created_at)).limit(limit)
    res = await db.execute(q)
    return [JobApplicationResponse.model_validate(a) for a in res.scalars().all()]


@app.get("/applications/{user_id}/{app_id}", response_model=JobApplicationResponse, tags=["Applications"])
async def get_application(
    user_id: str,
    app_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_require_user),
):
    _ensure_owner(user_id, current_user)
    res = (await db.execute(
        select(JobApplication).where(JobApplication.id == app_id, JobApplication.user_id == user_id)
    )).scalar_one_or_none()
    if not res:
        raise HTTPException(404, "Application not found")
    return JobApplicationResponse.model_validate(res)


@app.delete("/applications/{user_id}/{app_id}", tags=["Applications"])
async def delete_application(
    user_id: str,
    app_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_require_user),
):
    _ensure_owner(user_id, current_user)
    res = (await db.execute(
        select(JobApplication).where(JobApplication.id == app_id, JobApplication.user_id == user_id)
    )).scalar_one_or_none()
    if not res:
        raise HTTPException(404, "Application not found")
    await db.delete(res)
    await db.commit()
    return {"deleted": app_id}


# ══════════════════════════════════════════════════════════════════════════════
# AI TOOLS
# ══════════════════════════════════════════════════════════════════════════════

@app.post("/ai/resume/{user_id}", tags=["AI Tools"])
async def gen_resume(
    user_id: str,
    body: ResumeGenerateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_require_user),
):
    _ensure_owner(user_id, current_user)
    profile = await _profile_dict(user_id, db)
    content = await generate_resume(
        profile=profile,
        job_title=body.job_title or "",
        job_description=body.job_description or "",
        company_name=body.company_name or "",
    )
    doc = GeneratedDocument(
        id=str(uuid.uuid4()), user_id=user_id, doc_type="resume",
        job_title=body.job_title, company_name=body.company_name, content=content,
    )
    db.add(doc); await db.commit()
    return {"content": content, "doc_id": doc.id}


@app.post("/ai/cover-letter/{user_id}", tags=["AI Tools"])
async def gen_cover_letter(
    user_id: str,
    body: CoverLetterRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_require_user),
):
    _ensure_owner(user_id, current_user)
    profile = await _profile_dict(user_id, db)
    content = await generate_cover_letter(
        profile=profile,
        job_title=body.job_title,
        company_name=body.company_name,
        job_description=body.job_description,
        hiring_manager=body.hiring_manager or "Hiring Manager",
    )
    doc = GeneratedDocument(
        id=str(uuid.uuid4()), user_id=user_id, doc_type="cover_letter",
        job_title=body.job_title, company_name=body.company_name, content=content,
    )
    db.add(doc); await db.commit()
    return {"content": content, "doc_id": doc.id}


@app.post("/ai/score-job/{user_id}", tags=["AI Tools"])
async def score_job(
    user_id: str,
    job_title: str, company_name: str, job_description: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_require_user),
):
    _ensure_owner(user_id, current_user)
    profile = await _profile_dict(user_id, db)
    return await score_job_match(profile, job_title, job_description, company_name)


@app.post("/ai/interview-tips/{user_id}", tags=["AI Tools"])
async def interview_tips(
    user_id: str,
    job_title: str, company_name: str,
    job_description: str = "",
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_require_user),
):
    _ensure_owner(user_id, current_user)
    profile = await _profile_dict(user_id, db)
    return await generate_interview_tips(profile, job_title, company_name, job_description)


@app.post("/ai/pdf/resume", tags=["AI Tools — PDF"])
async def pdf_resume(
    user_id: str,
    body: ResumeGenerateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_require_user),
):
    """Generate resume and return as downloadable PDF."""
    _ensure_owner(user_id, current_user)
    profile = await _profile_dict(user_id, db)
    content = await generate_resume(
        profile=profile,
        job_title=body.job_title or "",
        job_description=body.job_description or "",
        company_name=body.company_name or "",
    )
    pdf = resume_text_to_pdf_bytes(content, name=profile.get("full_name","Candidate"))
    fname = f"resume_{(profile.get('full_name','candidate') or 'candidate').replace(' ','_')}.pdf"
    return Response(content=pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{fname}"'})


@app.post("/ai/pdf/cover-letter", tags=["AI Tools — PDF"])
async def pdf_cover_letter(
    user_id: str,
    body: CoverLetterRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_require_user),
):
    """Generate cover letter and return as downloadable PDF."""
    _ensure_owner(user_id, current_user)
    profile = await _profile_dict(user_id, db)
    content = await generate_cover_letter(
        profile=profile,
        job_title=body.job_title,
        company_name=body.company_name,
        job_description=body.job_description,
        hiring_manager=body.hiring_manager or "Hiring Manager",
    )
    pdf = cover_letter_to_pdf_bytes(
        content, name=profile.get("full_name",""),
        company=body.company_name, job_title=body.job_title,
    )
    fname = f"cover_letter_{body.company_name.replace(' ','_')}.pdf"
    return Response(content=pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{fname}"'})


# ══════════════════════════════════════════════════════════════════════════════
# DASHBOARD
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/dashboard/{user_id}", response_model=DashboardStats, tags=["Dashboard"])
async def dashboard(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_require_user),
):
    _ensure_owner(user_id, current_user)
    apps = (await db.execute(
        select(JobApplication).where(JobApplication.user_id == user_id)
    )).scalars().all()
    runs = (await db.execute(
        select(AgentRun).where(AgentRun.user_id == user_id)
    )).scalars().all()

    applied  = [a for a in apps if a.status == "applied"]
    company_counts = Counter(a.company_name for a in applied if a.company_name)
    scores   = [a.match_score for a in apps if a.match_score is not None]
    trend: Dict[str, int] = defaultdict(int)
    for a in applied:
        if a.applied_at:
            trend[a.applied_at.strftime("%Y-%m-%d")] += 1

    return DashboardStats(
        total_applications=len(apps),
        applied_count=len(applied),
        pending_count=sum(1 for a in apps if a.status == "pending"),
        failed_count=sum(1 for a in apps if a.status == "failed"),
        skipped_count=sum(1 for a in apps if a.status == "skipped"),
        active_runs=sum(1 for r in runs if r.status == "running"),
        completed_runs=sum(1 for r in runs if r.status == "completed"),
        top_companies=[{"company": c, "count": n} for c, n in company_counts.most_common(5)],
        application_trend=[{"date": d, "count": c} for d, c in sorted(trend.items())[-14:]],
        match_score_avg=round(sum(scores)/len(scores), 1) if scores else 0.0,
    )


# ══════════════════════════════════════════════════════════════════════════════
# SYSTEM
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/health", tags=["System"])
async def health():
    return {
        "status":           "ok",
        "version":          "1.0.0",
        "llm_provider":     "Groq (free)",
        "groq_configured":  bool(os.getenv("GROQ_API_KEY")),
        "timestamp":        datetime.utcnow().isoformat(),
    }


# ══════════════════════════════════════════════════════════════════════════════
# BACKGROUND AGENT TASK
# ══════════════════════════════════════════════════════════════════════════════

async def _run_agent_bg(run_id: str, user_id: str, config: AgentRunCreate):
    from backend.agents.job_agent import JobApplicationAgent

    _active_runs[run_id] = {
        "status": "running", "progress_pct": 0.0,
        "current_step": "starting", "log_messages": [],
        "total_applied": 0, "total_failed": 0, "total_skipped": 0, "total_found": 0,
    }

    async with AsyncSessionLocal() as db:
        res = (await db.execute(select(AgentRun).where(AgentRun.id == run_id))).scalar_one_or_none()
        if res:
            res.status = "running"; res.started_at = datetime.utcnow()
            await db.commit()
        profile = await _profile_dict(user_id, db)

    # ── callback ──────────────────────────────────────────────────────────────
    async def on_update(rid: str, _node: str, out: Dict[str, Any]):
        state = _active_runs.get(rid, {})
        for key in ("status", "progress_pct", "current_step"):
            if key in out:
                state[key] = out[key]
        state["log_messages"] = state.get("log_messages", []) + out.get("log_messages", [])
        _active_runs[rid] = state

        async with AsyncSessionLocal() as db2:
            r2 = (await db2.execute(select(AgentRun).where(AgentRun.id == rid))).scalar_one_or_none()
            if r2:
                r2.progress_pct  = state.get("progress_pct", 0)
                r2.current_step  = state.get("current_step", "")
                r2.status        = state.get("status", "running")
                r2.log_messages  = state.get("log_messages", [])
                await db2.commit()

            for app_data in out.get("applications", []):
                exists = (await db2.execute(
                    select(JobApplication).where(JobApplication.id == app_data["id"])
                )).scalar_one_or_none()
                if exists:
                    continue
                db2.add(JobApplication(
                    id=app_data["id"], user_id=user_id, agent_run_id=rid,
                    job_title=app_data.get("job_title",""),
                    company_name=app_data.get("company_name",""),
                    job_url=app_data.get("job_url",""),
                    job_description=app_data.get("job_description","")[:4000],
                    job_location=app_data.get("job_location",""),
                    salary_range=app_data.get("salary_range",""),
                    job_type=app_data.get("job_type","full-time"),
                    source_site=app_data.get("source_site",""),
                    status=app_data.get("status","pending"),
                    applied_at=(
                        datetime.fromisoformat(app_data["applied_at"])
                        if app_data.get("applied_at") else None
                    ),
                    match_score=app_data.get("match_score"),
                    cover_letter=app_data.get("cover_letter",""),
                    ai_notes=app_data.get("ai_notes",""),
                    error_message=app_data.get("error_message",""),
                ))
                await db2.commit()
                if app_data.get("status") == "applied":
                    state["total_applied"] = state.get("total_applied", 0) + 1
                elif app_data.get("status") == "failed":
                    state["total_failed"]  = state.get("total_failed",  0) + 1
                elif app_data.get("status") == "skipped":
                    state["total_skipped"] = state.get("total_skipped", 0) + 1
                state["total_found"] = state.get("total_found", 0) + 1
                _active_runs[rid] = state

    # ── run ───────────────────────────────────────────────────────────────────
    try:
        await JobApplicationAgent().run(
            run_id=run_id, user_id=user_id, profile=profile,
            job_titles=config.job_titles, locations=config.locations,
            sites=config.sites, max_applications=config.max_applications,
            min_match_score=config.min_match_score, on_update=on_update,
        )
    except Exception as exc:
        ts  = datetime.now().strftime("%H:%M:%S")
        msg = f"[{ts}] ❌ Agent error: {exc}"
        if run_id in _active_runs:
            _active_runs[run_id]["status"] = "failed"
            _active_runs[run_id]["log_messages"].append(msg)
        async with AsyncSessionLocal() as db3:
            r3 = (await db3.execute(select(AgentRun).where(AgentRun.id == run_id))).scalar_one_or_none()
            if r3:
                r3.status = "failed"
                r3.log_messages = (r3.log_messages or []) + [msg]
                await db3.commit()
        return

    # ── finalise ──────────────────────────────────────────────────────────────
    async with AsyncSessionLocal() as db4:
        r4 = (await db4.execute(select(AgentRun).where(AgentRun.id == run_id))).scalar_one_or_none()
        if r4:
            all_apps = (await db4.execute(
                select(JobApplication).where(JobApplication.agent_run_id == run_id)
            )).scalars().all()
            r4.status        = "completed"
            r4.completed_at  = datetime.utcnow()
            r4.progress_pct  = 100.0
            r4.total_applied = sum(1 for a in all_apps if a.status == "applied")
            r4.total_failed  = sum(1 for a in all_apps if a.status == "failed")
            r4.total_skipped = sum(1 for a in all_apps if a.status == "skipped")
            r4.total_found   = len(all_apps)
            await db4.commit()
    if run_id in _active_runs:
        _active_runs[run_id].update({
            "status": "completed",
            "progress_pct": 100.0,
            "total_applied": r4.total_applied if r4 else _active_runs[run_id].get("total_applied", 0),
            "total_failed": r4.total_failed if r4 else _active_runs[run_id].get("total_failed", 0),
            "total_skipped": r4.total_skipped if r4 else _active_runs[run_id].get("total_skipped", 0),
            "total_found": r4.total_found if r4 else _active_runs[run_id].get("total_found", 0),
        })


# ── entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "backend.api.main:app",
        host=os.getenv("BACKEND_HOST", "0.0.0.0"),
        port=int(os.getenv("BACKEND_PORT", "8000")),
        reload=True,
        log_level="info",
    )
