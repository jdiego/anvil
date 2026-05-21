from __future__ import annotations

import anvil.config as anvil_config
import anvil.github.tools as anvil_github_tools
import suap_mcp.config as compat_config
import suap_mcp.exceptions as compat_exceptions
import suap_mcp.github.tools as compat_github_tools
from anvil.exceptions import ConfigError


def test_legacy_package_imports_alias_anvil_modules() -> None:
    assert compat_config is anvil_config
    assert compat_github_tools is anvil_github_tools
    assert vars(compat_exceptions)["ConfigError"] is ConfigError
