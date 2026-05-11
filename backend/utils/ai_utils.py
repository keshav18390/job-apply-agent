"""
AutoApplier — AI Utilities (Groq LLM — FREE)
Handles:  resume generation · cover letter · job scoring · interview tips
"""
from __future__ import annotations
import json
from typing import Any, Dict, List, Optional

from langchain_groq import ChatGroq
from langchain_core.messages import HumanMessage

from config import cfg


def get_llm(temperature: float = 0.4) -> ChatGroq:
    """Return a configured Groq LLM instance."""
    cfg.reload()
    return ChatGroq(
        model=cfg.groq_model(),
        temperature=temperature,
        groq_api_key=cfg.groq_api_key(),
        max_tokens=4096,
    )


# ─── Resume ───────────────────────────────────────────────────────────────────

async def generate_resume(
    profile: Dict[str, Any],
    job_title: str = "",
    job_description: str = "",
    company_name: str = "",
) -> str:
    """Generate an ATS-optimised resume tailored to a job description."""
    llm = get_llm(temperature=0.3)

    exp_lines = "\n".join(
        f"  • {e.get('title')} at {e.get('company')} "
        f"({e.get('start_date')} – {e.get('end_date', 'Present')})\n"
        f"    {e.get('description', '')}"
        for e in (profile.get("experience") or [])[:6]
    )
    edu_lines = "\n".join(
        f"  • {e.get('degree')} in {e.get('field', '')} — "
        f"{e.get('school')} ({e.get('graduation_year', '')})"
        for e in (profile.get("education") or [])[:4]
    )

    target = (
        f"\nTARGET ROLE: {job_title} at {company_name}"
        f"\nJOB DESCRIPTION EXCERPT:\n{job_description[:700]}"
        if job_title else ""
    )

    prompt = f"""You are an expert resume writer. Create a clean, ATS-optimised resume in plain text.

CANDIDATE:
Name: {profile.get('full_name', 'Candidate')}
Email: {profile.get('email', '')}
Phone: {profile.get('phone', '')}
Location: {profile.get('location', '')}
LinkedIn: {profile.get('linkedin_url', '')}
GitHub: {profile.get('github_url', '')}
Years of Experience: {profile.get('years_experience', 0)}

PROFESSIONAL SUMMARY:
{profile.get('summary', '')}

SKILLS:
{', '.join(profile.get('skills') or [])}

EXPERIENCE:
{exp_lines}

EDUCATION:
{edu_lines}
{target}

Write the resume with these exact section headers (ALL CAPS):
PROFESSIONAL SUMMARY
SKILLS
PROFESSIONAL EXPERIENCE
EDUCATION

Rules:
- Use bullet points starting with strong action verbs
- Quantify achievements where possible (%, $, numbers)
- Match keywords from the job description
- Keep it to one page worth of content
- Plain text only — no markdown symbols except bullet •
Output the resume only, no commentary."""

    try:
        res = await llm.ainvoke([HumanMessage(content=prompt)])
        return res.content.strip()
    except Exception as e:
        return _fallback_resume(profile)


def _fallback_resume(profile: Dict[str, Any]) -> str:
    name     = profile.get("full_name", "Candidate")
    email    = profile.get("email", "")
    phone    = profile.get("phone", "")
    location = profile.get("location", "")
    skills   = ", ".join(profile.get("skills") or [])
    summary  = profile.get("summary", "Experienced professional seeking new opportunities.")
    exp_text = "\n".join(
        f"• {e.get('title')} at {e.get('company')} "
        f"({e.get('start_date')} – {e.get('end_date', 'Present')})\n  {e.get('description', '')}"
        for e in (profile.get("experience") or [])
    )
    edu_text = "\n".join(
        f"• {e.get('degree')} — {e.get('school')}"
        for e in (profile.get("education") or [])
    )
    return f"""{name}
{email} | {phone} | {location}

PROFESSIONAL SUMMARY
{summary}

SKILLS
{skills}

PROFESSIONAL EXPERIENCE
{exp_text}

EDUCATION
{edu_text}
"""


# ─── Cover Letter ─────────────────────────────────────────────────────────────

