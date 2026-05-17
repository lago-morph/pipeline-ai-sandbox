#!/usr/bin/env python3
"""Runner for the 'task-dag-claim-and-plan' scenario.

See test-harness/scenarios/task-dag-claim-and-plan.yml for the scenario
spec and test-harness/lib/scenario_runner.py for the generic phase
loop.

Modes:

- ``--target synthetic-fixture`` (default in the absence of credentials):
  uses the synthetic observer; phases whose assertions require live skill
  execution are marked `skipped` with reason
  ``requires-live-skill-execution``.
- ``--target live-new-repo``: when ``GITHUB_TOKEN``/``GH_TOKEN`` and a
  resolvable owner/repo are available in the environment, drives the
  scenario end-to-end against real GitHub via the live observer.
  Without credentials the runner degrades to synthetic-fixture and
  records ``degraded_reason`` in state diagnostics.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

_LIB = Path(__file__).resolve().parents[1] / "lib"
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

from scenario_runner import cli_main  # noqa: E402
from synthetic_observe import generic_observe  # noqa: E402


SCENARIO_ID = 'task-dag-claim-and-plan'

PHASE_EXPECTED_KEYS = {
    'setup': ['issue_number_present'],
    'claim': ['issue_has_label', 'issue_locked'],
    'plan': ['brief_present', 'subagent_plan_count_min'],
    'verify': ['meta_status'],
}


def observe(phase_name, inputs, fixture, diagnostics):
    return generic_observe(
        phase_name,
        inputs,
        fixture,
        diagnostics,
        expected_keys=PHASE_EXPECTED_KEYS.get(phase_name, []),
    )


def live_observer_factory(*, github_client, owner, repo):
    """Build the live observer for task-dag-claim-and-plan."""
    from live_observe import TaskDagClaimObserver

    agent_login = os.environ.get("AGENT_LOGIN") or "agent"
    return TaskDagClaimObserver(
        github_client=github_client,
        agent_login=agent_login,
    )


if __name__ == "__main__":
    raise SystemExit(
        cli_main(SCENARIO_ID, observe, live_observer_factory=live_observer_factory)
    )
