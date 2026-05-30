import asyncio
import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import (
    check_rate_limit,
    clear_failures,
    get_csrf_token,
    record_failure,
    validate_csrf,
    verify_password,
)
from app.database import get_db
from app.models import User
from app.templating import templates

log = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse(request, "login.html", {"error": None, "csrf_token": get_csrf_token(request)})


@router.post("/login", response_class=HTMLResponse)
async def login_submit(request: Request, db: AsyncSession = Depends(get_db)):
    form = await request.form()
    form_dict = dict(form)
    validate_csrf(request, form_dict)

    ip = request.client.host if request.client else "unknown"
    check_rate_limit(ip)

    email = form_dict.get("email", "")
    password = form_dict.get("password", "")

    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()

    if not user or not await asyncio.to_thread(verify_password, password, user.password_hash):
        record_failure(ip)
        return templates.TemplateResponse(
            request, "login.html",
            {"error": "用户名或密码错误", "csrf_token": get_csrf_token(request)},
            status_code=401,
        )

    if not user.is_active:
        return templates.TemplateResponse(
            request, "login.html",
            {"error": "账号已被禁用", "csrf_token": get_csrf_token(request)},
            status_code=403,
        )

    request.session["user_id"] = user.id
    request.session["role"] = user.role
    request.session["csrf_token"] = get_csrf_token(request)
    clear_failures(ip)

    return RedirectResponse("/admin/dashboard", status_code=303)


@router.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/auth/login", status_code=303)
