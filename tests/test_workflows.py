from __future__ import annotations

from pathlib import Path

import pytest
import respx
from httpx import Response

from anvil.workflows import (
    OpenFixMergeRequestFromSentryInput,
    open_fix_mr_from_sentry,
)


def _mock_sentry_issue() -> None:
    base = "https://sentry.example.com/api/0/issues/42"
    respx.get(f"{base}/").mock(
        return_value=Response(
            200,
            json={
                "id": "42",
                "shortId": "BACKEND-42",
                "title": "Boom",
                "culprit": "backend.foo",
                "level": "error",
                "status": "unresolved",
                "permalink": "https://sentry.example.com/issues/42/",
            },
        )
    )
    respx.get(f"{base}/events/").mock(
        return_value=Response(200, json=[{"id": "evt-1", "eventID": "evt-1"}])
    )


@pytest.mark.asyncio
@respx.mock
async def test_open_fix_mr_from_sentry_dry_run_does_not_create_branch(
    fake_contexts_yaml: Path,
    env_secrets: None,
) -> None:
    _mock_sentry_issue()
    branch_route = respx.post(
        "https://gitlab.example.com/api/v4/projects/group%2Fproject/repository/branches"
    ).mock(return_value=Response(201, json={"name": "fix/sentry-42"}))

    output = await open_fix_mr_from_sentry(
        OpenFixMergeRequestFromSentryInput(
            sentry_issue_url="https://sentry.example.com/issues/42/",
            context_url="https://gitlab.example.com/group/project",
            project_path="group/project",
            branch_name="fix/sentry-42",
            base_ref="main",
            confirm=False,
        )
    )

    assert output.dry_run is True
    assert output.branch_created is False
    assert output.issue.short_id == "BACKEND-42"
    assert "fix/sentry-42" in output.prompt
    assert branch_route.called is False


@pytest.mark.asyncio
@respx.mock
async def test_open_fix_mr_from_sentry_confirmed_creates_branch(
    fake_contexts_yaml: Path,
    env_secrets: None,
) -> None:
    _mock_sentry_issue()
    branch_route = respx.post(
        "https://gitlab.example.com/api/v4/projects/group%2Fproject/repository/branches"
    ).mock(return_value=Response(201, json={"name": "fix/sentry-42"}))

    output = await open_fix_mr_from_sentry(
        OpenFixMergeRequestFromSentryInput(
            sentry_issue_url="https://sentry.example.com/issues/42/",
            context_url="https://gitlab.example.com/group/project",
            project_path="group/project",
            branch_name="fix/sentry-42",
            base_ref="main",
            confirm=True,
        )
    )

    assert output.dry_run is False
    assert output.branch_created is True
    assert branch_route.called
    assert branch_route.calls.last.request.content == b'{"branch":"fix/sentry-42","ref":"main"}'
