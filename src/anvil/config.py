from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from anvil.exceptions import ConfigError

CONFIG_PATH = Path.home() / ".config/anvil/contexts.yaml"


def load_config() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        raise ConfigError(
            f"Config not found: {CONFIG_PATH}. "
            "Copy contexts.yaml.example into this path and configure your contexts."
        )

    try:
        with CONFIG_PATH.open() as f:
            data = yaml.safe_load(f) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"Invalid YAML in {CONFIG_PATH}: {exc}") from exc

    if not isinstance(data, dict) or "contexts" not in data:
        raise ConfigError(f"{CONFIG_PATH} is missing the top-level 'contexts' key")

    if not isinstance(data["contexts"], dict) or not data["contexts"]:
        raise ConfigError(f"{CONFIG_PATH} has no contexts defined")

    return data
