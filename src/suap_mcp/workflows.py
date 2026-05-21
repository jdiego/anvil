from __future__ import annotations

import sys
from importlib import import_module

_module = import_module("anvil.workflows")
sys.modules[__name__] = _module
