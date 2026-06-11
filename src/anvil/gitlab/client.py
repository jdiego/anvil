from __future__ import annotations

from typing import Any

import httpx

from anvil.http import DEFAULT_TIMEOUT, request_json, request_text

SERVICE = "gitlab"


def gitlab_headers(token: str) -> dict[str, str]:
    return {
        "PRIVATE-TOKEN": token,
        "Accept": "application/json",
    }


def _api_root(base_url: str) -> str:
    return f"{base_url.rstrip('/')}/api/v4"


def _encode_project(project_path: str) -> str:
    return project_path.replace("/", "%2F")


async def get_current_user(base_url: str, token: str) -> dict[str, Any]:
    """Return the GitLab user associated with the token. Used by ``doctor``."""

    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
        result = await request_json(
            client,
            "GET",
            f"{_api_root(base_url)}/user",
            service=SERVICE,
            headers=gitlab_headers(token),
        )
    return result  # type: ignore[no-any-return]


async def create_merge_request(
    base_url: str,
    token: str,
    project_path: str,
    source_branch: str,
    target_branch: str,
    title: str,
    description: str,
    remove_source_branch: bool = False,
) -> dict[str, Any]:
    payload = {
        "source_branch": source_branch,
        "target_branch": target_branch,
        "title": title,
        "description": description,
        "remove_source_branch": remove_source_branch,
    }

    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
        result = await request_json(
            client,
            "POST",
            f"{_api_root(base_url)}/projects/{_encode_project(project_path)}/merge_requests",
            service=SERVICE,
            headers=gitlab_headers(token),
            json=payload,
        )
    return result  # type: ignore[no-any-return]


async def get_pipeline(
    base_url: str, token: str, project_path: str, pipeline_id: int
) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
        result = await request_json(
            client,
            "GET",
            f"{_api_root(base_url)}/projects/{_encode_project(project_path)}/pipelines/{pipeline_id}",
            service=SERVICE,
            headers=gitlab_headers(token),
        )
    return result  # type: ignore[no-any-return]


async def get_latest_pipeline_for_ref(
    base_url: str,
    token: str,
    project_path: str,
    ref: str,
) -> dict[str, Any] | None:
    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
        result = await request_json(
            client,
            "GET",
            f"{_api_root(base_url)}/projects/{_encode_project(project_path)}/pipelines",
            service=SERVICE,
            headers=gitlab_headers(token),
            params={"ref": ref, "per_page": 1, "order_by": "id", "sort": "desc"},
        )
    pipelines = result if isinstance(result, list) else []
    return pipelines[0] if pipelines else None


async def list_pipeline_jobs(
    base_url: str,
    token: str,
    project_path: str,
    pipeline_id: int,
) -> list[dict[str, Any]]:
    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
        result = await request_json(
            client,
            "GET",
            f"{_api_root(base_url)}/projects/{_encode_project(project_path)}/pipelines/{pipeline_id}/jobs",
            service=SERVICE,
            headers=gitlab_headers(token),
            params={"per_page": 100},
        )
    return result if isinstance(result, list) else []


async def get_job_trace(
    base_url: str,
    token: str,
    project_path: str,
    job_id: int,
) -> str:
    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
        return await request_text(
            client,
            "GET",
            f"{_api_root(base_url)}/projects/{_encode_project(project_path)}/jobs/{job_id}/trace",
            service=SERVICE,
            headers=gitlab_headers(token),
        )


