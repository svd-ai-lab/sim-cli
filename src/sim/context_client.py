"""Client for the hosted Engineering Context API."""
from __future__ import annotations

from typing import Any

import httpx

from sim import config as _cfg


class MissingContextApiKey(RuntimeError):
    """Raised when no hosted context API key is configured."""


class ContextApiError(RuntimeError):
    def __init__(self, status_code: int | None, error_code: str, message: str, detail: Any = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code
        self.message = message
        self.detail = detail


def _endpoint(base_url: str) -> str:
    return base_url.rstrip("/") + "/context"


def _extract_error(response: httpx.Response) -> tuple[str, str, Any]:
    try:
        payload = response.json()
    except ValueError:
        return "CONTEXT_API_REQUEST_FAILED", response.text or f"HTTP {response.status_code}", None

    detail = payload.get("detail", payload)
    if isinstance(detail, dict):
        code = str(detail.get("error_code") or _code_for_status(response.status_code))
        message = str(detail.get("message") or detail.get("error") or f"HTTP {response.status_code}")
    else:
        code = _code_for_status(response.status_code)
        message = str(detail)
    return code, message, payload


def _code_for_status(status_code: int) -> str:
    if status_code in {401, 403}:
        return "CONTEXT_API_UNAUTHORIZED"
    if status_code == 429:
        return "CONTEXT_API_RATE_LIMITED"
    return "CONTEXT_API_REQUEST_FAILED"


def get_context(
    *,
    domain: str,
    query: str,
    max_tokens: int = 4000,
    source_preference: str = "any",
    solver_version: str | None = None,
    api_base_url: str | None = None,
    api_key: str | None = None,
    timeout: float = 20.0,
) -> dict[str, Any]:
    key = api_key or _cfg.resolve_context_api_key()
    if not key:
        raise MissingContextApiKey("Set SIM_CONTEXT_API_KEY or [context].api_key before requesting hosted context.")

    payload = {
        "domain": domain,
        "query": query,
        "max_tokens": max_tokens,
        "source_preference": source_preference,
    }
    if solver_version:
        payload["solver_version"] = solver_version

    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.post(
                _endpoint(api_base_url or _cfg.resolve_context_api_base_url()),
                headers={"Authorization": f"Bearer {key}"},
                json=payload,
            )
    except httpx.HTTPError as exc:
        raise ContextApiError(None, "CONTEXT_API_REQUEST_FAILED", f"Cannot reach hosted context API: {exc}") from exc

    if response.status_code != 200:
        code, message, detail = _extract_error(response)
        raise ContextApiError(response.status_code, code, message, detail)
    return response.json()
