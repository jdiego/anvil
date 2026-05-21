from __future__ import annotations

from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any

import httpx
from tenacity import (
    AsyncRetrying,
    RetryCallState,
    retry_if_exception,
    stop_after_attempt,
    wait_random_exponential,
)

from anvil.exceptions import UpstreamHTTPError
from anvil.logging import get_logger

DEFAULT_TIMEOUT = httpx.Timeout(30.0, connect=10.0)
DEFAULT_RETRIES = 3
RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504})
HTTP_NO_CONTENT = 204

_logger = get_logger(__name__)
_fallback_wait = wait_random_exponential(multiplier=0.5, max=8)


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.TransportError):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in RETRYABLE_STATUSES
    return False


def _retry_after_seconds(value: str) -> float | None:
    if value.isdecimal():
        return max(0.0, float(value))

    try:
        retry_at = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None

    if retry_at.tzinfo is None:
        retry_at = retry_at.replace(tzinfo=UTC)

    return max(0.0, (retry_at - datetime.now(UTC)).total_seconds())


def _wait_with_retry_after(retry_state: RetryCallState) -> float:
    exc = retry_state.outcome.exception() if retry_state.outcome else None
    if isinstance(exc, httpx.HTTPStatusError):
        retry_after = exc.response.headers.get("Retry-After")
        if retry_after:
            seconds = _retry_after_seconds(retry_after)
            if seconds is not None:
                return seconds

    return float(_fallback_wait(retry_state))


async def request_json(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    service: str,
    headers: dict[str, str] | None = None,
    params: dict[str, Any] | None = None,
    json: dict[str, Any] | None = None,
    retries: int = DEFAULT_RETRIES,
) -> Any:
    """Issue a request with retries, mapping upstream errors to :class:`UpstreamHTTPError`.

    Retries transport errors and 429/5xx with exponential backoff and jitter.
    """

    try:
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(retries),
            wait=_wait_with_retry_after,
            retry=retry_if_exception(_is_retryable),
            reraise=True,
        ):
            with attempt:
                response = await client.request(
                    method,
                    url,
                    headers=headers,
                    params=params,
                    json=json,
                )
                response.raise_for_status()
                _logger.debug(
                    "upstream_ok",
                    service=service,
                    method=method,
                    url=url,
                    status_code=response.status_code,
                    attempt=attempt.retry_state.attempt_number,
                )
                if response.status_code == HTTP_NO_CONTENT or not response.content:
                    return None
                return response.json()
    except httpx.HTTPStatusError as exc:
        _logger.warning(
            "upstream_http_error_final",
            service=service,
            method=method,
            url=url,
            status_code=exc.response.status_code,
        )
        raise UpstreamHTTPError(
            service=service,
            status_code=exc.response.status_code,
            message=exc.response.text[:500],
        ) from exc
    except httpx.TransportError as exc:
        _logger.warning(
            "upstream_transport_error_final",
            service=service,
            method=method,
            url=url,
            error=str(exc),
        )
        raise UpstreamHTTPError(
            service=service,
            status_code=0,
            message=str(exc),
        ) from exc

    # Defensive: AsyncRetrying with reraise=True always returns or raises.
    raise UpstreamHTTPError(
        service=service,
        status_code=0,
        message="exhausted retries without response",
    )


async def request_text(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    service: str,
    headers: dict[str, str] | None = None,
    params: dict[str, Any] | None = None,
    retries: int = DEFAULT_RETRIES,
) -> str:
    """Issue a request returning text with the same retry/error mapping as request_json."""

    try:
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(retries),
            wait=_wait_with_retry_after,
            retry=retry_if_exception(_is_retryable),
            reraise=True,
        ):
            with attempt:
                response = await client.request(
                    method,
                    url,
                    headers=headers,
                    params=params,
                )
                response.raise_for_status()
                _logger.debug(
                    "upstream_ok",
                    service=service,
                    method=method,
                    url=url,
                    status_code=response.status_code,
                    attempt=attempt.retry_state.attempt_number,
                )
                return response.text
    except httpx.HTTPStatusError as exc:
        _logger.warning(
            "upstream_http_error_final",
            service=service,
            method=method,
            url=url,
            status_code=exc.response.status_code,
        )
        raise UpstreamHTTPError(
            service=service,
            status_code=exc.response.status_code,
            message=exc.response.text[:500],
        ) from exc
    except httpx.TransportError as exc:
        _logger.warning(
            "upstream_transport_error_final",
            service=service,
            method=method,
            url=url,
            error=str(exc),
        )
        raise UpstreamHTTPError(
            service=service,
            status_code=0,
            message=str(exc),
        ) from exc

    raise UpstreamHTTPError(
        service=service,
        status_code=0,
        message="exhausted retries without response",
    )
