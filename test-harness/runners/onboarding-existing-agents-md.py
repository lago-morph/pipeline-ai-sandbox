#!/usr/bin/env python3
"""Runner for the 'onboarding-existing-agents-md' scenario.

See test-harness/scenarios/onboarding-existing-agents-md.yml for the scenario spec and
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


SCENARIO_ID = 'onboarding-existing-agents-md'

# `expected_keys` per phase, used by generic_observe to decide whether
# any synthetic-mode assertion can be made for a given phase. If none of
# the phase's expected keys is in the synthetic catalogue, the phase
# is marked `skipped` rather than `failed`.
PHASE_EXPECTED_KEYS = {'detect': ['agents_md_present', 'claude_md_present', 'onboarding_started', 'protocol_installed'], 'interview': ['dialog_file_present', 'questions_answered_min'], 'recommend': ['no_agents_md_edits_proposed', 'pointer_edit_proposed', 'recommendations_file_present'], 'apply': ['agents_md_body_unchanged', 'pointer_added_to_agents_md'], 'verify': ['claude_md_body_unchanged', 'meta_status']}


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
