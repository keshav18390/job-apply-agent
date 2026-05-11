from __future__ import annotations
import os
from pathlib import Path

def _find_and_load_env():
    from dotenv import load_dotenv
    search = [
        Path(__file__).resolve().parent,
        Path(__file__).resolve().parent.parent,
        Path.cwd(),
    ]
    for d in search:
        env_file = d / ".env"
        if env_file.exists():
            load_dotenv(env_file, override=False)
            return str(env_file)
    load_dotenv(override=False)
    return ".env"

_env_path = _find_and_load_env()

class Config:
    @staticmethod
    def reload():
        _find_and_load_env()

    @staticmethod
    def groq_api_key(): return os.getenv("GROQ_API_KEY", "")

    @staticmethod
    def groq_model(): return os.getenv("GROQ_MODEL", "llama-3.1-70b-versatile")

    @staticmethod
    def linkedin_email(): return os.getenv("LINKEDIN_EMAIL", "").strip()

    @staticmethod
    def linkedin_password(): return os.getenv("LINKEDIN_PASSWORD", "").strip()

    @staticmethod
    def headless(): return os.getenv("PLAYWRIGHT_HEADLESS", "false").strip().lower() == "true"

    @staticmethod
    def slow_mo(): return int(os.getenv("PLAYWRIGHT_SLOW_MO", "80"))

    @staticmethod
    def timeout(): return int(os.getenv("PLAYWRIGHT_TIMEOUT", "45000"))

    @staticmethod
    def linkedin_user_data_dir():
        return os.getenv(
            "LINKEDIN_USER_DATA_DIR",
            str((Path(__file__).resolve().parent / "data" / "linkedin_browser_profile").resolve()),
        )

    @staticmethod
    def secret_key(): return os.getenv("SECRET_KEY", "autoapplier-secret-key")

    @staticmethod
    def algorithm(): return os.getenv("ALGORITHM", "HS256")

    @staticmethod
    def token_expire_minutes(): return int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "10080"))

    @staticmethod
    def database_url(): return os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./data/autoapplier.db")

    @staticmethod
    def apply_delay(): return float(os.getenv("APPLICATION_DELAY_SECONDS", "4"))

    @staticmethod
    def backend_url(): return os.getenv("BACKEND_URL", "http://localhost:8000")

    @staticmethod
    def summary():
        return {
            "env_file":        _env_path,
            "groq_configured": bool(Config.groq_api_key()),
            "linkedin_email":  Config.linkedin_email() or "NOT SET",
            "linkedin_pass":   "SET" if Config.linkedin_password() else "NOT SET",
            "headless":        Config.headless(),
        }

cfg = Config()
