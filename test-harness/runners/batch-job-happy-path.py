#!/usr/bin/env python3
"""Runner for the 'batch-job-happy-path' scenario.

See test-harness/scenarios/batch-job-happy-path.yml for the scenario
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


SCENARIO_ID = "batch-job-happy-path"

# `expected_keys` per phase, used by generic_observe to decide whether
# any synthetic-mode assertion can be made for a given phase. If none of
# the phase's expected keys is in the synthetic catalogue, the phase is
# marked `skipped` rather than `failed`.
PHASE_EXPECTED_KEYS = {
    "setup": ["issue_number_present", "repo_created"],
    "invoke": ["batch_job_comment_present", "envelope_run_status"],
    "verify": ["envelope_run_status", "error_kind_absent", "summary_keys_present"],
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
    """Build the live observer for batch-job-happy-path.

    The factory is called by the scenario runner when ``--target=live-new-repo``
    and the environment supplies credentials. The agent_login is sourced
    from the env (``AGENT_LOGIN``) when set; the comment author is who
    drives the protocol, so ``add_comment`` from this client is what the
    handler workflow gates on via author_association.
    """
    from live_observe import BatchJobObserver

    agent_login = os.environ.get("AGENT_LOGIN") or "agent"
    return BatchJobObserver(
        github_client=github_client,
        agent_login=agent_login,
    )


if __name__ == "__main__":
    raise SystemExit(
        cli_main(SCENARIO_ID, observe, live_observer_factory=live_observer_factory)
    )
