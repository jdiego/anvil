from __future__ import annotations

import sys
from importlib import import_module

_module = import_module("anvil.github.models")
sys.modules[__name__] = _module
