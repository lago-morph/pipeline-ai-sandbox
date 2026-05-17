#!/usr/bin/env python3
"""Runner for the 'onboarding-resume-mid-interview' scenario.

Synthetic-fixture target: pre-write a partial dialog file, then
resume the interview from the next unanswered question. See
``test-harness/lib/synthetic_drivers.SyntheticOnboardingObserver``.
"""
from __future__ import annotations

import sys
from pathlib import Path

_LIB = Path(__file__).resolve().parents[1] / "lib"
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

from scenario_runner import cli_main  # noqa: E402
from synthetic_drivers import SyntheticOnboardingObserver  # noqa: E402


SCENARIO_ID = 'onboarding-resume-mid-interview'


_observer = SyntheticOnboardingObserver(mode="resume")


def observe(phase_name, inputs, fixture, diagnostics):
    return _observer(phase_name, inputs, fixture, diagnostics)


if __name__ == "__main__":
    raise SystemExit(cli_main(SCENARIO_ID, observe))
