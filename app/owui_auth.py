import json
import logging
import time

import httpx

log = logging.getLogger(__name__)

# In-memory token cache: account_id -> {"token": str, "expires_at": float}
_token_cache: dict[int, dict] = {}


async def get_session_token(account, http_client: httpx.AsyncClient) -> str:
    """Get a valid session token for the account, auto-login if needed."""
    cached = _token_cache.get(account.id)
    if cached and cached["expires_at"] > time.time() + 60:
        return cached["token"]

    token = await _login_to_openwebui(account, http_client)
    if not token:
        raise Exception(f"Failed to login to {account.target_url} with {account.email}")

    return token


async def _login_to_openwebui(account, http_client: httpx.AsyncClient) -> str | None:
    """Login to OpenWebUI and get JWT token."""
    login_url = f"{account.target_url.rstrip('/')}/api/v1/auths/signin"

    try:
        resp = await http_client.post(
            login_url,
            json={"email": account.email, "password": account.password},
            headers={
                "Content-Type": "application/json",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            },
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
