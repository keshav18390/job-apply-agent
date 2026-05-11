"""
AutoApplier — Auth Utilities (JWT + password hashing)
"""
from __future__ import annotations
from datetime import datetime, timedelta
from typing import Optional

from jose import JWTError, jwt
from passlib.exc import UnknownHashError
from passlib.context import CryptContext

from config import cfg

pwd_context = CryptContext(
    schemes=["pbkdf2_sha256", "bcrypt"],
    deprecated="auto",
)


def hash_password(plain: str) -> str:
    return pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return pwd_context.verify(plain, hashed)
    except (UnknownHashError, TypeError, ValueError):
        return False


def password_needs_refresh(hashed: str) -> bool:
    try:
        return pwd_context.needs_update(hashed)
    except (UnknownHashError, TypeError, ValueError):
        return False


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    cfg.reload()
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=cfg.token_expire_minutes()))
    to_encode["exp"] = expire
    return jwt.encode(to_encode, cfg.secret_key(), algorithm=cfg.algorithm())


def decode_token(token: str) -> Optional[dict]:
    cfg.reload()
    try:
        return jwt.decode(token, cfg.secret_key(), algorithms=[cfg.algorithm()])
    except JWTError:
        return None
