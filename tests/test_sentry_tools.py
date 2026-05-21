from __future__ import annotations

from pathlib import Path

import pytest
import respx
from httpx import Response

from anvil.exceptions import InvalidInputError
from anvil.sentry.models import (
    AssignSentryIssueInput,
    GetSentryIssueInput,
    GetSentryReleaseInput,
    LinkSentryIssueToMergeRequestInput,
    ListSentryIssuesInput,
    ResolveSentryContextInput,
    ResolveSentryIssueInput,
)
from anvil.sentry.tools import (
    assign_sentry_issue,
    get_sentry_issue,
    get_sentry_release,
    link_sentry_issue_to_mr,
    list_sentry_issues,
    resolve_sentry_context,
    resolve_sentry_issue,
)


@pytest.mark.asyncio
async def test_resolve_sentry_context(fake_contexts_yaml: Path) -> None:
    output = await resolve_sentry_context(
        ResolveSentryContextInput(url="https://sentry.example.com/")
    )
    assert output.context == "example"
    assert output.gitlab_base_url == "https://gitlab.example.com"


@pytest.mark.asyncio
@respx.mock
async def test_get_sentry_issue_returns_summary(
    fake_contexts_yaml: Path,
    env_secrets: None,
) -> None:
    base = "https://sentry.example.com/api/0/issues/42"
    respx.get(f"{base}/").mock(
        return_value=Response(
            200,
            json={
                "id": "42",
                "shortId": "PROJ-42",
                "title": "Boom",
                "culprit": "/foo/bar",
                "level": "error",
                "status": "unresolved",
                "permalink": "https://sentry.example.com/issues/42/",
                "count": "12",
                "userCount": 3,
                "firstSeen": "2026-05-01T00:00:00Z",
                "lastSeen": "2026-05-11T00:00:00Z",
            },
        )
    )
    respx.get(f"{base}/events/").mock(
        return_value=Response(200, json=[{"id": "evt-1", "eventID": "evt-1"}])
    )

    output = await get_sentry_issue(
        GetSentryIssueInput(url="https://sentry.example.com/issues/42/")
    )

    assert output.context == "example"
    assert output.issue.id == "42"
    assert output.issue.short_id == "PROJ-42"
    assert output.latest_event is not None
    assert output.latest_event["id"] == "evt-1"


@pytest.mark.asyncio
async def test_get_sentry_issue_rejects_url_without_issue_id(
    fake_contexts_yaml: Path,
    env_secrets: None,
) -> None:
    with pytest.raises(InvalidInputError):
        await get_sentry_issue(
            GetSentryIssueInput(url="https://sentry.example.com/some/other/path")
        )


@pytest.mark.asyncio
@respx.mock
async def test_list_sentry_issues_returns_summaries(
    fake_contexts_yaml: Path,
    env_secrets: None,
) -> None:
    route = respx.get("https://sentry.example.com/api/0/projects/example-org/backend/issues/").mock(
        return_value=Response(
            200,
            json=[
                {
                    "id": "42",
                    "shortId": "BACKEND-42",
                    "title": "Boom",
                    "status": "unresolved",
                }
            ],
        )
    )

    output = await list_sentry_issues(
        ListSentryIssuesInput(
            context_url="https://sentry.example.com/",
            organization_slug="example-org",
            project_slug="backend",
            query="is:unresolved level:error",
            environment="production",
            age="24h",
        )
    )

    assert output.context == "example"
    assert output.issues[0].short_id == "BACKEND-42"
    assert route.calls.last.request.url.params["query"] == "is:unresolved level:error age:24h"
    assert route.calls.last.request.url.params["environment"] == "production"


@pytest.mark.asyncio
async def test_assign_sentry_issue_dry_run_does_not_call_sentry(
    fake_contexts_yaml: Path,
    env_secrets: None,
) -> None:
    with respx.mock(assert_all_called=False) as mock:
        output = await assign_sentry_issue(
            AssignSentryIssueInput(
                context_url="https://sentry.example.com/",
                issue_id="42",
                assignee="user:alice@example.com",
                confirm=False,
            )
        )

    assert output.dry_run is True
    assert output.assigned_to == "user:alice@example.com"
    assert mock.calls.call_count == 0


@pytest.mark.asyncio
@respx.mock
async def test_assign_sentry_issue_confirmed_updates_issue(
    fake_contexts_yaml: Path,
    env_secrets: None,
) -> None:
    route = respx.put("https://sentry.example.com/api/0/issues/42/").mock(
        return_value=Response(
            200,
            json={"id": "42", "shortId": "BACKEND-42", "title": "Boom", "status": "unresolved"},
        )
    )

    output = await assign_sentry_issue(
        AssignSentryIssueInput(
            context_url="https://sentry.example.com/",
            issue_id="42",
            assignee="user:alice@example.com",
            confirm=True,
        )
    )

    assert output.issue is not None
    assert output.issue.id == "42"
    assert route.calls.last.request.content == b'{"assignedTo":"user:alice@example.com"}'


@pytest.mark.asyncio
@respx.mock
async def test_resolve_sentry_issue_confirmed_sets_status_details(
    fake_contexts_yaml: Path,
    env_secrets: None,
) -> None:
    route = respx.put("https://sentry.example.com/api/0/issues/42/").mock(
        return_value=Response(
            200,
            json={"id": "42", "shortId": "BACKEND-42", "title": "Boom", "status": "resolved"},
        )
    )

    output = await resolve_sentry_issue(
        ResolveSentryIssueInput(
            context_url="https://sentry.example.com/",
            issue_id="42",
            in_release="backend@1.2.3",
            confirm=True,
        )
    )

    assert output.issue is not None
    assert output.issue.status == "resolved"
    assert route.calls.last.request.content == (
        b'{"status":"resolved","statusDetails":{"inRelease":"backend@1.2.3"}}'
    )


@pytest.mark.asyncio
@respx.mock
async def test_link_sentry_issue_to_mr_confirmed_creates_comment(
    fake_contexts_yaml: Path,
    env_secrets: None,
) -> None:
    route = respx.post("https://sentry.example.com/api/0/issues/42/comments/").mock(
        return_value=Response(201, json={"id": "comment-1"})
    )

    output = await link_sentry_issue_to_mr(
        LinkSentryIssueToMergeRequestInput(
            context_url="https://sentry.example.com/",
            issue_id="42",
            mr_url="https://gitlab.example.com/group/project/-/merge_requests/7",
            confirm=True,
        )
    )

    assert output.comment_id == "comment-1"
    assert b"Fix merge request:" in route.calls.last.request.content


@pytest.mark.asyncio
@respx.mock
async def test_get_sentry_release_returns_summary(
    fake_contexts_yaml: Path,
    env_secrets: None,
) -> None:
    respx.get(
        "https://sentry.example.com/api/0/projects/example-org/backend/releases/backend@1.2.3/"
    ).mock(
        return_value=Response(
            200,
            json={
                "version": "backend@1.2.3",
                "dateCreated": "2026-05-13T00:00:00Z",
                "dateReleased": "2026-05-13T01:00:00Z",
                "newGroups": 2,
                "projects": [{"slug": "backend"}],
            },
        )
    )

    output = await get_sentry_release(
        GetSentryReleaseInput(
            context_url="https://sentry.example.com/",
            organization_slug="example-org",
            project_slug="backend",
            version="backend@1.2.3",
        )
    )

    assert output.release.version == "backend@1.2.3"
    assert output.release.projects == ["backend"]
