import json
import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response, StreamingResponse

from app.auth import get_account_from_api_key
from app.models import Account
from app.owui_auth import AuthError, add_owui_chat_fields, authed_request

log = logging.getLogger(__name__)

router = APIRouter(tags=["api"])

# Extra headers (on top of Authorization/User-Agent set by authed_request) used to
# make forwarded chat requests resemble a real browser session.
FORWARD_HEADERS = {
    "Accept": "text/event-stream",
    "Accept-Encoding": "gzip, deflate, br",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Sec-Fetch-Mode": "cors",
    "Content-Type": "application/json",
}


def get_http_client(request: Request) -> httpx.AsyncClient:
    return request.app.state.http_client


async def stream_sse(resp: httpx.Response):
    """Re-emit the upstream SSE stream in strict `data: ...\\r\\n\\r\\n` form.

    Always closes the upstream response so the connection is released even if the
    client disconnects mid-stream.
    """
    try:
        async for line in resp.aiter_lines():
            line = line.strip()
            if not line:
                continue
            if line.startswith("data:"):
                yield (line + "\r\n\r\n").encode("utf-8")
            elif line == "[DONE]":
                yield b"data: [DONE]\r\n\r\n"
                break
    finally:
        await resp.aclose()


def _forward_headers(account: Account) -> dict:
    return {
        **FORWARD_HEADERS,
        "Origin": account.target_url,
        "Referer": f"{account.target_url}/",
    }


def _apply_model_prefix(payload: dict, account: Account) -> None:
    """Prefix the request's model id in place so it matches the target whitelist."""
    prefix = account.model_prefix
    model = payload.get("model")
    if prefix and model and not model.startswith(prefix):
        payload["model"] = prefix + model
        log.info("Model prefixed: %s -> %s", model, payload["model"])


def _strip_model_prefix(model_id: str, prefix: str) -> str:
    """Remove prefix from a model id so clients see the original name."""
    if prefix and model_id.startswith(prefix):
        return model_id[len(prefix):]
    return model_id


@router.post("/v1/chat/completions")
@router.post("/api/chat/completions")
async def proxy_chat_completions(
    request: Request,
    account: Account = Depends(get_account_from_api_key),
):
    http_client = get_http_client(request)
    body = await request.body()

    # Parse the body once; reuse it for prefixing and the stream flag.
    try:
        payload = json.loads(body) if body else {}
    except json.JSONDecodeError:
        payload = {}

    if payload:
        _apply_model_prefix(payload, account)
        add_owui_chat_fields(payload)
        body = json.dumps(payload).encode("utf-8")

    is_stream = bool(payload.get("stream", False))
    target_url = f"{account.target_url}/api/chat/completions"

    try:
        resp = await authed_request(
            account, http_client, "POST", target_url,
            content=body, extra_headers=_forward_headers(account), stream=True,
        )
    except AuthError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except httpx.ConnectError as e:
        log.error("Connect error to %s: %s", target_url, e)
        raise HTTPException(status_code=502, detail="无法连接到目标服务器")
    except httpx.TimeoutException:
        log.error("Timeout connecting to %s", target_url)
        raise HTTPException(status_code=504, detail="目标服务器响应超时")

    if resp.status_code >= 400:
        error_body = await resp.aread()
        await resp.aclose()
        return Response(content=error_body, status_code=resp.status_code, media_type="application/json")

    if is_stream:
        return StreamingResponse(
            stream_sse(resp),
            status_code=resp.status_code,
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    full_body = await resp.aread()
    await resp.aclose()
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
        resp = await authed_request(account, http_client, "GET", target_url)
    except AuthError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except httpx.ConnectError:
        raise HTTPException(status_code=502, detail="无法连接到目标服务器")
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="目标服务器响应超时")

    if resp.status_code != 200:
        return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")

    # Normalize OpenWebUI's /api/models into a strict OpenAI /v1/models response
    # (`{"object":"list","data":[{"id","object","created","owned_by"}]}`) and strip
    # the account prefix so third-party clients see clean, selectable model ids.
    try:
        data = resp.json()
        models = []
        for m in data.get("data", []):
            mid = _strip_model_prefix(m.get("id", ""), account.model_prefix)
            if mid:
                models.append({"id": mid, "object": "model", "created": 0, "owned_by": "openwebui"})
        payload = {"object": "list", "data": models}
        return Response(content=json.dumps(payload).encode("utf-8"), media_type="application/json")
    except (json.JSONDecodeError, AttributeError, TypeError):
        return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")
