#!/usr/bin/env python3
"""Runner for the 'multi-scenario-soak' scenario.

See test-harness/scenarios/multi-scenario-soak.yml for the scenario spec and
test-harness/lib/scenario_runner.py for the generic phase loop. This
runner uses the synthetic-fixture observer; phases whose assertions
require live skill execution against real GitHub are marked
`skipped` with reason 'requires-live-skill-execution'.
"""
from __future__ import annotations

import sys
from pathlib import Path

_LIB = Path(__file__).resolve().parents[1] / "lib"
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

from scenario_runner import cli_main  # noqa: E402
from synthetic_observe import generic_observe  # noqa: E402


SCENARIO_ID = 'multi-scenario-soak'

# `expected_keys` per phase, used by generic_observe to decide whether
# any synthetic-mode assertion can be made for a given phase. If none of
# the phase's expected keys is in the synthetic catalogue, the phase
# is marked `skipped` rather than `failed`.
PHASE_EXPECTED_KEYS = {'setup': ['issue_numbers_present_count'], 'fanout': ['no_shared_branch_names', 'orchestrators_running'], 'merge': ['all_orchestrators_completed', 'prs_opened_count'], 'verify': ['no_cross_contamination', 'no_shared_run_dirs', 'prs_merged_count']}


def observe(phase_name, inputs, fixture, diagnostics):
    return generic_observe(
        phase_name,
        inputs,
        fixture,
        diagnostics,
        expected_keys=PHASE_EXPECTED_KEYS.get(phase_name, []),
    )


if __name__ == "__main__":
    raise SystemExit(cli_main(SCENARIO_ID, observe))
