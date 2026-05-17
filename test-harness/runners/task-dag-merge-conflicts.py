#!/usr/bin/env python3
"""Runner for the 'task-dag-merge-conflicts' scenario.

Synthetic-fixture target: simulates two sub-branches touching the
same file with incompatible content; merge under
``conflict_strategy: fail`` surfaces the conflict. See
``test-harness/lib/synthetic_drivers.SyntheticTaskDagMergeConflictsObserver``.
"""
from __future__ import annotations

import sys
from pathlib import Path

_LIB = Path(__file__).resolve().parents[1] / "lib"
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

from scenario_runner import cli_main  # noqa: E402
from synthetic_drivers import SyntheticTaskDagMergeConflictsObserver  # noqa: E402


SCENARIO_ID = 'task-dag-merge-conflicts'


_observer = SyntheticTaskDagMergeConflictsObserver()


def observe(phase_name, inputs, fixture, diagnostics):
    return _observer(phase_name, inputs, fixture, diagnostics)


if __name__ == "__main__":
    raise SystemExit(cli_main(SCENARIO_ID, observe))
