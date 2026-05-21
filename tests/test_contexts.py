from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from anvil.contexts import load_contexts, resolve_context
from anvil.exceptions import ConfigError, ContextNotFoundError, InvalidInputError


def test_load_contexts_parses_yaml(fake_contexts_yaml: Path) -> None:
    contexts = load_contexts()
    assert "example" in contexts
    assert contexts["example"].sentry is not None
    assert contexts["example"].gitlab is not None
    assert contexts["example"].sentry.base_url == "https://sentry.example.com"
    assert contexts["example"].gitlab.token_keychain == "anvil/gitlab/example"


def test_resolve_context_matches_sentry_host(fake_contexts_yaml: Path) -> None:
    name, ctx = resolve_context("https://sentry.example.com/issues/42/")
    assert name == "example"
    assert ctx.gitlab is not None
    assert ctx.gitlab.base_url == "https://gitlab.example.com"


def test_resolve_context_matches_gitlab_host(fake_contexts_yaml: Path) -> None:
    name, _ = resolve_context("https://gitlab.example.com/group/project")
    assert name == "example"


def test_load_contexts_accepts_github_only_context(
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

    contexts = load_contexts()
    name, ctx = resolve_context("https://api.github.com/repos/owner/repo")

    assert contexts["github-only"].sentry is None
    assert contexts["github-only"].gitlab is None
    assert name == "github-only"
    assert ctx.github is not None


def test_load_contexts_rejects_context_without_services(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "contexts.yaml"
    path.write_text(yaml.safe_dump({"contexts": {"empty": {}}}))
    monkeypatch.setattr("anvil.config.CONFIG_PATH", path)

    with pytest.raises(ConfigError, match="no services configured"):
        load_contexts()


def test_resolve_context_unknown_host_raises(fake_contexts_yaml: Path) -> None:
    with pytest.raises(ContextNotFoundError):
        resolve_context("https://example.com/whatever")


def test_resolve_context_invalid_url_raises(fake_contexts_yaml: Path) -> None:
    with pytest.raises(InvalidInputError):
        resolve_context("not-a-url")