async def generate_cover_letter(
    profile: Dict[str, Any],
    job_title: str,
    company_name: str,
    job_description: str,
    hiring_manager: str = "Hiring Manager",
) -> str:
    """Generate a compelling, personalised cover letter using Groq."""
    llm = get_llm(temperature=0.6)

    recent_exp = ", ".join(
        f"{e.get('title')} at {e.get('company')}"
        for e in (profile.get("experience") or [])[:3]
    )

    prompt = f"""You are an expert career coach. Write a compelling cover letter.

APPLICANT:
Name: {profile.get('full_name', 'Candidate')}
Skills: {', '.join((profile.get('skills') or [])[:12])}
Years of Experience: {profile.get('years_experience', 0)}
Summary: {profile.get('summary', '')[:300]}
Recent Roles: {recent_exp}

JOB:
Title: {job_title}
Company: {company_name}
Hiring Manager: {hiring_manager}
Description excerpt: {job_description[:700]}

Write exactly 3 paragraphs:
1. Opening: Hook + specific reason for wanting THIS company (not generic)
2. Value: Connect 2–3 specific skills/achievements to the job requirements
3. Closing: Enthusiastic call to action

Constraints:
- Start with "Dear {hiring_manager},"
- Under 250 words total
- No clichés: avoid "I am writing to express", "passion", "I believe I would be a great fit"
- Be specific and confident
- End with: "Sincerely,\\n{profile.get('full_name', 'Candidate')}"

Output only the letter text, nothing else."""

    try:
        res = await llm.ainvoke([HumanMessage(content=prompt)])
        return res.content.strip()
    except Exception:
        return _fallback_cover_letter(profile, job_title, company_name, hiring_manager)


def _fallback_cover_letter(
    profile: Dict[str, Any],
    job_title: str,
    company_name: str,
    hiring_manager: str,
) -> str:
    skills = ", ".join((profile.get("skills") or [])[:4])
    name   = profile.get("full_name", "Candidate")
    years  = profile.get("years_experience", 0)
    return f"""Dear {hiring_manager},

{company_name}'s reputation for innovation drew me immediately to this {job_title} opening. With {years} years of experience and expertise in {skills}, I am confident I can contribute meaningfully to your team.

My background aligns closely with your requirements. I have consistently delivered results through technical excellence and strong collaboration, and I am excited to bring that to {company_name}.

I would welcome the opportunity to discuss how my experience can help drive {company_name}'s goals forward. Thank you for your consideration.

Sincerely,
{name}"""


# ─── Job Scorer ───────────────────────────────────────────────────────────────

async def score_job_match(
    profile: Dict[str, Any],
    job_title: str,
    job_description: str,
    company_name: str,
) -> Dict[str, Any]:
    """Score 0–100 how well a job matches the candidate using Groq."""
    llm = get_llm(temperature=0.1)

    prompt = f"""Rate this job opportunity for this candidate from 0-100. Be precise and strict.

CANDIDATE:
Skills: {', '.join(profile.get('skills') or [])}
Years Experience: {profile.get('years_experience', 0)}
Desired Roles: {', '.join(profile.get('job_titles') or [])}
Preferred Locations: {', '.join(profile.get('preferred_locations') or [])}

JOB:
Title: {job_title}
Company: {company_name}
Description: {job_description[:800]}

Respond with valid JSON only (no markdown):
{{
  "score": 85,
  "reason": "Strong Python match, remote-friendly, aligns with seniority level",
  "matched_skills": ["Python", "FastAPI"],
  "missing_skills": ["Kubernetes"],
  "recommendation": "apply"
}}
recommendation must be "apply" if score >= 60, else "skip"."""

    try:
        res = await llm.ainvoke([HumanMessage(content=prompt)])
        text = res.content.strip()
        # strip any markdown fences
        if "```" in text:
            text = text.split("```")[1].lstrip("json").strip()
        return json.loads(text)
    except Exception:
        return {
            "score": 65,
            "reason": "Unable to compute detailed score",
            "matched_skills": [],
            "missing_skills": [],
            "recommendation": "apply",
        }


# ─── Interview Tips ───────────────────────────────────────────────────────────

