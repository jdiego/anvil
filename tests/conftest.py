from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
import yaml


@pytest.fixture
def fake_contexts_yaml(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Write a contexts.yaml in tmp and point the module at it."""

    data = {
        "contexts": {
            "example": {
                "sentry": {
                    "base_url": "https://sentry.example.com",
                    "token_keychain": "anvil/sentry/example",
                },
                "gitlab": {
                    "base_url": "https://gitlab.example.com",
                    "token_keychain": "anvil/gitlab/example",
                },
            },
        }
    }
    path = tmp_path / "contexts.yaml"
    path.write_text(yaml.safe_dump(data))

    monkeypatch.setattr("anvil.config.CONFIG_PATH", path)
    return path


@pytest.fixture
def env_secrets(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Provide secrets via environment variables (the first resolution step)."""

    monkeypatch.setenv("ANVIL_SENTRY_EXAMPLE", "sentry-token")
    monkeypatch.setenv("ANVIL_GITLAB_EXAMPLE", "gitlab-token")
    yield
