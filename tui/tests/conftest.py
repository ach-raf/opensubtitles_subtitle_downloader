"""Pytest config for the tui test-suite.

Ensures the project root is on sys.path so ``import tui...`` and the mocked
``library.*`` packages resolve regardless of how pytest is invoked from.
"""

from __future__ import annotations

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
