"""Pytest bootstrap: ensure the repo root is importable so ``import parley`` works.

Parley is run as a source tree (not installed into the venv), so without this
the offline test modules cannot import the pure ``parley`` package. Adding the
repo root to ``sys.path`` keeps the tests dependency-free (no editable install
or band SDK required).
"""

from __future__ import annotations

import os
import sys

_REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
