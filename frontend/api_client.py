"""Calls the Churnscope API with the signed-in user's Bearer token and maps failures to UI states."""

from collections.abc import Callable
from typing import Any

import httpx

TIMEOUT = 10
ANALYTICS_TIMEOUT = 30
IMPORT_TIMEOUT = 60


class NotSignedIn(Exception):
    """401: no valid session; show the sign-in page."""


class NotAllowed(Exception):
    """403: signed in, but this account is not on the allow-list."""


class ServiceUnavailable(Exception):
    """Timeout, network error, 5xx or 503: show a generic 'service unavailable'."""


class ApiError(Exception):
    def __init__(self, status_code: int, code: str | None = None):
        super().__init__(f"API returned {status_code}")
        self.status_code = status_code
        self.code = code  # the error's machine code only, never the server's message text


class ApiClient:
    def __init__(
        self, base_url: str, get_token: Callable[[], str | None], http: httpx.Client | None = None
    ):
        self._base = base_url.rstrip("/")
        self._get_token = get_token
        self._http = http or httpx.Client()

    def get(self, path: str, *, timeout: float | None = None, **params: Any) -> Any:
        return self._request("GET", path, timeout=timeout, params=params)

    def post(self, path: str, json: Any = None, *, timeout: float | None = None) -> Any:
        return self._request("POST", path, timeout=timeout, json=json)

    def post_file(
        self,
        path: str,
        *,
        file: tuple[str, bytes, str],
        data: dict[str, str],
        timeout: float | None = None,
    ) -> Any:
        """A multipart POST: `file` is (filename, content, content type), sent as field `file`."""
        return self._request("POST", path, timeout=timeout, files={"file": file}, data=data)

    def delete(self, path: str, *, timeout: float | None = None) -> Any:
        return self._request("DELETE", path, timeout=timeout)

    def _request(self, method: str, path: str, timeout: float | None, **kwargs: Any) -> Any:
        headers = {}
        if token := self._get_token():
            headers["Authorization"] = f"Bearer {token}"
        try:
            response = self._http.request(
                method,
                f"{self._base}{path}",
                headers=headers,
                timeout=TIMEOUT if timeout is None else timeout,
                **kwargs,
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
            raise ApiError(status, _error_code(response))
        return None if status == 204 else response.json()


def _error_code(response: httpx.Response) -> str | None:
    try:
        code = response.json()["detail"]["code"]
    except (ValueError, KeyError, TypeError):
        return None
    return code if isinstance(code, str) else None
