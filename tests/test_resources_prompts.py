from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from anvil.prompts import review_sentry_issue
from anvil.resources import list_contexts_resource
from anvil.server import build_server


def test_list_contexts_resource_omits_secret_identifiers(fake_contexts_yaml: Path) -> None:
    result = list_contexts_resource()

    assert result == {
        "contexts": [
            {
                "name": "example",
                "sentry": {"base_url": "https://sentry.example.com"},
                "gitlab": {"base_url": "https://gitlab.example.com"},
            }
        ]
    }
    assert "token_keychain" not in repr(result)


def test_list_contexts_resource_omits_unconfigured_services(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "contexts.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "contexts": {
                    "github-only": {
                        "github": {
                            "base_url": "https://api.github.com",
                            "token_keychain": "anvil/github/example",
                        },
                    },
                },
            }
        )
    )
    monkeypatch.setattr("anvil.config.CONFIG_PATH", path)

    result = list_contexts_resource()

    assert result == {
        "contexts": [
            {
                "name": "github-only",
                "github": {"base_url": "https://api.github.com"},
            }
        ]
    }
    assert "token_keychain" not in repr(result)


def test_review_sentry_issue_prompt_mentions_expected_workflow() -> None:
    prompt = review_sentry_issue("https://sentry.example.com/issues/42/")

    assert "Call get_sentry_issue" in prompt
    assert "https://sentry.example.com/issues/42/" in prompt
    assert "Do not create a GitLab merge request" in prompt


@pytest.mark.asyncio
async def test_server_registers_contexts_resource_and_review_prompt(
    fake_contexts_yaml: Path,
) -> None:
    mcp = build_server()

    resources = await mcp.list_resources()
    prompts = await mcp.list_prompts()
    tools = await mcp.list_tools()

    contexts_resource = next(r for r in resources if str(r.uri) == "contexts://list")
    review_prompt = next(p for p in prompts if p.name == "review-sentry-issue")

    assert contexts_resource.mime_type == "application/json"
    assert contexts_resource.annotations is not None
    assert contexts_resource.annotations.model_dump(by_alias=True)["readOnlyHint"] is True
    assert review_prompt.arguments is not None
    assert [arg.name for arg in review_prompt.arguments] == ["issue_url"]
    assert {tool.name for tool in tools} >= {
        "resolve_github_context",
        "list_github_pull_requests",
        "get_github_pull_request_diff",
        "compare_github_refs",
        "get_github_workflow_run_status",
        "get_github_actions_job_log",
    }
