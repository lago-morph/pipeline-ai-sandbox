#!/usr/bin/env python3
"""Runner for the 'batch-job-branch-sha-mismatch' scenario.

Synthetic-fixture target: posts a valid envelope whose ``commit_sha``
does not match the in-memory branch HEAD; the real
``.agent/scripts/handler.py`` then writes a terminal ``error`` envelope
with ``error_kind: branch_sha_mismatch``.
"""
from __future__ import annotations

import sys
from pathlib import Path

_LIB = Path(__file__).resolve().parents[1] / "lib"
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

from scenario_runner import cli_main  # noqa: E402
from synthetic_drivers import SyntheticBatchJobErrorObserver  # noqa: E402


SCENARIO_ID = 'batch-job-branch-sha-mismatch'


_observer = SyntheticBatchJobErrorObserver(error_mode="sha_mismatch")


def observe(phase_name, inputs, fixture, diagnostics):
    return _observer(phase_name, inputs, fixture, diagnostics)


if __name__ == "__main__":
    raise SystemExit(cli_main(SCENARIO_ID, observe))
