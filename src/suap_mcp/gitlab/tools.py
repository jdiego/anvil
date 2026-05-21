from __future__ import annotations

import sys
from importlib import import_module

_module = import_module("anvil.gitlab.tools")
sys.modules[__name__] = _module
