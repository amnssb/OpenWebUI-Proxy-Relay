import json
import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response, StreamingResponse

from app.auth import get_account_from_api_key
from app.models import Account
from app.owui_auth import get_session_token, invalidate_token

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


async def _build_headers(account: Account, http_client: httpx.AsyncClient) -> dict:
    token = await get_session_token(account, http_client)
    return {
        **BROWSER_HEADERS,
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
        "Origin": account.target_url,
        "Referer": f"{account.target_url}/",
    }


def _apply_model_map(body: bytes, account: Account) -> bytes:
    """Apply model name mapping from account config to request body."""
    if not body:
        return body
    try:
        model_map = json.loads(account.model_map) if account.model_map else {}
    except (json.JSONDecodeError, TypeError):
        model_map = {}
    if not model_map:
        return body

    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return body

    client_model = data.get("model")
    if client_model and client_model in model_map:
        data["model"] = model_map[client_model]
        log.info(f"Model mapped: {client_model} -> {data['model']}")
        return json.dumps(data).encode("utf-8")

    return body


@router.post("/v1/chat/completions")
@router.post("/api/chat/completions")
async def proxy_chat_completions(
    request: Request,
    account: Account = Depends(get_account_from_api_key),
):
    http_client = get_http_client(request)
    body = await request.body()

    # Apply model name mapping
    body = _apply_model_map(body, account)

    target_url = f"{account.target_url}/api/chat/completions"

    try:
        headers = await _build_headers(account, http_client)
        resp = await http_client.post(
            target_url,
            content=body,
            headers=headers,
            stream=True,
        )

        # If 401, invalidate token and retry once
        if resp.status_code == 401:
            invalidate_token(account.id)
            headers = await _build_headers(account, http_client)
            resp = await http_client.post(
                target_url,
                content=body,
                headers=headers,
                stream=True,
            )

    except httpx.ConnectError as e:
        log.error(f"Connect error to {target_url}: {e}")
        raise HTTPException(status_code=502, detail="无法连接到目标服务器")
    except httpx.TimeoutException:
        log.error(f"Timeout connecting to {target_url}")
        raise HTTPException(status_code=504, detail="目标服务器响应超时")

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
        headers = await _build_headers(account, http_client)
        resp = await http_client.get(target_url, headers=headers)

        # If 401, retry once
        if resp.status_code == 401:
            invalidate_token(account.id)
            headers = await _build_headers(account, http_client)
            resp = await http_client.get(target_url, headers=headers)

        # Apply reverse model mapping
        try:
            model_map = json.loads(account.model_map) if account.model_map else {}
        except (json.JSONDecodeError, TypeError):
            model_map = {}

        if model_map:
            reverse_map = {v: k for k, v in model_map.items()}
            try:
                body = json.loads(resp.content)
                if "data" in body:
                    for m in body["data"]:
                        if m.get("id") in reverse_map:
                            m["id"] = reverse_map[m["id"]]
                            m["owned_by"] = "proxy"
                return Response(content=json.dumps(body).encode(), status_code=resp.status_code, media_type="application/json")
            except (json.JSONDecodeError, KeyError):
                pass

        return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")
    except httpx.ConnectError:
        raise HTTPException(status_code=502, detail="无法连接到目标服务器")
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="目标服务器响应超时")
