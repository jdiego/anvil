from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
import respx
import yaml
from httpx import Response

from anvil.github.models import (
    CompareRefsInput,
    CreatePullRequestInput,
    GetActionsJobLogInput,
    GetPullRequestDiffInput,
    GetPullRequestInput,
    GetWorkflowRunStatusInput,
    ListPullRequestsInput,
    ResolveGitHubContextInput,
)
from anvil.github.tools import (
    compare_github_refs,
    create_github_pull_request,
    get_github_actions_job_log,
    get_github_pull_request,
    get_github_pull_request_diff,
    get_github_workflow_run_status,
    list_github_pull_requests,
    resolve_github_context,
)


@pytest.fixture
def github_contexts_yaml(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    data = {
        "contexts": {
            "github-example": {
                "sentry": {
                    "base_url": "https://sentry.example.com",
                    "token_keychain": "anvil/sentry/example",
                },
                "gitlab": {
                    "base_url": "https://gitlab.example.com",
                    "token_keychain": "anvil/gitlab/example",
                },
                "github": {
                    "base_url": "https://api.github.com",
                    "token_keychain": "anvil/github/example",
                },
            },
        }
    }
    path = tmp_path / "contexts.yaml"
    path.write_text(yaml.safe_dump(data))
    monkeypatch.setattr("anvil.config.CONFIG_PATH", path)
    return path


@pytest.fixture
def github_env_secret(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("ANVIL_GITHUB_EXAMPLE", "github-token")
    yield


@pytest.mark.asyncio
async def test_resolve_github_context(github_contexts_yaml: Path) -> None:
    output = await resolve_github_context(
        ResolveGitHubContextInput(url="https://api.github.com/repos/owner/repo")
    )

    assert output.context == "github-example"
    assert output.github_base_url == "https://api.github.com"


@pytest.mark.asyncio
@respx.mock
async def test_list_github_pull_requests_returns_summaries(
    github_contexts_yaml: Path,
    github_env_secret: None,
) -> None:
    route = respx.get("https://api.github.com/repos/owner/repo/pulls").mock(
        return_value=Response(
            200,
            json=[
                {
                    "number": 7,
                    "title": "feat: add github tools",
                    "state": "open",
                    "draft": False,
                    "user": {"login": "alice"},
                    "head": {"ref": "feat/github"},
                    "base": {"ref": "main"},
                    "html_url": "https://github.com/owner/repo/pull/7",
                    "updated_at": "2026-05-21T10:00:00Z",
                }
            ],
        )
    )

    output = await list_github_pull_requests(
        ListPullRequestsInput(
            context_url="https://api.github.com/repos/owner/repo",
            repository="owner/repo",
            state="open",
            base="main",
        )
    )

    assert output.context == "github-example"
    assert output.pull_requests[0].number == 7
    assert output.pull_requests[0].user_login == "alice"
    assert route.calls.last.request.headers["Authorization"] == "Bearer github-token"
    assert route.calls.last.request.url.params["base"] == "main"


@pytest.mark.asyncio
@respx.mock
async def test_list_github_pull_requests_applies_limit_and_flags_truncation(
    github_contexts_yaml: Path,
    github_env_secret: None,
) -> None:
    route = respx.get("https://api.github.com/repos/owner/repo/pulls").mock(
        return_value=Response(
            200,
            json=[
                {"number": i, "title": f"feat {i}", "state": "open"} for i in range(5)
            ],
        )
    )

    output = await list_github_pull_requests(
        ListPullRequestsInput(
            context_url="https://api.github.com/repos/owner/repo",
            repository="owner/repo",
            limit=2,
        )
    )

    assert len(output.pull_requests) == 2
    assert output.returned == 2
    assert output.total == 5
    assert output.truncated is True
    assert any("limit" in warning.lower() for warning in output.warnings)
    # `limit` must reach GitHub as per_page so callers can fetch more than the old 50.
    assert route.calls.last.request.url.params["per_page"] == "2"


@pytest.mark.asyncio
@respx.mock
async def test_get_github_pull_request_diff_returns_bounded_patches(
    github_contexts_yaml: Path,
    github_env_secret: None,
) -> None:
    respx.get("https://api.github.com/repos/owner/repo/pulls/7").mock(
        return_value=Response(
            200,
            json={
                "number": 7,
                "title": "feat: add github tools",
                "state": "open",
                "draft": False,
                "head": {"ref": "feat/github", "sha": "headsha"},
                "base": {"ref": "main", "sha": "basesha"},
                "html_url": "https://github.com/owner/repo/pull/7",
            },
        )
    )
    respx.get("https://api.github.com/repos/owner/repo/pulls/7/files").mock(
        return_value=Response(
            200,
            json=[
                {
                    "filename": "src/app.py",
                    "status": "modified",
                    "additions": 3,
                    "deletions": 1,
                    "changes": 4,
                    "patch": "\n".join([f"line {i}" for i in range(30)]),
                },
                {
                    "filename": "README.md",
                    "status": "modified",
                    "additions": 1,
                    "deletions": 0,
                    "changes": 1,
                    "patch": "doc line",
                },
            ],
        )
    )

    output = await get_github_pull_request_diff(
        GetPullRequestDiffInput(
            context_url="https://api.github.com/repos/owner/repo",
            repository="owner/repo",
            pull_number=7,
            max_files=1,
            max_lines_per_file=20,
        )
    )

    assert output.pull_number == 7
    assert output.total_files == 2
    assert output.returned_files == 1
    assert output.files_truncated is True
    assert output.files[0].filename == "src/app.py"
    assert output.files[0].returned_lines == 20
    assert output.files[0].truncated is True


@pytest.mark.asyncio
@respx.mock
async def test_compare_github_refs_returns_counts(
    github_contexts_yaml: Path,
    github_env_secret: None,
) -> None:
    respx.get("https://api.github.com/repos/owner/repo/compare/main...feature").mock(
        return_value=Response(
            200,
            json={
                "status": "ahead",
                "ahead_by": 2,
                "behind_by": 0,
                "total_commits": 2,
                "commits": [
                    {"commit": {"message": "feat: one\n\nbody"}},
                    {"commit": {"message": "fix: two"}},
                ],
                "files": [{"filename": "src/app.py"}],
            },
        )
    )

    output = await compare_github_refs(
        CompareRefsInput(
            context_url="https://api.github.com/repos/owner/repo",
            repository="owner/repo",
            base_ref="main",
            head_ref="feature",
        )
    )

    assert output.ahead_by == 2
    assert output.files_changed == 1
    assert output.commit_messages == ["feat: one\n\nbody", "fix: two"]


@pytest.mark.asyncio
@respx.mock
async def test_get_github_workflow_run_status_returns_jobs(
    github_contexts_yaml: Path,
    github_env_secret: None,
) -> None:
    respx.get("https://api.github.com/repos/owner/repo/actions/runs/123").mock(
        return_value=Response(
            200,
            json={
                "id": 123,
                "name": "CI",
                "status": "completed",
                "conclusion": "failure",
                "event": "pull_request",
                "head_branch": "feature",
                "head_sha": "abc",
                "html_url": "https://github.com/owner/repo/actions/runs/123",
            },
        )
    )
    respx.get("https://api.github.com/repos/owner/repo/actions/runs/123/jobs").mock(
        return_value=Response(
            200,
            json={
                "jobs": [
                    {
                        "id": 456,
                        "name": "pytest",
                        "status": "completed",
                        "conclusion": "failure",
                        "html_url": "https://github.com/owner/repo/actions/jobs/456",
                    },
                    {
                        "id": 457,
                        "name": "ruff",
                        "status": "completed",
                        "conclusion": "success",
                    },
                ]
            },
        )
    )

    output = await get_github_workflow_run_status(
        GetWorkflowRunStatusInput(
            context_url="https://api.github.com/repos/owner/repo",
            repository="owner/repo",
            run_id=123,
        )
    )

    assert output.run.id == 123
    assert len(output.jobs) == 2
    assert [job.id for job in output.failed_jobs] == [456]


@pytest.mark.asyncio
@respx.mock
async def test_get_github_actions_job_log_returns_tail(
    github_contexts_yaml: Path,
    github_env_secret: None,
) -> None:
    respx.get("https://api.github.com/repos/owner/repo/actions/jobs/456/logs").mock(
        return_value=Response(200, text="line1\nline2\nline3\n")
    )

    output = await get_github_actions_job_log(
        GetActionsJobLogInput(
            context_url="https://api.github.com/repos/owner/repo",
            repository="owner/repo",
            job_id=456,
            tail=2,
        )
    )

    assert output.log_tail == "line2\nline3"
    assert output.returned_lines == 2
    assert output.truncated is True


@pytest.mark.asyncio
async def test_create_github_pull_request_dry_run_does_not_call_github(
    github_contexts_yaml: Path,
    github_env_secret: None,
) -> None:
    with respx.mock(assert_all_called=False) as mock:
        route = mock.post("https://api.github.com/repos/owner/repo/pulls")

        output = await create_github_pull_request(
            CreatePullRequestInput(
                context_url="https://api.github.com/repos/owner/repo",
                repository="owner/repo",
                head="fix/sentry-42",
                title="fix: handle missing payload field",
            )
        )

    assert output.dry_run is True
    assert output.number is None
    assert output.html_url is None
    assert output.title == "fix: handle missing payload field"
    assert not route.called


@pytest.mark.asyncio
@respx.mock
async def test_create_github_pull_request_creates_pr_when_confirmed(
    github_contexts_yaml: Path,
    github_env_secret: None,
) -> None:
    route = respx.post("https://api.github.com/repos/owner/repo/pulls").mock(
        return_value=Response(
            201,
            json={
                "number": 42,
                "title": "fix: handle missing payload field",
                "html_url": "https://github.com/owner/repo/pull/42",
                "draft": False,
            },
        )
    )

    output = await create_github_pull_request(
        CreatePullRequestInput(
            context_url="https://api.github.com/repos/owner/repo",
            repository="owner/repo",
            head="fix/sentry-42",
            base="main",
            title="fix: handle missing payload field",
            body="Root cause, fix, and test plan.",
            confirm=True,
        )
    )

    assert output.dry_run is False
    assert output.number == 42
    assert str(output.html_url) == "https://github.com/owner/repo/pull/42"
    assert output.title == "fix: handle missing payload field"

    sent = json.loads(route.calls.last.request.content)
    assert sent["head"] == "fix/sentry-42"
    assert sent["base"] == "main"
    assert sent["title"] == "fix: handle missing payload field"
    assert sent["draft"] is False
    assert route.calls.last.request.headers["Authorization"] == "Bearer github-token"


@pytest.mark.asyncio
@respx.mock
async def test_get_github_pull_request_summarizes_reviews_and_comments(
    github_contexts_yaml: Path,
    github_env_secret: None,
) -> None:
    respx.get("https://api.github.com/repos/owner/repo/pulls/7").mock(
        return_value=Response(
            200,
            json={
                "number": 7,
                "title": "feat: add github tools",
                "state": "open",
                "draft": False,
                "merged": False,
                "user": {"login": "author"},
                "head": {"ref": "feat/github"},
                "base": {"ref": "main"},
                "html_url": "https://github.com/owner/repo/pull/7",
                "mergeable": True,
                "mergeable_state": "clean",
                "requested_reviewers": [{"login": "carol"}],
            },
        )
    )
    respx.get("https://api.github.com/repos/owner/repo/pulls/7/reviews").mock(
        return_value=Response(
            200,
            json=[
                {"user": {"login": "bob"}, "state": "CHANGES_REQUESTED", "submitted_at": "t1"},
                {"user": {"login": "bob"}, "state": "APPROVED", "submitted_at": "t2"},
                {"user": {"login": "dave"}, "state": "COMMENTED", "submitted_at": "t3"},
            ],
        )
    )
    respx.get("https://api.github.com/repos/owner/repo/issues/7/comments").mock(
        return_value=Response(
            200,
            json=[
                {"id": 1, "user": {"login": "bob"}, "body": "old", "created_at": "t1"},
                {"id": 2, "user": {"login": "carol"}, "body": "newer", "created_at": "t2"},
            ],
        )
    )

    output = await get_github_pull_request(
        GetPullRequestInput(
            context_url="https://api.github.com/repos/owner/repo",
            repository="owner/repo",
            pull_number=7,
            max_comments=1,
        )
    )

    assert output.number == 7
    assert output.mergeable_state == "clean"
    # bob's later APPROVED overrides the earlier CHANGES_REQUESTED; dave (COMMENTED) is dropped.
    assert output.approved_by == ["bob"]
    assert output.changes_requested_by == []
    assert {r.user_login for r in output.reviews} == {"bob"}
    # An outstanding requested reviewer keeps the decision at review_required.
    assert output.requested_reviewers == ["carol"]
    assert output.review_decision == "review_required"
    assert output.total_comments == 2
    assert output.comments_truncated is True
    assert [c.id for c in output.comments] == [2]


@pytest.mark.asyncio
@respx.mock
async def test_get_github_pull_request_skips_comments_when_max_zero(
    github_contexts_yaml: Path,
    github_env_secret: None,
) -> None:
    respx.get("https://api.github.com/repos/owner/repo/pulls/7").mock(
        return_value=Response(
            200,
            json={"number": 7, "state": "open", "requested_reviewers": []},
        )
    )
    respx.get("https://api.github.com/repos/owner/repo/pulls/7/reviews").mock(
        return_value=Response(
            200,
            json=[{"user": {"login": "bob"}, "state": "APPROVED", "submitted_at": "t1"}],
        )
    )
    comments_route = respx.get("https://api.github.com/repos/owner/repo/issues/7/comments")

    output = await get_github_pull_request(
        GetPullRequestInput(
            context_url="https://api.github.com/repos/owner/repo",
            repository="owner/repo",
            pull_number=7,
            max_comments=0,
        )
    )

    assert output.approved_by == ["bob"]
    assert output.review_decision == "approved"
    assert output.comments == []
    assert not comments_route.called
