#!/usr/bin/env python3
"""Runner for the 'batch-job-runner-pickup-timeout' scenario.

Synthetic-fixture target: posts a valid envelope but **does not run**
the handler — models the case where no batch-job-handler workflow
picked up the request. After ``pickup_timeout_s`` the observer writes
a synthetic terminal ``error`` envelope with
``error_kind: pickup_timeout`` (this is what the orchestrator-side
poll loop would do in production).
"""
from __future__ import annotations

import sys
from pathlib import Path

_LIB = Path(__file__).resolve().parents[1] / "lib"
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

from scenario_runner import cli_main  # noqa: E402
from synthetic_drivers import SyntheticBatchJobErrorObserver  # noqa: E402


SCENARIO_ID = 'batch-job-runner-pickup-timeout'


_observer = SyntheticBatchJobErrorObserver(
    error_mode="pickup_timeout",
    pickup_timeout_s=0.01,
)


def observe(phase_name, inputs, fixture, diagnostics):
    return _observer(phase_name, inputs, fixture, diagnostics)


if __name__ == "__main__":
    raise SystemExit(cli_main(SCENARIO_ID, observe))
