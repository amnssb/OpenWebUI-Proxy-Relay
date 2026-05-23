import json
import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response, StreamingResponse

from app.auth import get_account_from_api_key
from app.models import Account

log = logging.getLogger(__name__)

router = APIRouter(tags=["api"])

BROWSER_HEADERS = {
    "Accept": "text/event-stream",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Encoding": "gzip, deflate, br",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Sec-Fetch-Mode": "cors",
}


def get_http_client(request: Request) -> httpx.AsyncClient:
    return request.app.state.http_client


async def stream_sse(resp: httpx.Response):
    async for line in resp.aiter_lines():
        if not line:
            continue
        line = line.strip()
        if line.startswith("data:"):
            yield (line + "\r\n\r\n").encode("utf-8")
        elif line == "[DONE]":
            yield b"data: [DONE]\r\n\r\n"
            break


def _build_headers(account: Account) -> dict:
    return {
        **BROWSER_HEADERS,
        "Content-Type": "application/json",
        "Authorization": f"Bearer {account.session_token}",
        "Origin": account.target_url,
        "Referer": f"{account.target_url}/",
    }


@router.post("/v1/chat/completions")
@router.post("/api/chat/completions")
async def proxy_chat_completions(
    request: Request,
    account: Account = Depends(get_account_from_api_key),
):
    http_client = get_http_client(request)
    body = await request.body()
    target_url = f"{account.target_url}/api/chat/completions"

    try:
        resp = await http_client.post(
            target_url,
            content=body,
            headers=_build_headers(account),
            stream=True,
        )
    except httpx.ConnectError as e:
        log.error(f"Connect error to {target_url}: {e}")
        raise HTTPException(status_code=502, detail="Cannot connect to target server")
    except httpx.TimeoutException:
        log.error(f"Timeout connecting to {target_url}")
        raise HTTPException(status_code=504, detail="Target server timeout")

    if resp.status_code >= 400:
        error_body = await resp.aread()
        return Response(content=error_body, status_code=resp.status_code, media_type="application/json")

    data = json.loads(body) if body else {}
    is_stream = data.get("stream", False)

    if is_stream:
        return StreamingResponse(
            stream_sse(resp),
            status_code=resp.status_code,
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    full_body = await resp.aread()
    return Response(content=full_body, status_code=resp.status_code, media_type="application/json")


@router.get("/v1/models")
@router.get("/api/models")
async def proxy_models(
    request: Request,
    account: Account = Depends(get_account_from_api_key),
):
    http_client = get_http_client(request)
    target_url = f"{account.target_url}/api/models"

    try:
        resp = await http_client.get(
            target_url,
            headers=_build_headers(account),
        )
        return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")
    except httpx.ConnectError:
        raise HTTPException(status_code=502, detail="Cannot connect to target server")
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Target server timeout")
