import logging
import secrets
from datetime import datetime

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_csrf_token, hash_password, require_admin, validate_csrf
from app.database import get_db
from app.models import Account, ApiKey, User
from app.schemas import AccountForm, AccountUpdateForm, ApiKeyForm, UserForm, UserUpdateForm

log = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])

BROWSER_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"


def generate_api_key() -> str:
    return f"sk-proxy-{secrets.token_urlsafe(32)}"


# ---- Accounts ----

@router.post("/accounts")
async def create_account(
    request: Request,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    form = await request.form()
    validate_csrf(request, dict(form))
    data = AccountForm(**dict(form))

    if not data.target_url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="target_url must start with http:// or https://")

    account = Account(
        name=data.name,
        target_url=data.target_url.rstrip("/"),
        session_token=data.session_token,
    )
    db.add(account)
    await db.commit()
    return RedirectResponse("/admin/accounts", status_code=303)


@router.post("/accounts/{account_id}/edit")
async def update_account(
    account_id: int,
    request: Request,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    form = await request.form()
    validate_csrf(request, dict(form))

    result = await db.execute(select(Account).where(Account.id == account_id))
    account = result.scalar_one_or_none()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    data = AccountUpdateForm(**{k: v for k, v in dict(form).items() if v is not None and v != ""})
    if data.name is not None:
        account.name = data.name
    if data.target_url is not None:
        account.target_url = data.target_url.rstrip("/")
    if data.session_token is not None:
        account.session_token = data.session_token

    await db.commit()
    return RedirectResponse("/admin/accounts", status_code=303)


@router.post("/accounts/{account_id}/delete")
async def delete_account(
    account_id: int,
    request: Request,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    form = await request.form()
    validate_csrf(request, dict(form))

    result = await db.execute(select(ApiKey).where(ApiKey.account_id == account_id))
    keys = result.scalars().all()
    if keys:
        raise HTTPException(status_code=400, detail="Delete all API keys for this account first")

    result = await db.execute(select(Account).where(Account.id == account_id))
    account = result.scalar_one_or_none()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    await db.delete(account)
    await db.commit()
    return RedirectResponse("/admin/accounts", status_code=303)


@router.post("/accounts/{account_id}/toggle")
async def toggle_account(
    account_id: int,
    request: Request,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    form = await request.form()
    validate_csrf(request, dict(form))

    result = await db.execute(select(Account).where(Account.id == account_id))
    account = result.scalar_one_or_none()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    account.is_enabled = not account.is_enabled
    await db.commit()
    return RedirectResponse("/admin/accounts", status_code=303)


@router.post("/accounts/{account_id}/health")
async def check_health(
    account_id: int,
    request: Request,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    form = await request.form()
    validate_csrf(request, dict(form))

    result = await db.execute(select(Account).where(Account.id == account_id))
    account = result.scalar_one_or_none()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    http_client: httpx.AsyncClient = request.app.state.http_client
    status = "unhealthy"
    try:
        resp = await http_client.get(
            f"{account.target_url}/api/models",
            headers={
                "Authorization": f"Bearer {account.session_token}",
                "User-Agent": BROWSER_UA,
            },
            timeout=10.0,
        )
        if resp.status_code == 200:
            status = "healthy"
    except Exception:
        pass

    account.health_status = status
    account.last_health_check = datetime.utcnow()
    await db.commit()
    return RedirectResponse("/admin/accounts", status_code=303)


# ---- Users ----

@router.post("/users")
async def create_user(
    request: Request,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    form = await request.form()
    validate_csrf(request, dict(form))
    data = UserForm(**dict(form))

    result = await db.execute(select(User).where(User.username == data.username))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Username already exists")

    new_user = User(
        username=data.username,
        password_hash=hash_password(data.password),
        role=data.role,
    )
    db.add(new_user)
    await db.commit()
    return RedirectResponse("/admin/users", status_code=303)


@router.post("/users/{user_id}/edit")
async def update_user(
    user_id: int,
    request: Request,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    form = await request.form()
    validate_csrf(request, dict(form))

    result = await db.execute(select(User).where(User.id == user_id))
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")

    data = UserUpdateForm(**{k: v for k, v in dict(form).items() if v is not None and v != ""})
    if data.password is not None:
        target.password_hash = hash_password(data.password)
    if data.role is not None:
        target.role = data.role

    await db.commit()
    return RedirectResponse("/admin/users", status_code=303)


@router.post("/users/{user_id}/toggle")
async def toggle_user(
    user_id: int,
    request: Request,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    form = await request.form()
    validate_csrf(request, dict(form))

    result = await db.execute(select(User).where(User.id == user_id))
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")

    target.is_active = not target.is_active
    await db.commit()
    return RedirectResponse("/admin/users", status_code=303)


@router.post("/users/{user_id}/delete")
async def delete_user(
    user_id: int,
    request: Request,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    form = await request.form()
    validate_csrf(request, dict(form))

    if user_id == admin.id:
        raise HTTPException(status_code=400, detail="Cannot delete yourself")

    result = await db.execute(select(User).where(User.id == user_id))
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")

    await db.delete(target)
    await db.commit()
    return RedirectResponse("/admin/users", status_code=303)


# ---- API Keys ----

@router.post("/api-keys")
async def create_api_key(
    request: Request,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    form = await request.form()
    validate_csrf(request, dict(form))
    data = ApiKeyForm(**dict(form))

    result = await db.execute(select(Account).where(Account.id == data.account_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Account not found")

    new_key = ApiKey(
        key=generate_api_key(),
        name=data.name,
        account_id=data.account_id,
    )
    db.add(new_key)
    await db.commit()
    await db.refresh(new_key)

    # Store the new key value in session so it can be shown once
    request.session["new_api_key"] = new_key.key
    return RedirectResponse("/admin/api-keys", status_code=303)


@router.post("/api-keys/{key_id}/toggle")
async def toggle_api_key(
    key_id: int,
    request: Request,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    form = await request.form()
    validate_csrf(request, dict(form))

    result = await db.execute(select(ApiKey).where(ApiKey.id == key_id))
    api_key = result.scalar_one_or_none()
    if not api_key:
        raise HTTPException(status_code=404, detail="API key not found")

    api_key.is_active = not api_key.is_active
    await db.commit()
    return RedirectResponse("/admin/api-keys", status_code=303)


@router.post("/api-keys/{key_id}/delete")
async def delete_api_key(
    key_id: int,
    request: Request,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    form = await request.form()
    validate_csrf(request, dict(form))

    result = await db.execute(select(ApiKey).where(ApiKey.id == key_id))
    api_key = result.scalar_one_or_none()
    if not api_key:
        raise HTTPException(status_code=404, detail="API key not found")

    await db.delete(api_key)
    await db.commit()
    return RedirectResponse("/admin/api-keys", status_code=303)
