"""Supabase Google sign-in with PKCE. Pure functions: no Streamlit imports, so they test alone.

A full-page redirect starts a new Streamlit session, so the PKCE verifier cannot live in
`st.session_state`; `VerifierStore` keeps it per process, keyed by a flow id carried in the
redirect URL (Supabase returns no client `state`). Tokens are never logged or put in errors.
"""

import base64
import hashlib
import secrets
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx

VERIFIER_TTL_SECONDS = 600
VERIFIER_CAP = 1000
REFRESH_MARGIN_SECONDS = 60
HTTP_TIMEOUT = 10


class AuthError(Exception):
    """Sign-in or refresh failed. The message is generic on purpose."""


@dataclass(frozen=True)
class Tokens:
    access_token: str
    refresh_token: str
    expires_at: float


def new_verifier() -> str:
    return secrets.token_urlsafe(48)  # 64 URL-safe characters


def challenge_for(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


class VerifierStore:
    """Single-use verifiers with a TTL and a size cap (oldest evicted first)."""

    def __init__(
        self,
        clock: Callable[[], float] = time.monotonic,
        ttl: float = VERIFIER_TTL_SECONDS,
        cap: int = VERIFIER_CAP,
    ):
        self._clock, self._ttl, self._cap = clock, ttl, cap
        self._items: OrderedDict[str, tuple[str, float]] = OrderedDict()
        self._lock = threading.Lock()

    def put(self, flow_id: str, verifier: str) -> None:
        with self._lock:
            self._items[flow_id] = (verifier, self._clock() + self._ttl)
            while len(self._items) > self._cap:
                self._items.popitem(last=False)

    def pop(self, flow_id: str) -> str | None:
        with self._lock:
            entry = self._items.pop(flow_id, None)
        if entry is None or entry[1] < self._clock():
            return None
        return entry[0]


def authorize_url(
    *, supabase_url: str, redirect_to: str, challenge: str, provider: str = "google"
) -> str:
    query = urlencode(
        {
            "provider": provider,
            "redirect_to": redirect_to,
            "code_challenge": challenge,
            "code_challenge_method": "s256",
        }
    )
    return f"{supabase_url.rstrip('/')}/auth/v1/authorize?{query}"


def needs_refresh(tokens: Tokens, now: float, margin: float = REFRESH_MARGIN_SECONDS) -> bool:
    return tokens.expires_at - now < margin


def _token_call(
    client: httpx.Client,
    supabase_url: str,
    anon_key: str,
    grant: str,
    body: dict,
    now: float | None,
) -> Tokens:
    try:
        response = client.post(
            f"{supabase_url.rstrip('/')}/auth/v1/token",
            params={"grant_type": grant},
            headers={"apikey": anon_key},
            json=body,
            timeout=HTTP_TIMEOUT,
        )
        if response.status_code != 200:
            raise AuthError("Sign-in failed")
        data = response.json()
        return Tokens(
            access_token=data["access_token"],
            refresh_token=data["refresh_token"],
            expires_at=(time.time() if now is None else now) + float(data["expires_in"]),
        )
    except (httpx.HTTPError, KeyError, ValueError, TypeError):
        raise AuthError("Sign-in failed") from None


def exchange_code(
    client: httpx.Client,
    *,
    supabase_url: str,
    anon_key: str,
    code: str,
    verifier: str,
    now: float | None = None,
) -> Tokens:
    body = {"auth_code": code, "code_verifier": verifier}
    return _token_call(client, supabase_url, anon_key, "pkce", body, now)


def refresh(
    client: httpx.Client,
    *,
    supabase_url: str,
    anon_key: str,
    refresh_token: str,
    now: float | None = None,
) -> Tokens:
    body = {"refresh_token": refresh_token}
    return _token_call(client, supabase_url, anon_key, "refresh_token", body, now)


def sign_out(client: httpx.Client, *, supabase_url: str, anon_key: str, access_token: str) -> None:
    """Best-effort server-side logout; the local session is cleared regardless."""
    try:
        client.post(
            f"{supabase_url.rstrip('/')}/auth/v1/logout",
            headers={"apikey": anon_key, "Authorization": f"Bearer {access_token}"},
            timeout=HTTP_TIMEOUT,
        )
    except httpx.HTTPError:
        pass
