"""
AutoApplier — Streamlit Frontend (bug-fixed)
Pages: Dashboard · AI Agent · Applications · Profile · AI Resume · Cover Letter · Interview Tips
"""
from __future__ import annotations
import base64, json, os, time
from datetime import datetime
from typing import Any, Dict, List, Optional

import requests
import streamlit as st

API = os.getenv("BACKEND_URL", "http://localhost:8000")

st.set_page_config(page_title="AutoApplier — AI Job Agent", page_icon="🎯",
                   layout="wide", initial_sidebar_state="expanded")

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Syne:wght@400;600;700;800&family=DM+Sans:wght@300;400;500&display=swap');
html,body,[class*="css"]{font-family:'DM Sans',sans-serif;}
.logo{font-family:'Syne',sans-serif;font-size:1.6rem;font-weight:800;
  background:linear-gradient(135deg,#6366f1,#a855f7,#ec4899);
  -webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;}
.page-title{font-family:'Syne',sans-serif;font-size:2.4rem;font-weight:800;
  background:linear-gradient(135deg,#6366f1 0%,#a855f7 50%,#ec4899 100%);
  -webkit-background-clip:text;-webkit-text-fill-color:transparent;
  background-clip:text;line-height:1.1;margin-bottom:0;}
.page-sub{color:#64748b;font-size:1rem;margin-top:.25rem;margin-bottom:1.5rem;}
.metric-card{background:linear-gradient(135deg,#1e1b4b,#312e81);
  border:1px solid rgba(99,102,241,.3);border-radius:16px;padding:1.4rem;
  text-align:center;box-shadow:0 4px 20px rgba(99,102,241,.12);}
.metric-icon{font-size:1.6rem;}
.metric-value{font-family:'Syne',sans-serif;font-size:2.2rem;font-weight:800;color:#a5b4fc;}
.metric-label{font-size:.78rem;color:#94a3b8;text-transform:uppercase;letter-spacing:.08em;margin-top:.2rem;}
.section-title{font-family:'Syne',sans-serif;font-size:1.1rem;font-weight:700;color:#e2e8f0;
  border-bottom:2px solid rgba(99,102,241,.3);padding-bottom:.4rem;margin-bottom:1rem;}
.log-box{background:#020617;border:1px solid #1e293b;border-radius:10px;
  padding:.8rem 1rem;height:280px;overflow-y:auto;
  font-family:'JetBrains Mono',monospace;font-size:.78rem;color:#94a3b8;}
.log-ok{color:#4ade80;}.log-err{color:#f87171;}.log-warn{color:#fbbf24;}.log-info{color:#60a5fa;}
.progress-bar{background:linear-gradient(90deg,#4f46e5,#7c3aed,#ec4899,#4f46e5);
  background-size:200% 100%;animation:slide 2s linear infinite;border-radius:4px;height:4px;margin:.6rem 0;}
@keyframes slide{0%{background-position:0% 50%}100%{background-position:200% 50%}}
.tip-card{background:#0f172a;border:1px solid rgba(168,85,247,.25);
  border-radius:10px;padding:.9rem 1.1rem;margin-bottom:.5rem;}
div[data-testid="stSidebarContent"]{background:#070b14;}
.stButton>button{border-radius:8px !important;font-weight:500 !important;transition:all .15s !important;}
.stButton>button:hover{transform:translateY(-1px) !important;box-shadow:0 4px 14px rgba(99,102,241,.35) !important;}
</style>
""", unsafe_allow_html=True)

# ── Session defaults ──────────────────────────────────────────────────────────
_DEFAULTS: Dict[str, Any] = {
    "token": None, "user_id": None, "user_name": "",
    "page": "Dashboard", "active_run_id": None,
    # resume
    "resume_job_title": "", "resume_company": "", "resume_job_desc": "", "gen_resume": "",
    # cover letter
    "cl_job_title": "", "cl_company": "", "cl_hm": "", "cl_job_desc": "", "gen_cl": "",
    # interview
    "interview_tips": None, "interview_meta": {},
}
for _k, _v in _DEFAULTS.items():
    if _k not in st.session_state:
        st.session_state[_k] = _v


# ── API client ────────────────────────────────────────────────────────────────
class Client:
    def __init__(self):
        self.hdrs = {"Content-Type": "application/json"}
        if st.session_state.token:
            self.hdrs["Authorization"] = f"Bearer {st.session_state.token}"

    def get(self, path, **kw):
        try: return requests.get(f"{API}{path}", headers=self.hdrs, timeout=15, **kw)
        except: return None

    def post(self, path, data=None, **kw):
        try: return requests.post(f"{API}{path}", json=data, headers=self.hdrs, timeout=30, **kw)
        except: return None

    def put(self, path, data=None, **kw):
        try: return requests.put(f"{API}{path}", json=data, headers=self.hdrs, timeout=15, **kw)
        except: return None

    def delete(self, path, **kw):
        try: return requests.delete(f"{API}{path}", headers=self.hdrs, timeout=10, **kw)
        except: return None


def cli(): return Client()


# ── Helpers ───────────────────────────────────────────────────────────────────
def _fmt_dt(s):
    if not s: return "—"
    try: return datetime.fromisoformat(s.replace("Z","")).strftime("%b %d, %H:%M")
    except: return s


def _decode_uid(token):
    try:
        part = token.split(".")[1]; part += "=" * (-len(part) % 4)
        return json.loads(base64.b64decode(part)).get("sub","")
    except: return ""


def _pdf_btn(label, url, payload, filename):
    """Fetch PDF from backend and render download button."""
    headers = {"Content-Type": "application/json"}
    if st.session_state.token:
        headers["Authorization"] = f"Bearer {st.session_state.token}"
    try:
        r = requests.post(url, json=payload, headers=headers, timeout=30)
        if r and r.status_code == 200:
            st.download_button(label, data=r.content, file_name=filename,
                               mime="application/pdf", use_container_width=True)
        else:
            st.caption("⚠️ PDF generation failed")
    except:
        st.caption("⚠️ PDF unavailable")


# ═════════════════════════════════════════════════════════════════════════════
# AUTH
# ═════════════════════════════════════════════════════════════════════════════
def render_auth():
    _, c2, _ = st.columns([1, 1.4, 1])
    with c2:
        st.markdown('<div class="page-title">🎯 AutoApplier</div>', unsafe_allow_html=True)
        st.markdown('<div class="page-sub">Autonomous AI job agent — powered by Groq (free)</div>',
                    unsafe_allow_html=True)
        st.markdown("<br>", unsafe_allow_html=True)

        tab_in, tab_up = st.tabs(["Sign In", "Create Account"])

        with tab_in:
            with st.form("login"):
                email = st.text_input("Email", placeholder="you@example.com")
                pwd   = st.text_input("Password", type="password")
                if st.form_submit_button("Sign In →", use_container_width=True, type="primary"):
                    r = Client().post("/auth/login", {"email": email, "password": pwd})
                    if r and r.status_code == 200:
                        tok = r.json()["access_token"]
                        st.session_state.token   = tok
                        st.session_state.user_id = _decode_uid(tok)
                        st.rerun()
                    else:
                        msg = r.json().get("detail","Invalid credentials") if r else "Backend unreachable"
                        st.error(msg)

        with tab_up:
            with st.form("register"):
                name  = st.text_input("Full Name", placeholder="Jane Smith")
                email = st.text_input("Email",     placeholder="jane@example.com")
                pwd   = st.text_input("Password (min 8 chars)", type="password")
                if st.form_submit_button("Create Account →", use_container_width=True, type="primary"):
                    if len(pwd) < 8:
                        st.error("Password must be ≥ 8 characters")
                    else:
                        r = Client().post("/auth/register",
                                          {"email": email, "password": pwd, "full_name": name})
                        if r and r.status_code == 200:
                            tok = r.json()["access_token"]
                            st.session_state.token     = tok
                            st.session_state.user_id   = _decode_uid(tok)
                            st.session_state.user_name = name
                            st.rerun()
                        else:
                            err = r.json().get("detail","Registration failed") if r else "Backend unreachable"
                            st.error(err)


# ═════════════════════════════════════════════════════════════════════════════
# SIDEBAR
# ═════════════════════════════════════════════════════════════════════════════
def render_sidebar():
    with st.sidebar:
        st.markdown('<div class="logo">🎯 AutoApplier</div>', unsafe_allow_html=True)
        st.caption("Powered by Groq LLM · Free")
        st.markdown("---")

        nav = {
            "📊 Dashboard":      "Dashboard",
            "🤖 AI Job Agent":   "Agent",
            "📝 Applications":   "Applications",
            "🔧 Profile":        "Profile",
            "✍️ AI Resume":     "Resume",
            "📄 Cover Letter":   "CoverLetter",
            "🎤 Interview Tips": "Interview",
        }
        for label, key in nav.items():
            if st.button(label, use_container_width=True,
                          type="primary" if st.session_state.page==key else "secondary",
                          key=f"nav_{key}"):
                st.session_state.page = key; st.rerun()

        st.markdown("---")
        if st.session_state.active_run_id:
            r = cli().get(f"/agent/run/{st.session_state.active_run_id}")
            if r and r.status_code == 200:
                run = r.json()
                if run["status"] == "running":
                    st.markdown('<div class="progress-bar"></div>', unsafe_allow_html=True)
                    st.caption(f"🤖 Running: {run['progress_pct']:.0f}%")
                    st.progress(run["progress_pct"] / 100)

        st.markdown("---")
        if st.button("🚪 Sign Out", use_container_width=True):
            for k in list(st.session_state.keys()): del st.session_state[k]
            st.rerun()


# ═════════════════════════════════════════════════════════════════════════════
# DASHBOARD
# ═════════════════════════════════════════════════════════════════════════════
def render_dashboard():
    st.markdown('<div class="page-title">Dashboard</div>', unsafe_allow_html=True)
    st.markdown('<div class="page-sub">Your job search at a glance</div>', unsafe_allow_html=True)

    uid = st.session_state.user_id
    r   = cli().get(f"/dashboard/{uid}")

    if r and r.status_code == 200:
        s = r.json()
        for col, (val, label, icon) in zip(st.columns(4), [
            (s["applied_count"],            "Applied",       "📨"),
            (s["total_applications"],        "Total Tracked", "📋"),
            (f"{s['match_score_avg']:.0f}%", "Avg Match",    "🎯"),
            (s["completed_runs"],            "Agent Runs",   "🤖"),
        ]):
            with col:
                st.markdown(f"""<div class="metric-card">
                  <div class="metric-icon">{icon}</div>
                  <div class="metric-value">{val}</div>
                  <div class="metric-label">{label}</div></div>""", unsafe_allow_html=True)

        st.markdown("<br>", unsafe_allow_html=True)
        cl, cr = st.columns([2, 1])
        with cl:
            st.markdown('<div class="section-title">📈 Application Trend</div>', unsafe_allow_html=True)
            if s.get("application_trend"):
                import pandas as pd
                df = pd.DataFrame(s["application_trend"])
                if not df.empty:
                    st.line_chart(df.set_index("date")["count"], height=200, color="#6366f1")
            else:
                st.info("No applications yet — launch the AI Agent!")
        with cr:
            st.markdown('<div class="section-title">🏢 Top Companies</div>', unsafe_allow_html=True)
            for co in s.get("top_companies", []):
                st.markdown(f"**{co['company']}** — {co['count']} apps")
            if not s.get("top_companies"): st.info("No data yet")
    else:
        st.info("🚀 Welcome! Set up your profile, then launch the AI Agent.")

    st.markdown('<div class="section-title">🔄 Recent Agent Runs</div>', unsafe_allow_html=True)
    rr = cli().get(f"/agent/runs/{uid}")
    if rr and rr.status_code == 200:
        runs = rr.json()
        if not runs: st.info("No runs yet — head to **AI Job Agent**.")
        for run in runs[:5]:
            icon = {"completed":"🟢","running":"🔵","failed":"🔴","queued":"🟡","paused":"⚪"}.get(run["status"],"⚪")
            with st.expander(f"{icon} {', '.join(run['job_titles'][:2])} | {run['status']} | {_fmt_dt(run.get('started_at'))}"):
                ca, cb, cc = st.columns(3)
                ca.metric("Applied",  run["total_applied"])
                cb.metric("Failed",   run["total_failed"])
                cc.metric("Progress", f"{run['progress_pct']:.0f}%")
                if run["status"] == "running": st.progress(run["progress_pct"] / 100)
                if run.get("log_messages"): st.caption("Last: " + run["log_messages"][-1])


# ═════════════════════════════════════════════════════════════════════════════
# AGENT
# ═════════════════════════════════════════════════════════════════════════════
def render_agent():
    st.markdown('<div class="page-title">🤖 AI Job Agent</div>', unsafe_allow_html=True)
    st.markdown('<div class="page-sub">Configure and launch your autonomous application agent</div>',
                unsafe_allow_html=True)

    uid = st.session_state.user_id
    active_run = None
    if st.session_state.active_run_id:
        r = cli().get(f"/agent/run/{st.session_state.active_run_id}")
        if r and r.status_code == 200: active_run = r.json()

    ccfg, cstat = st.columns([1.1, 1])

    with ccfg:
        st.markdown('<div class="section-title">⚙️ Configuration</div>', unsafe_allow_html=True)
        with st.form("agent_form"):
            titles_txt = st.text_area("Job Titles (one per line) *",
                value="Software Engineer\nBackend Developer\nPython Developer", height=100)
            locs_txt = st.text_area("Locations (one per line)",
                value="Remote\nSan Francisco, CA", height=70)
            ca, cb = st.columns(2)
            with ca:
                max_apps  = st.slider("Max Applications", 1, 100, 1, 1)
                min_score = st.slider("Min Match Score %", 0, 100, 60, 5)
            with cb:
                sites = st.multiselect("Job Sites",
                    ["linkedin"],
                    default=["linkedin"])
            running_now = bool(active_run and active_run.get("status") == "running")
            go = st.form_submit_button("🚀 Launch Agent", use_container_width=True,
                                       type="primary", disabled=running_now)

        if go:
            titles = [t.strip() for t in titles_txt.strip().splitlines() if t.strip()]
            locs   = [l.strip() for l in locs_txt.strip().splitlines()   if l.strip()]
            if not titles: st.error("Enter at least one job title")
            elif not sites: st.error("Select at least one job site")
            else:
                r = cli().post(f"/agent/run?user_id={uid}", {
                    "job_titles": titles, "locations": locs, "sites": sites,
                    "max_applications": max_apps, "min_match_score": float(min_score),
                })
                if r and r.status_code == 200:
                    st.session_state.active_run_id = r.json()["id"]
                    st.success("✅ Agent launched!"); st.rerun()
                else:
                    st.error(r.json().get("detail","Launch failed") if r else "Backend unreachable")

    with cstat:
        st.markdown('<div class="section-title">📡 Live Status</div>', unsafe_allow_html=True)
        if active_run:
            status   = active_run.get("status","")
            progress = active_run.get("progress_pct", 0)
            step     = active_run.get("current_step","").replace("_"," ").title()
            smap = {"running":"🔵 Running","completed":"🟢 Completed",
                    "failed":"🔴 Failed","queued":"🟡 Queued","paused":"⚪ Paused"}
            st.markdown(f"**Status:** {smap.get(status, status)}")
            st.markdown(f"**Step:** {step or '—'}")
            st.progress(progress / 100)
            ca, cb, cc = st.columns(3)
            ca.metric("Applied", active_run.get("total_applied",0))
            cb.metric("Found",   active_run.get("total_found",  0))
            cc.metric("Failed",  active_run.get("total_failed", 0))

            if status == "running":
                st.markdown('<div class="progress-bar"></div>', unsafe_allow_html=True)
                if st.button("⏸️ Stop Agent", use_container_width=True):
                    cli().post(f"/agent/run/{st.session_state.active_run_id}/stop"); st.rerun()
                time.sleep(3); st.rerun()
            elif status == "completed":
                st.success("🎉 Agent completed!")
                if st.button("🆕 Start New Run", use_container_width=True):
                    st.session_state.active_run_id = None; st.rerun()

            st.markdown('<div class="section-title" style="margin-top:1rem">📋 Logs</div>',
                        unsafe_allow_html=True)
            logs = (active_run.get("log_messages") or [])[-40:]
            html = "".join(
                f'<div class="{"log-ok" if any(c in l for c in ["✅","🎉","📋","✍️"]) else "log-err" if "❌" in l else "log-warn" if "⚠️" in l else "log-info"}">'
                f'{l.replace("<","&lt;").replace(">","&gt;")}</div>'
                for l in logs
            )
            st.markdown(f'<div class="log-box">{html or "<div class=log-info>Waiting…</div>"}</div>',
                        unsafe_allow_html=True)
        else:
            st.info("No active run. Configure and launch the agent →")


# ═════════════════════════════════════════════════════════════════════════════
# APPLICATIONS
# ═════════════════════════════════════════════════════════════════════════════
def render_applications():
    st.markdown('<div class="page-title">📝 Applications</div>', unsafe_allow_html=True)
    st.markdown('<div class="page-sub">Every application the agent has tracked</div>',
                unsafe_allow_html=True)

    uid = st.session_state.user_id
    cf1, cf2, _ = st.columns([1,1,2])
    with cf1: fstatus = st.selectbox("Status", ["All","applied","pending","failed","skipped"])
    with cf2: fsort   = st.selectbox("Sort",   ["Date (newest)","Match Score","Company"])

    params = {}
    if fstatus != "All": params["status"] = fstatus
    r = cli().get(f"/applications/{uid}", params=params)

    if not r or r.status_code != 200:
        st.error("Could not fetch applications. Is the backend running?"); return

    apps: List[Dict] = r.json()
    if fsort == "Match Score": apps.sort(key=lambda x: x.get("match_score") or 0, reverse=True)
    elif fsort == "Company":   apps.sort(key=lambda x: x.get("company_name") or "")

    st.caption(f"{len(apps)} application(s)")
    if not apps:
        st.info("No applications yet. Launch the AI agent to start!"); return

    for app in apps:
        status = app.get("status","pending")
        score  = app.get("match_score") or 0
        with st.expander(f"**{app.get('job_title','N/A')}** — {app.get('company_name','N/A')} | {status.upper()} | {score:.0f}%"):
            cl, cr = st.columns([2,1])
            with cl:
                st.markdown(f"**🏢 Company:** {app.get('company_name','—')}")
                st.markdown(f"**📍 Location:** {app.get('job_location','—')}")
                st.markdown(f"**💰 Salary:** {app.get('salary_range','Not listed')}")
                st.markdown(f"**🌐 Source:** {(app.get('source_site') or '—').title()}")
                if app.get("job_url"): st.markdown(f"[🔗 View Job Posting]({app['job_url']})")
            with cr:
                color = "green" if status=="applied" else "red" if status=="failed" else "orange"
                st.markdown(f"**Status:** :{color}[{status.upper()}]")
                st.markdown(f"**Match:** {score:.0f}%")
                st.markdown(f"**Applied:** {_fmt_dt(app.get('applied_at'))}")
                if app.get("ai_notes"):    st.caption(f"💡 {app['ai_notes']}")
                if app.get("error_message"): st.caption(f"⚠️ {app['error_message']}")
            if app.get("cover_letter"):
                 st.markdown("**📄 Cover Letter:**")
                 st.text_area(
                     "",
                      app["cover_letter"],
                      height=180,
                      disabled=True,
                      key=f"cl_{app['id']}"
                 )
                    
        
            if st.button("🗑️ Delete", key=f"del_{app['id']}"):
                cli().delete(f"/applications/{uid}/{app['id']}"); st.rerun()


# ═════════════════════════════════════════════════════════════════════════════
# PROFILE
# ═════════════════════════════════════════════════════════════════════════════
def render_profile():
    st.markdown('<div class="page-title">🔧 Profile Setup</div>', unsafe_allow_html=True)
    st.markdown('<div class="page-sub">The more detail you add, the better the AI performs</div>',
                unsafe_allow_html=True)

    uid = st.session_state.user_id
    ex: Dict = {}
    r = cli().get(f"/profile/{uid}")
    if r and r.status_code == 200: ex = r.json()

    t1, t2, t3, t4 = st.tabs(["👤 Basic Info","💼 Experience & Skills","🎓 Education","⚙️ Preferences"])

    with t1:
        with st.form("basic"):
            c1, c2 = st.columns(2)
            with c1:
                phone    = st.text_input("Phone",       value=ex.get("phone",""))
                location = st.text_input("Location",    value=ex.get("location",""), placeholder="San Francisco, CA")
                linkedin = st.text_input("LinkedIn URL", value=ex.get("linkedin_url",""))
            with c2:
                github    = st.text_input("GitHub URL",    value=ex.get("github_url",""))
                portfolio = st.text_input("Portfolio URL", value=ex.get("portfolio_url",""))
                yrs       = st.number_input("Years Experience", 0, 40, value=int(ex.get("years_experience") or 0))
            summary = st.text_area("Professional Summary", value=ex.get("summary",""), height=110,
                                   placeholder="Brief background and goals…")
            st.markdown("**📎 Resume PDF** (improves AI matching quality)")
            resume_file = st.file_uploader("Upload PDF", type=["pdf"])
            if st.form_submit_button("💾 Save Basic Info", use_container_width=True, type="primary"):
                r2 = cli().put(f"/profile/{uid}", {
                    "phone": phone, "location": location, "linkedin_url": linkedin,
                    "github_url": github, "portfolio_url": portfolio,
                    "years_experience": yrs, "summary": summary,
                })
                if r2 and r2.status_code == 200:
                    st.success("✅ Saved!")
                else:
                    st.error("Save failed")
        # Upload outside form to avoid button conflict
        if resume_file is not None:
            headers = {}
            if st.session_state.token:
                headers["Authorization"] = f"Bearer {st.session_state.token}"
            up = requests.post(f"{API}/profile/{uid}/resume",
                files={"file": (resume_file.name, resume_file.getvalue(), "application/pdf")},
                headers=headers)
            if up.status_code == 200:
                st.success(f"✅ Resume parsed ({up.json().get('characters_extracted',0)} chars)")
            else:
                st.error("Resume upload failed")

    with t2:
        skills_str = st.text_area("Skills (comma-separated)",
            value=", ".join(ex.get("skills") or []),
            placeholder="Python, FastAPI, PostgreSQL, Docker, React…", height=75)
        st.markdown('<div class="section-title">Work Experience</div>', unsafe_allow_html=True)
        experience: List[Dict] = list(ex.get("experience") or [])

        with st.form("add_exp"):
            c1, c2 = st.columns(2)
            with c1:
                et = st.text_input("Job Title *", placeholder="Software Engineer")
                ec = st.text_input("Company *",   placeholder="Acme Corp")
                el = st.text_input("Location",    placeholder="Remote")
            with c2:
                es = st.text_input("Start Date *", placeholder="Jan 2022")
                ee = st.text_input("End Date",     placeholder="Present")
            ed = st.text_area("Description", placeholder="• Built X…\n• Led team of N…", height=90)
            if st.form_submit_button("➕ Add Experience", type="primary"):
                if et and ec and es:
                    experience.append({"title":et,"company":ec,"location":el,
                                       "start_date":es,"end_date":ee or "Present","description":ed})
                    skills = [s.strip() for s in skills_str.split(",") if s.strip()]
                    cli().put(f"/profile/{uid}", {"skills": skills, "experience": experience})
                    st.success("Added!"); st.rerun()
                else: st.error("Title, Company and Start Date are required")

        for i, exp in enumerate(experience):
            with st.expander(f"**{exp.get('title')}** at {exp.get('company')} ({exp.get('start_date')}–{exp.get('end_date','Present')})"):
                st.write(exp.get("description",""))
                if st.button("🗑️ Remove", key=f"rx_{i}"):
                    experience.pop(i); cli().put(f"/profile/{uid}", {"experience": experience}); st.rerun()

        if st.button("💾 Save Skills & Experience", type="primary"):
            skills = [s.strip() for s in skills_str.split(",") if s.strip()]
            r2 = cli().put(f"/profile/{uid}", {"skills": skills, "experience": experience})
            if r2 and r2.status_code == 200:
                st.success("✅ Saved!")
            else:
                st.error("Failed")

    with t3:
        education: List[Dict] = list(ex.get("education") or [])
        with st.form("add_edu"):
            c1, c2 = st.columns(2)
            with c1:
                ed_deg = st.text_input("Degree", placeholder="B.S. Computer Science")
                ed_sch = st.text_input("School", placeholder="MIT")
            with c2:
                ed_fld = st.text_input("Field",     placeholder="Computer Science")
                ed_yr  = st.text_input("Grad Year", placeholder="2021")
            ed_gpa = st.text_input("GPA (optional)", placeholder="3.8")
            if st.form_submit_button("➕ Add Education", type="primary"):
                if ed_deg and ed_sch:
                    education.append({"degree":ed_deg,"school":ed_sch,"field":ed_fld,
                                      "graduation_year":ed_yr,"gpa":ed_gpa})
                    cli().put(f"/profile/{uid}", {"education": education})
                    st.success("Added!"); st.rerun()
                else: st.error("Degree and School are required")
        for edu in education:
            st.markdown(f"🎓 **{edu.get('degree')}** in {edu.get('field','')} — {edu.get('school')} ({edu.get('graduation_year','')})")

    with t4:
        with st.form("prefs"):
            job_titles_txt = st.text_area("Target Job Titles (one per line)",
                value="\n".join(ex.get("job_titles") or []),
                placeholder="Software Engineer\nBackend Developer")
            pref_locs_txt = st.text_area("Preferred Locations (one per line)",
                value="\n".join(ex.get("preferred_locations") or ["Remote"]),
                placeholder="Remote\nNew York, NY")
            c1, c2 = st.columns(2)
            with c1: sal_min = st.number_input("Min Salary ($)", 0, 1_000_000, value=int(ex.get("salary_min") or 80_000), step=5_000)
            with c2: sal_max = st.number_input("Max Salary ($)", 0, 1_000_000, value=int(ex.get("salary_max") or 200_000), step=5_000)

            auth_opts = ["US Citizen","Green Card","H1B Visa","OPT/CPT","Other"]
            auth_val  = ex.get("work_authorization","US Citizen") or "US Citizen"
            work_auth = st.selectbox("Work Authorization", auth_opts,
                                     index=auth_opts.index(auth_val) if auth_val in auth_opts else 0)
            job_types = st.multiselect("Job Types",
                ["full-time","part-time","contract","remote","hybrid"],
                default=ex.get("job_types") or ["full-time","remote"])
            blacklist_txt = st.text_area("Blacklisted Companies (one per line)",
                value="\n".join(ex.get("blacklisted_companies") or []),
                placeholder="Current Employer\nCompany To Skip")

            if st.form_submit_button("💾 Save Preferences", use_container_width=True, type="primary"):
                r2 = cli().put(f"/profile/{uid}", {
                    "job_titles":            [t.strip() for t in job_titles_txt.splitlines() if t.strip()],
                    "preferred_locations":   [l.strip() for l in pref_locs_txt.splitlines()  if l.strip()],
                    "salary_min": sal_min, "salary_max": sal_max,
                    "work_authorization": work_auth, "job_types": job_types,
                    "blacklisted_companies": [c.strip() for c in blacklist_txt.splitlines() if c.strip()],
                })
                if r2 and r2.status_code == 200:
                    st.success("✅ Saved!")
                else:
                    st.error("Failed")


# ═════════════════════════════════════════════════════════════════════════════
# AI RESUME  (bug-fixed: session_state for cross-rerun persistence)
# ═════════════════════════════════════════════════════════════════════════════
def render_resume():
    st.markdown('<div class="page-title">✍️ AI Resume</div>', unsafe_allow_html=True)
    st.markdown('<div class="page-sub">ATS-optimised resume tailored to any job — Groq powered (free)</div>',
                unsafe_allow_html=True)

    uid = st.session_state.user_id
    cin, cout = st.columns([1, 1.4])

    with cin:
        st.markdown('<div class="section-title">🎯 Target Job (optional)</div>', unsafe_allow_html=True)
        with st.form("resume_form"):
            job_title = st.text_input("Job Title", placeholder="Senior Software Engineer",
                                      value=st.session_state.resume_job_title)
            company   = st.text_input("Company",   placeholder="Stripe",
                                      value=st.session_state.resume_company)
            job_desc  = st.text_area("Job Description (paste for best results)", height=240,
                                     placeholder="Paste full JD here…",
                                     value=st.session_state.resume_job_desc)
            go = st.form_submit_button("✨ Generate Resume", use_container_width=True, type="primary")

        if go:
            st.session_state.resume_job_title = job_title
            st.session_state.resume_company   = company
            st.session_state.resume_job_desc  = job_desc
            with st.spinner("Groq is crafting your resume…"):
                r = cli().post(f"/ai/resume/{uid}", {
                    "job_title": job_title, "job_description": job_desc, "company_name": company,
                })
                if r and r.status_code == 200:
                    st.session_state.gen_resume = r.json().get("content",""); st.success("✅ Resume generated!")
                else:
                    st.error("Generation failed. Check your GROQ_API_KEY in .env")

    with cout:
        st.markdown('<div class="section-title">📄 Generated Resume</div>', unsafe_allow_html=True)
        if st.session_state.gen_resume:
            edited = st.text_area("Edit below:", value=st.session_state.gen_resume,
                                  height=480, key="resume_edit")
            ca, cb = st.columns(2)
            with ca:
                st.download_button("📥 Download .txt", data=edited,
                    file_name="resume.txt", mime="text/plain", use_container_width=True)
            with cb:
                _pdf_btn("📥 Download PDF",
                    f"{API}/ai/pdf/resume?user_id={uid}",
                    {"job_title": st.session_state.resume_job_title,
                     "job_description": st.session_state.resume_job_desc,
                     "company_name":    st.session_state.resume_company},
                    "resume.pdf")
        else:
            st.info("Fill in the target job and click **Generate Resume**.")


# ═════════════════════════════════════════════════════════════════════════════
# COVER LETTER  (bug-fixed: session_state persistence)
# ═════════════════════════════════════════════════════════════════════════════
def render_cover_letter():
    st.markdown('<div class="page-title">📄 Cover Letter</div>', unsafe_allow_html=True)
    st.markdown('<div class="page-sub">Personalised cover letters written by Groq AI — free</div>',
                unsafe_allow_html=True)

    uid = st.session_state.user_id
    cin, cout = st.columns([1, 1.3])

    with cin:
        st.markdown('<div class="section-title">📋 Job Details</div>', unsafe_allow_html=True)
        with st.form("cl_form"):
            job_title = st.text_input("Job Title *",    placeholder="Product Engineer",
                                      value=st.session_state.cl_job_title)
            company   = st.text_input("Company *",      placeholder="Notion",
                                      value=st.session_state.cl_company)
            hm        = st.text_input("Hiring Manager", placeholder="Sarah Johnson",
                                      value=st.session_state.cl_hm)
            job_desc  = st.text_area("Job Description *", height=280,
                                     placeholder="Paste full JD here…",
                                     value=st.session_state.cl_job_desc)
            go = st.form_submit_button("✨ Generate Cover Letter", use_container_width=True, type="primary")

        if go:
            if not job_title or not company or not job_desc:
                st.error("Job Title, Company and Description are required")
            else:
                st.session_state.cl_job_title = job_title
                st.session_state.cl_company   = company
                st.session_state.cl_hm        = hm
                st.session_state.cl_job_desc  = job_desc
                with st.spinner("Groq is writing your cover letter…"):
                    r = cli().post(f"/ai/cover-letter/{uid}", {
                        "job_title": job_title, "company_name": company,
                        "job_description": job_desc, "hiring_manager": hm or "Hiring Manager",
                    })
                    if r and r.status_code == 200:
                        st.session_state.gen_cl = r.json().get("content",""); st.success("✅ Generated!")
                    else:
                        st.error("Generation failed. Check your GROQ_API_KEY in .env")

    with cout:
        st.markdown('<div class="section-title">✉️ Your Cover Letter</div>', unsafe_allow_html=True)
        if st.session_state.gen_cl:
            edited = st.text_area("Edit below:", value=st.session_state.gen_cl,
                                  height=430, key="cl_edit")
            company_safe = (st.session_state.cl_company or "job").replace(" ","_")
            ca, cb = st.columns(2)
            with ca:
                st.download_button("📥 Download .txt", data=edited,
                    file_name=f"cover_letter_{company_safe}.txt",
                    mime="text/plain", use_container_width=True)
            with cb:
                _pdf_btn("📥 Download PDF",
                    f"{API}/ai/pdf/cover-letter?user_id={uid}",
                    {"job_title":       st.session_state.cl_job_title,
                     "company_name":    st.session_state.cl_company,
                     "job_description": st.session_state.cl_job_desc or "N/A",
                     "hiring_manager":  st.session_state.cl_hm or "Hiring Manager"},
                    f"cover_letter_{company_safe}.pdf")
        else:
            st.info("Fill in the job details and click **Generate Cover Letter**.")


# ═════════════════════════════════════════════════════════════════════════════
# INTERVIEW TIPS
# ═════════════════════════════════════════════════════════════════════════════
def render_interview():
    st.markdown('<div class="page-title">🎤 Interview Tips</div>', unsafe_allow_html=True)
    st.markdown('<div class="page-sub">AI-personalised interview prep guide — powered by Groq (free)</div>',
                unsafe_allow_html=True)

    uid = st.session_state.user_id

    with st.form("interview_form"):
        c1, c2 = st.columns(2)
        with c1: job_title = st.text_input("Job Title *", placeholder="Senior Software Engineer")
        with c2: company   = st.text_input("Company *",   placeholder="Stripe")
        job_desc = st.text_area("Job Description (optional but recommended)", height=140,
                                placeholder="Paste the JD for more targeted tips…")
        go = st.form_submit_button("🎯 Generate Interview Guide", use_container_width=True, type="primary")

    if go:
        if not job_title or not company:
            st.error("Job Title and Company are required")
        else:
            with st.spinner("Groq is preparing your interview guide…"):
                r = cli().post(f"/ai/interview-tips/{uid}",
                               params={"job_title": job_title, "company_name": company,
                                       "job_description": job_desc})
                if r and r.status_code == 200:
                    st.session_state.interview_tips = r.json()
                    st.session_state.interview_meta = {"title": job_title, "company": company}
                else:
                    st.error("Generation failed. Check your GROQ_API_KEY in .env")

    tips = st.session_state.interview_tips
    meta = st.session_state.interview_meta
    if not tips:
        st.info("Enter a job title and company, then click Generate."); return

    st.markdown(f"### Interview Guide: **{meta.get('title')}** at **{meta.get('company')}**")
    st.markdown("---")

    t1, t2, t3, t4 = st.tabs(["❓ Questions","💡 Talking Points","🏢 Company Research","💰 Salary Tips"])

    with t1:
        ca, cb = st.columns(2)
        with ca:
            st.markdown("**Role-Specific Questions**")
            for q in tips.get("likely_questions",[]): st.markdown(f'<div class="tip-card">🔹 {q}</div>', unsafe_allow_html=True)
        with cb:
            st.markdown("**Behavioral Questions**")
            for q in tips.get("behavioral_questions",[]): st.markdown(f'<div class="tip-card">🔸 {q}</div>', unsafe_allow_html=True)
        st.markdown("**Technical Topics to Prepare**")
        topics = tips.get("technical_topics",[])
        if topics:
            cols = st.columns(min(len(topics),4))
            for i, t in enumerate(topics): cols[i % len(cols)].markdown(f"🛠️ {t}")
        st.markdown("**Questions to Ask the Interviewer**")
        for q in tips.get("questions_to_ask",[]): st.markdown(f'<div class="tip-card">🙋 {q}</div>', unsafe_allow_html=True)

    with t2:
        for pt in tips.get("key_talking_points",[]): st.markdown(f'<div class="tip-card">⭐ {pt}</div>', unsafe_allow_html=True)

    with t3:
        for tip in tips.get("company_research_tips",[]): st.markdown(f'<div class="tip-card">🔍 {tip}</div>', unsafe_allow_html=True)

    with t4:
        for tip in tips.get("salary_tips",[]): st.markdown(f'<div class="tip-card">💵 {tip}</div>', unsafe_allow_html=True)

    lines = [f"INTERVIEW GUIDE: {meta.get('title')} at {meta.get('company')}", "="*60, "",
             "LIKELY QUESTIONS:", *[f"  • {q}" for q in tips.get("likely_questions",[])], "",
             "BEHAVIORAL QUESTIONS:", *[f"  • {q}" for q in tips.get("behavioral_questions",[])], "",
             "TECHNICAL TOPICS:", *[f"  • {t}" for t in tips.get("technical_topics",[])], "",
             "KEY TALKING POINTS:", *[f"  • {p}" for p in tips.get("key_talking_points",[])], "",
             "QUESTIONS TO ASK:", *[f"  • {q}" for q in tips.get("questions_to_ask",[])], "",
             "COMPANY RESEARCH:", *[f"  • {t}" for t in tips.get("company_research_tips",[])], "",
             "SALARY TIPS:", *[f"  • {t}" for t in tips.get("salary_tips",[])]]
    st.markdown("<br>", unsafe_allow_html=True)
    st.download_button("📥 Download Guide", data="\n".join(lines),
        file_name=f"interview_{(meta.get('company') or 'guide').replace(' ','_')}.txt",
        mime="text/plain")


# ═════════════════════════════════════════════════════════════════════════════
# MAIN ROUTER
# ═════════════════════════════════════════════════════════════════════════════
def main():
    try:
        hc = requests.get(f"{API}/health", timeout=2)
        backend_ok = hc.status_code == 200
    except:
        backend_ok = False

    if not st.session_state.token:
        if not backend_ok:
            st.warning("⚠️ Backend offline. Run: `uvicorn backend.api.main:app --reload`", icon="⚠️")
        render_auth(); return

    render_sidebar()
    page = st.session_state.page
    {"Dashboard":    render_dashboard,
     "Agent":        render_agent,
     "Applications": render_applications,
     "Profile":      render_profile,
     "Resume":       render_resume,
     "CoverLetter":  render_cover_letter,
     "Interview":    render_interview}.get(page, render_dashboard)()


if __name__ == "__main__":
    main()
