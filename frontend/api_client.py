"""Calls the Churnscope API with the signed-in user's Bearer token and maps failures to UI states."""

from collections.abc import Callable
from typing import Any

import httpx

TIMEOUT = 10


class NotSignedIn(Exception):
    """401: no valid session; show the sign-in page."""


class NotAllowed(Exception):
    """403: signed in, but this account is not on the allow-list."""


class ServiceUnavailable(Exception):
    """Timeout, network error, 5xx or 503: show a generic 'service unavailable'."""


class ApiError(Exception):
    def __init__(self, status_code: int):
        super().__init__(f"API returned {status_code}")
        self.status_code = status_code


class ApiClient:
    def __init__(
        self, base_url: str, get_token: Callable[[], str | None], http: httpx.Client | None = None
    ):
        self._base = base_url.rstrip("/")
        self._get_token = get_token
        self._http = http or httpx.Client()

    def get(self, path: str, **params: Any) -> Any:
        return self._request("GET", path, params=params)

    def post(self, path: str, json: Any = None) -> Any:
        return self._request("POST", path, json=json)

    def delete(self, path: str) -> Any:
        return self._request("DELETE", path)

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        headers = {}
        if token := self._get_token():
            headers["Authorization"] = f"Bearer {token}"
        try:
            response = self._http.request(
                method, f"{self._base}{path}", headers=headers, timeout=TIMEOUT, **kwargs
            )
        except httpx.HTTPError:
            raise ServiceUnavailable("The service is unavailable") from None
        status = response.status_code
        if status == 401:
            raise NotSignedIn("Not signed in")
        if status == 403:
            raise NotAllowed("This account is not allowed")
        if status >= 500:
            raise ServiceUnavailable("The service is unavailable")
        if status >= 400:
            raise ApiError(status)
        return None if status == 204 else response.json()
