from __future__ import annotations

import pytest

from anvil.exceptions import SecretNotFoundError
from anvil.keychain import keychain_get


def test_env_var_resolution_normalizes_name(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANVIL_SENTRY_EXAMPLE", "from-env")
    assert keychain_get("anvil/sentry/example") == "from-env"


def test_env_var_empty_falls_through(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANVIL_NOPE", "")
    # On non-darwin/no-tools systems, we expect a SecretNotFoundError.
    monkeypatch.setattr("platform.system", lambda: "unknown")
    monkeypatch.setattr("shutil.which", lambda _: None)
    with pytest.raises(SecretNotFoundError):
        keychain_get("anvil/nope")
