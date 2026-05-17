#!/usr/bin/env python3
"""Runner for the 'task-dag-stale-takeover' scenario.

Synthetic-fixture target: drives the CAS-by-re-read claim handshake
against a pre-locked issue with a stale ``status_ts`` via
``test-harness/lib/synthetic_drivers.SyntheticTaskDagStaleTakeoverObserver``.
"""
from __future__ import annotations

import sys
from pathlib import Path

_LIB = Path(__file__).resolve().parents[1] / "lib"
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

from scenario_runner import cli_main  # noqa: E402
from synthetic_drivers import SyntheticTaskDagStaleTakeoverObserver  # noqa: E402


SCENARIO_ID = 'task-dag-stale-takeover'


_observer = SyntheticTaskDagStaleTakeoverObserver()


def observe(phase_name, inputs, fixture, diagnostics):
    return _observer(phase_name, inputs, fixture, diagnostics)


if __name__ == "__main__":
    raise SystemExit(cli_main(SCENARIO_ID, observe))
