"""Pytest configuration for the test-harness unit tests.

Inserts ``test-harness/lib`` on ``sys.path`` so tests can ``import``
the harness modules by their bare names (``envelopes``, ``state``,
``scenario_runner``, ...). Matches the way the runners themselves
import these modules from inside ``test-harness/runners/<id>.py``.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[2]
_LIB = _REPO_ROOT / "test-harness" / "lib"
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))


# Many of the lib modules use ``Path("test-harness/...")`` relative
# paths. Tests run with the repo root as cwd so those paths resolve.
os.chdir(_REPO_ROOT)
