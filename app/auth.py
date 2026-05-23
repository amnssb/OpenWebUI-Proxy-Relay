import secrets
import time
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models import Account, ApiKey, User


# ---- Password hashing ----

def hash_password(password: str) -> str:
    return bcrypt.hashpw(
        password.encode("utf-8"),
        bcrypt.gensalt(rounds=settings.bcrypt_rounds),
    ).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))


# ---- JWT (reserved for future programmatic admin API) ----

def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    payload = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(hours=settings.jwt_expire_hours))
    payload.update({"exp": expire, "iat": datetime.now(timezone.utc)})
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict:
    return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])


# ---- CSRF ----

def get_csrf_token(request: Request) -> str:
    token = request.session.get("csrf_token")
    if not token:
        token = secrets.token_hex(32)
        request.session["csrf_token"] = token
    return token


def validate_csrf(request: Request, form_data: dict) -> None:
    session_token = request.session.get("csrf_token")
    form_token = form_data.get("csrf_token")
    if not session_token or not form_token or session_token != form_token:
        raise HTTPException(status_code=403, detail="CSRF token mismatch")


# ---- Login rate limiting ----

_login_attempts: dict[str, list[float]] = {}


def check_rate_limit(ip: str, max_attempts: int = 5, window: float = 300.0) -> None:
    now = time.time()
    attempts = _login_attempts.get(ip, [])
    attempts = [t for t in attempts if now - t < window]
    _login_attempts[ip] = attempts
    if len(attempts) >= max_attempts:
        raise HTTPException(status_code=429, detail="Too many login attempts. Try again later.")


def record_failure(ip: str) -> None:
    _login_attempts.setdefault(ip, []).append(time.time())


def clear_failures(ip: str) -> None:
    _login_attempts.pop(ip, None)


# ---- FastAPI dependencies ----

async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> User:
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=303, headers={"Location": "/auth/login"})
    result = await db.execute(select(User).where(User.id == user_id, User.is_active == True))
    user = result.scalar_one_or_none()
    if not user:
        request.session.clear()
        raise HTTPException(status_code=303, headers={"Location": "/auth/login"})
    return user


async def require_admin(
    user: User = Depends(get_current_user),
) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


async def get_account_from_api_key(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Account:
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")

    token = auth_header[7:].strip()
    if not token.startswith("sk-proxy-"):
        raise HTTPException(status_code=401, detail="Invalid API key format")

    result = await db.execute(
        select(ApiKey).where(ApiKey.key == token, ApiKey.is_active == True)
    )
    api_key = result.scalar_one_or_none()
    if not api_key:
        raise HTTPException(status_code=401, detail="Invalid or inactive API key")

    result = await db.execute(
        select(Account).where(Account.id == api_key.account_id)
    )
    account = result.scalar_one_or_none()
    if not account or not account.is_enabled:
        raise HTTPException(status_code=403, detail="Account not found or disabled")

    return account
