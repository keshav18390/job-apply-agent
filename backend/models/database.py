"""
AutoApplier — Database Models (SQLAlchemy async + SQLite)
"""
from __future__ import annotations
import os
from datetime import datetime
from dotenv import load_dotenv
from sqlalchemy import (
    Boolean, Column, DateTime, Float, ForeignKey,
    Integer, String, Text,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, relationship
from sqlalchemy.types import JSON

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./data/autoapplier.db")

engine = create_async_engine(DATABASE_URL, echo=False, future=True)
AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


# ── Users ─────────────────────────────────────────────────────────────────────

class User(Base):
    __tablename__ = "users"

    id               = Column(String, primary_key=True)
    email            = Column(String, unique=True, index=True, nullable=False)
    hashed_password  = Column(String, nullable=False)
    full_name        = Column(String, default="")
    is_active        = Column(Boolean, default=True)
    created_at       = Column(DateTime, default=datetime.utcnow)

    profile      = relationship("UserProfile",    back_populates="user", uselist=False)
    applications = relationship("JobApplication", back_populates="user")
    agent_runs   = relationship("AgentRun",       back_populates="user")


class UserProfile(Base):
    __tablename__ = "user_profiles"

    id                   = Column(String, primary_key=True)
    user_id              = Column(String, ForeignKey("users.id"), unique=True, nullable=False)
    phone                = Column(String, default="")
    location             = Column(String, default="")
    linkedin_url         = Column(String, default="")
    github_url           = Column(String, default="")
    portfolio_url        = Column(String, default="")
    years_experience     = Column(Integer, default=0)
    job_titles           = Column(JSON, default=list)
    skills               = Column(JSON, default=list)
    preferred_locations  = Column(JSON, default=list)
    salary_min           = Column(Integer, nullable=True)
    salary_max           = Column(Integer, nullable=True)
    work_authorization   = Column(String, default="US Citizen")
    summary              = Column(Text, default="")
    experience           = Column(JSON, default=list)
    education            = Column(JSON, default=list)
    resume_text          = Column(Text, default="")
    resume_filename      = Column(String, default="")
    blacklisted_companies= Column(JSON, default=list)
    job_types            = Column(JSON, default=list)
    updated_at           = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", back_populates="profile")


# ── Job Applications ──────────────────────────────────────────────────────────

class JobApplication(Base):
    __tablename__ = "job_applications"

    id               = Column(String, primary_key=True)
    user_id          = Column(String, ForeignKey("users.id"), nullable=False)
    agent_run_id     = Column(String, ForeignKey("agent_runs.id"), nullable=True)
    job_title        = Column(String, default="")
    company_name     = Column(String, default="")
    job_url          = Column(String, default="")
    job_description  = Column(Text,   default="")
    job_location     = Column(String, default="")
    salary_range     = Column(String, default="")
    job_type         = Column(String, default="full-time")
    source_site      = Column(String, default="")
    status           = Column(String, default="pending")   # pending | applied | failed | skipped
    applied_at       = Column(DateTime, nullable=True)
    error_message    = Column(Text, default="")
    match_score      = Column(Float, nullable=True)
    cover_letter     = Column(Text, default="")
    ai_notes         = Column(Text, default="")
    created_at       = Column(DateTime, default=datetime.utcnow)

    user      = relationship("User",     back_populates="applications")
    agent_run = relationship("AgentRun", back_populates="applications")


# ── Agent Runs ────────────────────────────────────────────────────────────────

class AgentRun(Base):
    __tablename__ = "agent_runs"

    id               = Column(String, primary_key=True)
    user_id          = Column(String, ForeignKey("users.id"), nullable=False)
    job_titles       = Column(JSON, default=list)
    locations        = Column(JSON, default=list)
    sites            = Column(JSON, default=list)
    max_applications = Column(Integer, default=20)
    min_match_score  = Column(Float,   default=60.0)
    status           = Column(String,  default="queued")   # queued | running | completed | failed | paused
    current_step     = Column(String,  default="")
    progress_pct     = Column(Float,   default=0.0)
    total_found      = Column(Integer, default=0)
    total_applied    = Column(Integer, default=0)
    total_failed     = Column(Integer, default=0)
    total_skipped    = Column(Integer, default=0)
    started_at       = Column(DateTime, nullable=True)
    completed_at     = Column(DateTime, nullable=True)
    created_at       = Column(DateTime, default=datetime.utcnow)
    log_messages     = Column(JSON, default=list)

    user         = relationship("User",           back_populates="agent_runs")
    applications = relationship("JobApplication", back_populates="agent_run")


# ── Generated Documents ───────────────────────────────────────────────────────

class GeneratedDocument(Base):
    __tablename__ = "generated_documents"

    id           = Column(String, primary_key=True)
    user_id      = Column(String, ForeignKey("users.id"), nullable=False)
    doc_type     = Column(String, default="")   # resume | cover_letter
    job_title    = Column(String, default="")
    company_name = Column(String, default="")
    content      = Column(Text,   default="")
    created_at   = Column(DateTime, default=datetime.utcnow)


# ── DB helpers ────────────────────────────────────────────────────────────────

async def init_db():
    """Create all tables (idempotent)."""
    import os
    os.makedirs("data", exist_ok=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_db():
    """FastAPI dependency — yields an async DB session."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()