async def list_merge_requests(
    base_url: str,
    token: str,
    project_path: str,
    *,
    state: str,
    author: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    params: dict[str, Any] = {
        "state": state,
        "per_page": limit,
        "order_by": "updated_at",
        "sort": "desc",
    }
    if author:
        params["author_username"] = author

    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
        result = await request_json(
            client,
            "GET",
            f"{_api_root(base_url)}/projects/{_encode_project(project_path)}/merge_requests",
            service=SERVICE,
            headers=gitlab_headers(token),
            params=params,
        )
    return result if isinstance(result, list) else []


async def compare_refs(
    base_url: str,
    token: str,
    project_path: str,
    from_ref: str,
    to_ref: str,
) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
        result = await request_json(
            client,
            "GET",
            f"{_api_root(base_url)}/projects/{_encode_project(project_path)}/repository/compare",
            service=SERVICE,
            headers=gitlab_headers(token),
            params={"from": from_ref, "to": to_ref},
        )
    return result  # type: ignore[no-any-return]


async def get_merge_request(
    base_url: str,
    token: str,
    project_path: str,
    mr_iid: int,
) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
        result = await request_json(
            client,
            "GET",
            f"{_api_root(base_url)}/projects/{_encode_project(project_path)}/merge_requests/{mr_iid}",
            service=SERVICE,
            headers=gitlab_headers(token),
        )
    return result  # type: ignore[no-any-return]


async def get_merge_request_approvals(
    base_url: str,
    token: str,
    project_path: str,
    mr_iid: int,
) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
        result = await request_json(
            client,
            "GET",
            (
                f"{_api_root(base_url)}/projects/{_encode_project(project_path)}"
                f"/merge_requests/{mr_iid}/approvals"
            ),
            service=SERVICE,
            headers=gitlab_headers(token),
        )
    return result  # type: ignore[no-any-return]


async def list_merge_request_discussions(
    base_url: str,
    token: str,
    project_path: str,
    mr_iid: int,
    *,
    per_page: int = 100,
) -> list[dict[str, Any]]:
    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
        result = await request_json(
            client,
            "GET",
            (
                f"{_api_root(base_url)}/projects/{_encode_project(project_path)}"
                f"/merge_requests/{mr_iid}/discussions"
            ),
            service=SERVICE,
            headers=gitlab_headers(token),
            params={"per_page": per_page},
        )
    return result if isinstance(result, list) else []


async def get_merge_request_changes(
    base_url: str,
    token: str,
    project_path: str,
    mr_iid: int,
) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
        result = await request_json(
            client,
            "GET",
            f"{_api_root(base_url)}/projects/{_encode_project(project_path)}/merge_requests/{mr_iid}/changes",
            service=SERVICE,
            headers=gitlab_headers(token),
        )
    return result  # type: ignore[no-any-return]


async def retry_job(
    base_url: str,
    token: str,
    project_path: str,
    job_id: int,
) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
        result = await request_json(
            client,
            "POST",
            f"{_api_root(base_url)}/projects/{_encode_project(project_path)}/jobs/{job_id}/retry",
            service=SERVICE,
            headers=gitlab_headers(token),
        )
    return result  # type: ignore[no-any-return]


async def cancel_pipeline(
    base_url: str,
    token: str,
    project_path: str,
    pipeline_id: int,
) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
        result = await request_json(
            client,
            "POST",
            f"{_api_root(base_url)}/projects/{_encode_project(project_path)}/pipelines/{pipeline_id}/cancel",
            service=SERVICE,
            headers=gitlab_headers(token),
        )
    return result  # type: ignore[no-any-return]


async def post_merge_request_note(
    base_url: str,
    token: str,
    project_path: str,
    mr_iid: int,
    body: str,
) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
        result = await request_json(
            client,
            "POST",
            f"{_api_root(base_url)}/projects/{_encode_project(project_path)}/merge_requests/{mr_iid}/notes",
            service=SERVICE,
            headers=gitlab_headers(token),
            json={"body": body},
        )
    return result  # type: ignore[no-any-return]


async def post_merge_request_discussion(
    base_url: str,
    token: str,
    project_path: str,
    mr_iid: int,
    payload: dict[str, Any],
) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
        result = await request_json(
            client,
            "POST",
            f"{_api_root(base_url)}/projects/{_encode_project(project_path)}/merge_requests/{mr_iid}/discussions",
            service=SERVICE,
            headers=gitlab_headers(token),
            json=payload,
        )
    return result  # type: ignore[no-any-return]


async def approve_merge_request(
    base_url: str,
    token: str,
    project_path: str,
    mr_iid: int,
) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
        result = await request_json(
            client,
            "POST",
            f"{_api_root(base_url)}/projects/{_encode_project(project_path)}/merge_requests/{mr_iid}/approve",
            service=SERVICE,
            headers=gitlab_headers(token),
        )
    return result  # type: ignore[no-any-return]


async def update_merge_request(
    base_url: str,
    token: str,
    project_path: str,
    mr_iid: int,
    payload: dict[str, Any],
) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
        result = await request_json(
            client,
            "PUT",
            f"{_api_root(base_url)}/projects/{_encode_project(project_path)}/merge_requests/{mr_iid}",
            service=SERVICE,
            headers=gitlab_headers(token),
            json=payload,
        )
    return result  # type: ignore[no-any-return]


async def trigger_pipeline(
    base_url: str,
    token: str,
    project_path: str,
    ref: str,
    variables: dict[str, str],
) -> dict[str, Any]:
    payload = {
        "ref": ref,
        "variables": [{"key": key, "value": value} for key, value in variables.items()],
    }
    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
        result = await request_json(
            client,
            "POST",
            f"{_api_root(base_url)}/projects/{_encode_project(project_path)}/pipeline",
            service=SERVICE,
            headers=gitlab_headers(token),
            json=payload,
        )
    return result  # type: ignore[no-any-return]


async def create_branch(
    base_url: str,
    token: str,
    project_path: str,
    branch_name: str,
    ref: str,
) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
        result = await request_json(
            client,
            "POST",
            f"{_api_root(base_url)}/projects/{_encode_project(project_path)}/repository/branches",
            service=SERVICE,
            headers=gitlab_headers(token),
            json={"branch": branch_name, "ref": ref},
        )
    return result  # type: ignore[no-any-return]
