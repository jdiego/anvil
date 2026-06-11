from __future__ import annotations

from typing import Any
from urllib.parse import quote

import httpx

from anvil.http import DEFAULT_TIMEOUT, request_json, request_text

SERVICE = "github"


def github_headers(token: str, *, accept: str = "application/vnd.github+json") -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": accept,
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _api_root(base_url: str) -> str:
    return base_url.rstrip("/")


def _repo_path(repository: str) -> str:
    owner, repo = repository.split("/", maxsplit=1)
    return f"{quote(owner, safe='')}/{quote(repo, safe='')}"


def _ref_path(ref: str) -> str:
    return quote(ref, safe="")


async def get_current_user(base_url: str, token: str) -> dict[str, Any]:
    """Return the GitHub user associated with the token. Used by ``doctor``."""

    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
        result = await request_json(
            client,
            "GET",
            f"{_api_root(base_url)}/user",
            service=SERVICE,
            headers=github_headers(token),
        )
    return result  # type: ignore[no-any-return]


async def list_pull_requests(
    base_url: str,
    token: str,
    repository: str,
    *,
    state: str,
    base: str | None = None,
    head: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    params: dict[str, Any] = {
        "state": state,
        "per_page": limit,
        "sort": "updated",
        "direction": "desc",
    }
    if base:
        params["base"] = base
    if head:
        params["head"] = head

    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
        result = await request_json(
            client,
            "GET",
            f"{_api_root(base_url)}/repos/{_repo_path(repository)}/pulls",
            service=SERVICE,
            headers=github_headers(token),
            params=params,
        )
    return result if isinstance(result, list) else []


async def get_pull_request(
    base_url: str,
    token: str,
    repository: str,
    pull_number: int,
) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
        result = await request_json(
            client,
            "GET",
            f"{_api_root(base_url)}/repos/{_repo_path(repository)}/pulls/{pull_number}",
            service=SERVICE,
            headers=github_headers(token),
        )
    return result  # type: ignore[no-any-return]


async def list_pull_request_reviews(
    base_url: str,
    token: str,
    repository: str,
    pull_number: int,
) -> list[dict[str, Any]]:
    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
        result = await request_json(
            client,
            "GET",
            f"{_api_root(base_url)}/repos/{_repo_path(repository)}/pulls/{pull_number}/reviews",
            service=SERVICE,
            headers=github_headers(token),
            params={"per_page": 100},
        )
    return result if isinstance(result, list) else []


async def list_issue_comments(
    base_url: str,
    token: str,
    repository: str,
    issue_number: int,
) -> list[dict[str, Any]]:
    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
        result = await request_json(
            client,
            "GET",
            f"{_api_root(base_url)}/repos/{_repo_path(repository)}/issues/{issue_number}/comments",
            service=SERVICE,
            headers=github_headers(token),
            params={"per_page": 100},
        )
    return result if isinstance(result, list) else []


async def create_pull_request(
    base_url: str,
    token: str,
    repository: str,
    *,
    head: str,
    base: str,
    title: str,
    body: str,
    draft: bool,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "title": title,
        "head": head,
        "base": base,
        "body": body,
        "draft": draft,
    }
    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
        result = await request_json(
            client,
            "POST",
            f"{_api_root(base_url)}/repos/{_repo_path(repository)}/pulls",
            service=SERVICE,
            headers=github_headers(token),
            json=payload,
        )
    return result  # type: ignore[no-any-return]


async def list_pull_request_files(
    base_url: str,
    token: str,
    repository: str,
    pull_number: int,
) -> list[dict[str, Any]]:
    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
        result = await request_json(
            client,
            "GET",
            f"{_api_root(base_url)}/repos/{_repo_path(repository)}/pulls/{pull_number}/files",
            service=SERVICE,
            headers=github_headers(token),
            params={"per_page": 100},
        )
    return result if isinstance(result, list) else []


async def compare_refs(
    base_url: str,
    token: str,
    repository: str,
    base_ref: str,
    head_ref: str,
) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
        result = await request_json(
            client,
            "GET",
            (
                f"{_api_root(base_url)}/repos/{_repo_path(repository)}/compare/"
                f"{_ref_path(base_ref)}...{_ref_path(head_ref)}"
            ),
            service=SERVICE,
            headers=github_headers(token),
        )
    return result  # type: ignore[no-any-return]


async def get_workflow_run(
    base_url: str,
    token: str,
    repository: str,
    run_id: int,
) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
        result = await request_json(
            client,
            "GET",
            f"{_api_root(base_url)}/repos/{_repo_path(repository)}/actions/runs/{run_id}",
            service=SERVICE,
            headers=github_headers(token),
        )
    return result  # type: ignore[no-any-return]


async def list_workflow_run_jobs(
    base_url: str,
    token: str,
    repository: str,
    run_id: int,
) -> list[dict[str, Any]]:
    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
        result = await request_json(
            client,
            "GET",
            f"{_api_root(base_url)}/repos/{_repo_path(repository)}/actions/runs/{run_id}/jobs",
            service=SERVICE,
            headers=github_headers(token),
            params={"per_page": 100},
        )
    jobs = result.get("jobs", []) if isinstance(result, dict) else []
    return jobs if isinstance(jobs, list) else []


async def get_actions_job_log(
    base_url: str,
    token: str,
    repository: str,
    job_id: int,
) -> str:
    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT, follow_redirects=True) as client:
        return await request_text(
            client,
            "GET",
            f"{_api_root(base_url)}/repos/{_repo_path(repository)}/actions/jobs/{job_id}/logs",
            service=SERVICE,
            headers=github_headers(token, accept="text/plain"),
        )
