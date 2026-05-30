import logging
import re
import time

import httpx
import jwt

from app.crypto import decrypt

log = logging.getLogger(__name__)


class AuthError(Exception):
    """Raised when a usable session token cannot be obtained for an account."""


# Matches the `token=<jwt>` pair inside a cookie string, anchored to a cookie
# boundary so it doesn't pick up names like `csrftoken=`.
_TOKEN_COOKIE_RE = re.compile(r"(?:^|[;\s])token=([^;\s]+)")


def normalize_session_token(raw: str) -> str:
    """Extract a bare JWT from whatever the user pasted out of F12.

    Accepts the raw JWT, ``Bearer <jwt>``, ``Authorization: Bearer <jwt>`` and the
    OpenWebUI cookie form ``token=<jwt>`` (including a full cookie string).
    """
    if not raw:
        return ""
    s = raw.strip().strip('"').strip("'").strip()
    # Header line: "Authorization: Bearer <jwt>"
    if ":" in s and s.lower().startswith("authorization"):
        s = s.split(":", 1)[1].strip()
    # Cookie form: pull out the `token=` value.
    match = _TOKEN_COOKIE_RE.search(s)
    if match:
        s = match.group(1)
    # Scheme prefix: "Bearer <jwt>"
    elif s.lower().startswith("bearer "):
        s = s[7:].strip()
    return s.strip()

# Shared browser User-Agent used for both login and forwarded requests so the
# target's bot/security checks see a consistent client.
BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# In-memory token cache: account_id -> {"token": str, "expires_at": float}
_token_cache: dict[int, dict] = {}


def jwt_expiry(token: str) -> float | None:
    """Return a JWT's `exp` (epoch seconds) without verifying the signature."""
    try:
        claims = jwt.decode(token, options={"verify_signature": False})
        exp = claims.get("exp")
        return float(exp) if exp is not None else None
    except Exception:
        return None


async def get_session_token(account, http_client: httpx.AsyncClient) -> str:
    """Get a valid session token for the account.

    - ``token`` mode: use the manually captured JWT directly (no login).
    - ``password`` mode: reuse a cached token or auto-login.
    """
    if getattr(account, "auth_mode", "password") == "token":
        token = decrypt(account.session_token)
        if not token:
            raise AuthError("该账号为 Token 模式但未填写 Session Token，请在 F12 中抓取后填入")
        exp = jwt_expiry(token)
        if exp is not None and exp < time.time():
            raise AuthError("Session Token 已过期，请重新在浏览器 F12 中抓取最新 Token")
        return token

    cached = _token_cache.get(account.id)
    if cached and cached["expires_at"] > time.time() + 60:
        return cached["token"]

    token = await _login_to_openwebui(account, http_client)
    if not token:
        raise AuthError(f"登录失败：{account.email}@{account.target_url}（邮箱或密码错误，或目标不可达）")

    return token


async def _login_to_openwebui(account, http_client: httpx.AsyncClient) -> str | None:
    """Login to OpenWebUI and get JWT token."""
    login_url = f"{account.target_url.rstrip('/')}/api/v1/auths/signin"

    try:
        resp = await http_client.post(
            login_url,
            json={"email": account.email, "password": decrypt(account.password)},
            headers={"Content-Type": "application/json", "User-Agent": BROWSER_UA},
            timeout=15.0,
        )

        if resp.status_code != 200:
            log.error(f"Login failed for {account.email}@{account.target_url}: {resp.status_code} {resp.text[:200]}")
            return None

        data = resp.json()
        token = data.get("token")
        if not token:
            log.error(f"No token in login response: {data}")
            return None

        # Cache token for 24 hours (OpenWebUI default JWT expiry)
        _token_cache[account.id] = {
            "token": token,
            "expires_at": time.time() + 86400,
        }

        log.info(f"Logged in to {account.target_url} as {account.email}")
        return token

    except httpx.ConnectError as e:
        log.error(f"Cannot connect to {account.target_url}: {e}")
        return None
    except Exception as e:
        log.error(f"Login error for {account.email}@{account.target_url}: {e}")
        return None


def invalidate_token(account_id: int):
    """Remove cached token for an account (e.g. after 401)."""
    _token_cache.pop(account_id, None)


async def authed_request(
    account,
    http_client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    extra_headers: dict | None = None,
    stream: bool = False,
    **kwargs,
) -> httpx.Response:
    """Send a request to the target using the account's session token.

    Retries once with a fresh token on 401. When ``stream=True`` the response is
    returned with its body unread — the caller is responsible for closing it.
    """

    async def _send() -> httpx.Response:
        token = await get_session_token(account, http_client)
        # Send the session token both as a Bearer header and as the `token`
        # cookie — OpenWebUI's web UI authenticates via the cookie, and targets
        # behind an SSO/WAF gateway may require it.
        headers = {
            "Authorization": f"Bearer {token}",
            "Cookie": f"token={token}",
            "User-Agent": BROWSER_UA,
        }
        if extra_headers:
            headers.update(extra_headers)
        req = http_client.build_request(method, url, headers=headers, **kwargs)
        return await http_client.send(req, stream=stream)

    resp = await _send()
    # Only password-mode tokens can be refreshed; a manually captured token that
    # returns 401 is simply expired and re-fetching would change nothing.
    if resp.status_code == 401 and getattr(account, "auth_mode", "password") != "token":
        if stream:
            await resp.aclose()
        invalidate_token(account.id)
        resp = await _send()
    return resp
