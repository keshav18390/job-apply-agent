"""
AutoApplier — Pydantic v2 Schemas
"""
from __future__ import annotations
from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, EmailStr, Field


# ── Auth ──────────────────────────────────────────────────────────────────────

class UserCreate(BaseModel):
    email:     EmailStr
    password:  str = Field(min_length=8)
    full_name: str = Field(min_length=1)


class UserLogin(BaseModel):
    email:    EmailStr
    password: str


class Token(BaseModel):
    access_token: str
    token_type:   str = "bearer"


class UserResponse(BaseModel):
    id:         str
    email:      str
    full_name:  Optional[str] = ""
    is_active:  bool
    created_at: datetime

    class Config:
        from_attributes = True


# ── Profile ───────────────────────────────────────────────────────────────────

class UserProfileCreate(BaseModel):
    phone:                Optional[str]       = ""
    location:             Optional[str]       = ""
    linkedin_url:         Optional[str]       = ""
    github_url:           Optional[str]       = ""
    portfolio_url:        Optional[str]       = ""
    years_experience:     Optional[int]       = 0
    job_titles:           Optional[List[str]] = Field(default_factory=list)
    skills:               Optional[List[str]] = Field(default_factory=list)
    preferred_locations:  Optional[List[str]] = Field(default_factory=lambda: ["Remote"])
    salary_min:           Optional[int]       = None
    salary_max:           Optional[int]       = None
    work_authorization:   Optional[str]       = "US Citizen"
    summary:              Optional[str]       = ""
    experience:           Optional[List[Dict[str, Any]]] = Field(default_factory=list)
    education:            Optional[List[Dict[str, Any]]] = Field(default_factory=list)
    blacklisted_companies:Optional[List[str]] = Field(default_factory=list)
    job_types:            Optional[List[str]] = Field(default_factory=lambda: ["full-time", "remote"])


class UserProfileResponse(UserProfileCreate):
    id:              str
    user_id:         str
    resume_filename: Optional[str] = ""
    updated_at:      Optional[datetime] = None

    class Config:
        from_attributes = True


# ── Agent Run ─────────────────────────────────────────────────────────────────

class AgentRunCreate(BaseModel):
    job_titles:       List[str]       = Field(min_length=1)
    locations:        List[str]       = Field(default_factory=lambda: ["Remote"])
    sites:            List[str]       = Field(default_factory=lambda: ["linkedin"])
    max_applications: int             = Field(default=20, ge=1, le=200)
    min_match_score:  float           = Field(default=60.0, ge=0, le=100)


class AgentRunResponse(BaseModel):
    id:               str
    user_id:          str
    job_titles:       List[str]
    locations:        List[str]
    sites:            List[str]
    max_applications: int
    min_match_score:  float
    status:           str
    current_step:     Optional[str]   = ""
    progress_pct:     float
    total_found:      int
    total_applied:    int
    total_failed:     int
    total_skipped:    int
    started_at:       Optional[datetime] = None
    completed_at:     Optional[datetime] = None
    created_at:       datetime
    log_messages:     List[str]       = Field(default_factory=list)

    class Config:
        from_attributes = True


# ── Job Application ───────────────────────────────────────────────────────────

class JobApplicationResponse(BaseModel):
    id:              str
    job_title:       Optional[str]   = ""
    company_name:    Optional[str]   = ""
    job_url:         Optional[str]   = ""
    job_location:    Optional[str]   = ""
    salary_range:    Optional[str]   = ""
    job_type:        Optional[str]   = ""
    source_site:     Optional[str]   = ""
    status:          str
    applied_at:      Optional[datetime] = None
    match_score:     Optional[float] = None
    cover_letter:    Optional[str]   = ""
    ai_notes:        Optional[str]   = ""
    error_message:   Optional[str]   = ""
    created_at:      datetime

    class Config:
        from_attributes = True


# ── AI Tools ──────────────────────────────────────────────────────────────────

class ResumeGenerateRequest(BaseModel):
    job_title:       Optional[str] = ""
    job_description: Optional[str] = ""
    company_name:    Optional[str] = ""


class CoverLetterRequest(BaseModel):
    job_title:       str
    company_name:    str
    job_description: str
    hiring_manager:  Optional[str] = "Hiring Manager"


class DocumentResponse(BaseModel):
    id:           str
    doc_type:     str
    content:      str
    job_title:    Optional[str] = ""
    company_name: Optional[str] = ""
    created_at:   datetime

    class Config:
        from_attributes = True


# ── Dashboard ─────────────────────────────────────────────────────────────────

class DashboardStats(BaseModel):
    total_applications: int
    applied_count:      int
    pending_count:      int
    failed_count:       int
    skipped_count:      int
    active_runs:        int
    completed_runs:     int
    top_companies:      List[Dict[str, Any]]
    application_trend:  List[Dict[str, Any]]
    match_score_avg:    float
