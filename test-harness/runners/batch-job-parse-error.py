#!/usr/bin/env python3
"""Runner for the 'batch-job-parse-error' scenario.

Synthetic-fixture target: drives the real ``handler.run`` function in
``.agent/scripts/handler.py`` against an in-memory GitHub client (see
``test-harness/lib/synthetic_drivers.py``). Posts a malformed envelope
and observes the terminal ``parse_error`` envelope the handler writes
back.
"""
from __future__ import annotations

import sys
from pathlib import Path

_LIB = Path(__file__).resolve().parents[1] / "lib"
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

from scenario_runner import cli_main  # noqa: E402
from synthetic_drivers import SyntheticBatchJobErrorObserver  # noqa: E402


SCENARIO_ID = 'batch-job-parse-error'


_observer = SyntheticBatchJobErrorObserver(error_mode="parse_error")


def observe(phase_name, inputs, fixture, diagnostics):
    return _observer(phase_name, inputs, fixture, diagnostics)


if __name__ == "__main__":
    raise SystemExit(cli_main(SCENARIO_ID, observe))
