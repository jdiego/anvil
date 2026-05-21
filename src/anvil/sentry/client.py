from __future__ import annotations

from typing import Any

import httpx

from anvil.http import DEFAULT_TIMEOUT, request_json

SERVICE = "sentry"


def sentry_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }


def _api_root(base_url: str) -> str:
    return f"{base_url.rstrip('/')}/api/0"


async def get_authenticated(base_url: str, token: str) -> dict[str, Any]:
    """Return the Sentry user associated with the token. Used by ``doctor``."""

    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
        result = await request_json(
            client,
            "GET",
            f"{_api_root(base_url)}/",
            service=SERVICE,
            headers=sentry_headers(token),
        )
    return result  # type: ignore[no-any-return]


async def fetch_issue_with_latest_event(
    base_url: str,
    token: str,
    issue_id: str,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    issue_url = f"{_api_root(base_url)}/issues/{issue_id}/"

    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
        issue = await request_json(
            client,
            "GET",
            issue_url,
            service=SERVICE,
            headers=sentry_headers(token),
        )
        events = await request_json(
            client,
            "GET",
            f"{issue_url}events/",
            service=SERVICE,
            headers=sentry_headers(token),
            params={"limit": 1},
        )

    latest_event = events[0] if events else None
    return issue, latest_event


async def list_project_issues(
    base_url: str,
    token: str,
    organization_slug: str,
    project_slug: str,
    *,
    query: str | None = None,
    environment: str | None = None,
) -> list[dict[str, Any]]:
    params: dict[str, Any] = {"limit": 25}
    if query:
        params["query"] = query
    if environment:
        params["environment"] = environment

    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
        result = await request_json(
            client,
            "GET",
            f"{_api_root(base_url)}/projects/{organization_slug}/{project_slug}/issues/",
            service=SERVICE,
            headers=sentry_headers(token),
            params=params,
        )
    return result if isinstance(result, list) else []


async def update_issue(
    base_url: str,
    token: str,
    issue_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
        result = await request_json(
            client,
            "PUT",
            f"{_api_root(base_url)}/issues/{issue_id}/",
            service=SERVICE,
            headers=sentry_headers(token),
            json=payload,
        )
    return result  # type: ignore[no-any-return]


async def create_issue_comment(
    base_url: str,
    token: str,
    issue_id: str,
    text: str,
) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
        result = await request_json(
            client,
            "POST",
            f"{_api_root(base_url)}/issues/{issue_id}/comments/",
            service=SERVICE,
            headers=sentry_headers(token),
            json={"text": text},
        )
    return result  # type: ignore[no-any-return]


async def get_project_release(
    base_url: str,
    token: str,
    organization_slug: str,
    project_slug: str,
    version: str,
) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
        result = await request_json(
            client,
            "GET",
            f"{_api_root(base_url)}/projects/{organization_slug}/{project_slug}/releases/{version}/",
            service=SERVICE,
            headers=sentry_headers(token),
        )
    return result  # type: ignore[no-any-return]
