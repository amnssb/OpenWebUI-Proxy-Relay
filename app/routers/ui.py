from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_csrf_token, require_admin
from app.database import get_db
from app.models import Account, ApiKey, User
from app.templating import templates

router = APIRouter(tags=["ui"])


def ctx(user: User, request: Request, **kwargs) -> dict:
    return {"user": user, "csrf_token": get_csrf_token(request), **kwargs}


@router.get("/", response_class=HTMLResponse)
async def index():
    return RedirectResponse("/admin/dashboard")


@router.get("/admin/dashboard", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    account_count = (await db.execute(select(func.count(Account.id)))).scalar() or 0
    api_key_count = (await db.execute(select(func.count(ApiKey.id)))).scalar() or 0
    user_count = (await db.execute(select(func.count(User.id)))).scalar() or 0

    result = await db.execute(select(Account).order_by(Account.created_at.desc()).limit(5))
    recent_accounts = result.scalars().all()

    return templates.TemplateResponse(
        request, "dashboard.html",
        ctx(user, request,
            account_count=account_count,
            api_key_count=api_key_count,
            user_count=user_count,
            recent_accounts=recent_accounts),
    )


@router.get("/admin/accounts", response_class=HTMLResponse)
async def accounts_page(
    request: Request,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Account).order_by(Account.created_at.desc()))
    accounts = result.scalars().all()

    key_counts_result = await db.execute(
        select(ApiKey.account_id, func.count(ApiKey.id)).group_by(ApiKey.account_id)
    )
    key_counts = dict(key_counts_result.all())

    return templates.TemplateResponse(
        request, "accounts.html",
        ctx(user, request, accounts=accounts, key_counts=key_counts),
    )


@router.get("/admin/users", response_class=HTMLResponse)
async def users_page(
    request: Request,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).order_by(User.created_at.desc()))
    users = result.scalars().all()

    return templates.TemplateResponse(
        request, "users.html",
        ctx(user, request, users=users),
    )


@router.get("/admin/api-keys", response_class=HTMLResponse)
async def api_keys_page(
    request: Request,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(ApiKey).order_by(ApiKey.created_at.desc()))
    api_keys = result.scalars().all()

    result = await db.execute(select(Account).order_by(Account.name))
    accounts = result.scalars().all()

    account_map = {a.id: a.name for a in accounts}

    new_api_key = request.session.pop("new_api_key", None)

    return templates.TemplateResponse(
        request, "api_keys.html",
        ctx(user, request, api_keys=api_keys, accounts=accounts, account_map=account_map, new_api_key=new_api_key),
    )
