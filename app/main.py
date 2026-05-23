import logging
import os
from contextlib import asynccontextmanager

import httpx
import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.auth import hash_password
from app.config import settings
from app.database import async_session, init_db
from app.models import User
from app.routers.admin import router as admin_router
from app.routers.api import router as api_router
from app.routers.auth import router as auth_router
from app.routers.ui import router as ui_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
log = logging.getLogger(__name__)


async def seed_admin():
    from sqlalchemy import select

    async with async_session() as db:
        result = await db.execute(select(User).where(User.role == "admin"))
        if result.scalar_one_or_none():
            return
        admin = User(
            email=settings.default_admin_email,
            password_hash=hash_password(settings.default_admin_password),
            role="admin",
        )
        db.add(admin)
        await db.commit()
        log.info("Default admin '%s' created", settings.default_admin_email)


@asynccontextmanager
async def lifespan(app: FastAPI):
    os.makedirs("data", exist_ok=True)
    await init_db()
    await seed_admin()

    app.state.http_client = httpx.AsyncClient(
        verify=False,
        timeout=httpx.Timeout(connect=10.0, read=settings.request_timeout, write=10.0, pool=10.0),
        follow_redirects=True,
    )
    log.info("Proxy relay started")
    yield
    await app.state.http_client.aclose()
    log.info("Proxy relay stopped")


app = FastAPI(title="OpenWebUI Proxy Relay", lifespan=lifespan)

app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret,
    session_cookie="session",
    max_age=86400 * 3,
    same_site="lax",
    https_only=False,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="app/static"), name="static")

app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(ui_router)
app.include_router(api_router)


@app.exception_handler(HTTPException)
async def redirect_handler(request: Request, exc: HTTPException):
    if exc.status_code == 303 and exc.headers and "Location" in exc.headers:
        return RedirectResponse(url=exc.headers["Location"], status_code=303)
    from fastapi.responses import JSONResponse

    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, workers=1)