async def generate_interview_tips(
    profile: Dict[str, Any],
    job_title: str,
    company_name: str,
    job_description: str = "",
) -> Dict[str, Any]:
    """Generate role-specific interview preparation guide using Groq."""
    llm = get_llm(temperature=0.5)

    prompt = f"""You are an expert interview coach. Generate a structured interview prep guide.

CANDIDATE:
Name: {profile.get('full_name', 'Candidate')}
Skills: {', '.join((profile.get('skills') or [])[:12])}
Years Experience: {profile.get('years_experience', 0)}
Background: {profile.get('summary', '')[:300]}

ROLE: {job_title} at {company_name}
JOB DESC: {job_description[:500]}

Return valid JSON only (no markdown fences):
{{
  "likely_questions": ["Q1","Q2","Q3","Q4","Q5"],
  "behavioral_questions": ["Tell me about a time...","Describe a situation..."],
  "technical_topics": ["Topic1","Topic2","Topic3"],
  "company_research_tips": ["Tip1","Tip2"],
  "questions_to_ask": ["Question1","Question2"],
  "key_talking_points": ["Point based on candidate experience"],
  "salary_tips": ["Tip1","Tip2"]
}}"""

    try:
        res = await llm.ainvoke([HumanMessage(content=prompt)])
        text = res.content.strip()
        if "```" in text:
            text = text.split("```")[1].lstrip("json").strip()
        return json.loads(text)
    except Exception:
        return {
            "likely_questions": [
                f"Why do you want to work at {company_name}?",
                f"Walk me through your experience as a {job_title}.",
                "What is your biggest professional achievement?",
                "How do you handle tight deadlines and competing priorities?",
                "Where do you see yourself in 3-5 years?",
            ],
            "behavioral_questions": [
                "Tell me about a time you had to learn something quickly.",
                "Describe a conflict with a teammate and how you resolved it.",
            ],
            "technical_topics": (profile.get("skills") or [])[:6],
            "company_research_tips": [
                f"Read {company_name}'s latest blog posts and press releases.",
                "Check Glassdoor reviews to understand the culture.",
            ],
            "questions_to_ask": [
                "What does success look like in the first 90 days?",
                "What are the biggest challenges the team faces right now?",
            ],
            "key_talking_points": [
                f"{profile.get('years_experience', 0)} years of hands-on experience",
                f"Proficiency in {', '.join((profile.get('skills') or [])[:3])}",
            ],
            "salary_tips": [
                "Research market rates on Levels.fyi and LinkedIn Salary Insights.",
                "Let the employer make the first offer when possible.",
            ],
        }


# ─── Batch Job Scorer (used by agent) ────────────────────────────────────────

async def batch_score_jobs(
    profile: Dict[str, Any],
    jobs: List[Dict[str, Any]],
    min_score: float = 60.0,
) -> List[Dict[str, Any]]:
    """Score a list of jobs in batches of 5, return qualified jobs sorted by score."""
    llm = get_llm(temperature=0.1)
    scored: List[Dict[str, Any]] = []
    blacklist = {c.lower() for c in (profile.get("blacklisted_companies") or [])}

    chunk_size = 5
    for i in range(0, len(jobs), chunk_size):
        chunk = jobs[i : i + chunk_size]
        jobs_text = "\n\n".join(
            f"JOB {j+1}:\nTitle: {job.get('title','')}\n"
            f"Company: {job.get('company','')}\n"
            f"Description: {job.get('description','')[:400]}"
            for j, job in enumerate(chunk)
        )

        prompt = f"""Score each job 0-100 for this candidate. Be strict.

CANDIDATE:
Skills: {', '.join((profile.get('skills') or [])[:15])}
Years Experience: {profile.get('years_experience', 0)}
Desired Roles: {', '.join(profile.get('job_titles') or [])}

JOBS:
{jobs_text}

Return a JSON array only (no markdown):
[{{"job_index":1,"score":85,"reason":"strong match","matched_skills":["Python"]}}]
One object per job, in order."""

        try:
            res = await llm.ainvoke([HumanMessage(content=prompt)])
            text = res.content.strip()
            if "```" in text:
                text = text.split("```")[1].lstrip("json").strip()
            scores = json.loads(text)

            for score_data in scores:
                idx = score_data.get("job_index", 1) - 1
                if 0 <= idx < len(chunk):
                    job = chunk[idx].copy()
                    company_lower = job.get("company", "").lower()
                    if any(bl in company_lower for bl in blacklist):
                        job["match_score"]  = 0
                        job["skip_reason"]  = "blacklisted company"
                    else:
                        job["match_score"]      = score_data.get("score", 50)
                        job["score_reason"]     = score_data.get("reason", "")
                        job["matched_skills"]   = score_data.get("matched_skills", [])
                    scored.append(job)

        except Exception:
            for job in chunk:
                job["match_score"] = 50.0
                scored.append(job)

    # sort & filter
    scored.sort(key=lambda x: x.get("match_score", 0), reverse=True)
    return [j for j in scored if j.get("match_score", 0) >= min_score]
