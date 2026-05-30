import logging
import secrets
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import hash_password, require_admin, validate_csrf
from app.crypto import encrypt
from app.database import get_db
from app.models import Account, ApiKey, User
from app.owui_auth import authed_request
from app.schemas import AccountForm, AccountUpdateForm, ApiKeyForm, UserForm, UserUpdateForm

log = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])


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
        raise HTTPException(status_code=400, detail="目标地址必须以 http:// 或 https:// 开头")

    account = Account(
        name=data.name,
        target_url=data.target_url.rstrip("/"),
        auth_mode=data.auth_mode,
        email=data.email,
        password=encrypt(data.password),
        session_token=encrypt(data.session_token),
        model_prefix=data.model_prefix,
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
        raise HTTPException(status_code=404, detail="账号不存在")

    form_dict = dict(form)
    # Blank fields mean "leave unchanged" for credentials (password/token), so
    # they're filtered out below. model_prefix is the exception: an empty value
    # is a real value meaning "no prefix", so it is applied directly from the form.
    data = AccountUpdateForm(**{k: v for k, v in form_dict.items() if v is not None and v != ""})
    if data.name is not None:
        account.name = data.name
    if data.target_url is not None:
        account.target_url = data.target_url.rstrip("/")
    if data.auth_mode is not None:
        account.auth_mode = data.auth_mode
    if data.email is not None:
        account.email = data.email
    if data.password is not None:
        account.password = encrypt(data.password)
    if data.session_token is not None:
        account.session_token = encrypt(data.session_token)
    if "model_prefix" in form_dict:
        account.model_prefix = (form_dict.get("model_prefix") or "").strip()

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
        raise HTTPException(status_code=400, detail="请先删除该账号下的所有 API 密钥")

    result = await db.execute(select(Account).where(Account.id == account_id))
    account = result.scalar_one_or_none()
    if not account:
        raise HTTPException(status_code=404, detail="账号不存在")

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
        raise HTTPException(status_code=404, detail="账号不存在")

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
        raise HTTPException(status_code=404, detail="账号不存在")

    http_client: httpx.AsyncClient = request.app.state.http_client
    status = "unhealthy"
    try:
        resp = await authed_request(
            account, http_client, "GET", f"{account.target_url}/api/models", timeout=10.0
        )
        if resp.status_code == 200:
            status = "healthy"
    except Exception:
        pass

    account.health_status = status
    account.last_health_check = datetime.now(timezone.utc)
    await db.commit()
    return RedirectResponse("/admin/accounts", status_code=303)


@router.get("/accounts/{account_id}/models")
async def get_models(
    account_id: int,
    request: Request,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Account).where(Account.id == account_id))
    account = result.scalar_one_or_none()
    if not account:
        return JSONResponse({"models": [], "prefix": "", "error": "账号不存在"})

    http_client: httpx.AsyncClient = request.app.state.http_client
    prefix = account.model_prefix or ""

    try:
        resp = await authed_request(
            account, http_client, "GET", f"{account.target_url}/api/models", timeout=10.0
        )
    except Exception as e:
        return JSONResponse({"models": [], "prefix": prefix, "error": f"请求失败: {e}"})

    if resp.status_code != 200:
        return JSONResponse({"models": [], "prefix": prefix, "error": f"HTTP {resp.status_code}"})

    try:
        data = resp.json()
    except Exception as e:
        return JSONResponse({"models": [], "prefix": prefix, "error": f"解析失败: {e}"})

    models = []
    for m in data.get("data", []):
        mid = m.get("id", "")
        display_name = mid[len(prefix):] if prefix and mid.startswith(prefix) else mid
        models.append({"id": mid, "name": display_name})

    return JSONResponse({"models": models, "prefix": prefix, "error": None})

@router.post("/users")
async def create_user(
    request: Request,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    form = await request.form()
    validate_csrf(request, dict(form))
    data = UserForm(**dict(form))

    result = await db.execute(select(User).where(User.email == data.email))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="邮箱已存在")

    new_user = User(
        email=data.email,
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
        raise HTTPException(status_code=404, detail="用户不存在")

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
        raise HTTPException(status_code=404, detail="用户不存在")

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
        raise HTTPException(status_code=400, detail="不能删除自己")

    result = await db.execute(select(User).where(User.id == user_id))
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="用户不存在")

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
        raise HTTPException(status_code=400, detail="账号不存在")

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
        raise HTTPException(status_code=404, detail="API 密钥不存在")

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
        raise HTTPException(status_code=404, detail="API 密钥不存在")

    await db.delete(api_key)
    await db.commit()
    return RedirectResponse("/admin/api-keys", status_code=303)
