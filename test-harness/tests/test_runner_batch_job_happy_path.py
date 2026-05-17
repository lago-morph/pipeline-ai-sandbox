"""End-to-end smoke test of the batch-job-happy-path runner.

Drives the scenario through ``run_scenario`` with the
``InMemoryGitHubClient`` from ``.agent/scripts/common.py`` as the
GitHub backend, plus a thread that plays the role of the workflow
handler — picking up the request comment, validating it, and writing
back a terminal envelope. This exercises the full
runner+observer+envelope chain without any real GitHub.

Marked with the ``scenario`` pytest marker so CI runs it.
"""
from __future__ import annotations

import importlib.util
import sys
import threading
import time
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# Imports — load InMemoryGitHubClient from .agent/scripts/common.py without
# polluting sys.modules with a package-qualified name.
# ---------------------------------------------------------------------------
def _load_common():
    p = REPO_ROOT / ".agent" / "scripts" / "common.py"
    spec = importlib.util.spec_from_file_location("_harness_agent_common", p)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("_harness_agent_common", mod)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def common():
    return _load_common()


# ---------------------------------------------------------------------------
# Background "workflow" thread: watches an issue's comments, picks up
# the first batch-job-request envelope, and writes a terminal envelope
# back. This stands in for the real GHA batch-job-handler workflow.
# ---------------------------------------------------------------------------
def _start_fake_handler(client, issue_number: int, *, stop_event: threading.Event):
    import envelopes

    def loop():
        seen = set()
        while not stop_event.is_set():
            try:
                for c in client.list_comments(issue_number):
                    cid = int(c["id"])
                    if cid in seen:
                        continue
                    body = c.get("body") or ""
                    parsed = envelopes.parse(body)
                    if parsed is None:
                        continue
                    if envelopes.is_terminal(parsed):
                        continue
                    if parsed.get("kind") != envelopes.KIND_REQUEST:
                        continue
                    # Simulate the workflow: stamp terminal envelope.
                    terminal = dict(parsed)
                    terminal["run_status"] = "completed"
                    terminal["run_started_at"] = "2026-05-17T00:00:01Z"
                    terminal["run_finished_at"] = "2026-05-17T00:00:02Z"
                    terminal["workflow_run_id"] = 42
                    terminal["checked_out_sha"] = parsed["commit_sha"]
                    terminal["summary"] = {
                        "echoed_args": parsed.get("args", {}),
                        "message": parsed.get("args", {}).get("message", "hello"),
                    }
                    terminal["log_manifest_branch"] = "_agent_runs"
                    terminal["log_manifest_path"] = "runs/x/y/manifest.json"
                    client.update_comment(cid, envelopes.serialize(terminal))
                    seen.add(cid)
            except Exception:
                pass
            time.sleep(0.01)

    t = threading.Thread(target=loop, name="fake-handler", daemon=True)
    t.start()
    return t


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------
@pytest.mark.scenario
def test_batch_job_happy_path_end_to_end(tmp_path, monkeypatch, common):
    """Drive the runner through setup→invoke→verify with a fake handler."""
    # Use the in-memory client; pre-seed a main branch with a known SHA.
    client = common.InMemoryGitHubClient(default_user="alice")
    client.create_branch("main")
    main_sha = client.get_branch_head_sha("main")
    assert main_sha is not None and len(main_sha) == 40

    # We're going to drive run_scenario manually so we can spin up the
    # fake workflow thread between phases. Import the runner pieces.
    import live_observe

    observer = live_observe.BatchJobObserver(
        github_client=client,
        agent_login="alice",
        poll_interval_s=0.0,
        poll_timeout_s=10.0,
        sleep=lambda s: time.sleep(0.0),
        iso_now=lambda: "2026-05-17T00:00:00Z",
    )

    # Phase 1: setup — creates the issue.
    out = observer("setup", {}, tmp_path, {})
    assert out["issue_number_present"]
    issue_number = out["issue_number"]

    # Start the fake handler before invoke so the poll loop sees the
    # comment terminalize quickly.
    stop = threading.Event()
    handler = _start_fake_handler(client, issue_number, stop_event=stop)

    try:
        # Phase 2: invoke — posts request, polls until terminal.
        out_inv = observer(
            "invoke",
            {"args": {"message": "hello from the harness"}},
            tmp_path,
            {},
        )
        assert out_inv["batch_job_comment_present"] is True
        assert out_inv["envelope_run_status"] == "completed"
        assert out_inv["terminal_envelope_parsed"] is True

        # Phase 3: verify — inspects the terminal envelope.
        out_v = observer("verify", {}, tmp_path, {})
        assert out_v["envelope_run_status"] == "completed"
        assert out_v["error_kind_absent"] is True
        # The fake handler writes summary={"echoed_args": ..., "message": ...}.
        assert set(out_v["summary_keys_present"]) == {"echoed_args", "message"}
    finally:
        stop.set()
        handler.join(timeout=2)


@pytest.mark.scenario
def test_runner_degrades_when_no_credentials(tmp_path, monkeypatch):
    """The CLI-level runner path should not crash when no creds present."""
    # Strip any env that might let it find creds.
    for k in ("GITHUB_TOKEN", "GH_TOKEN", "GITHUB_REPOSITORY"):
        monkeypatch.delenv(k, raising=False)
    # Importing the runner module is enough — run_scenario will degrade.
    import scenario_runner
    from synthetic_observe import generic_observe

    # Use the real scenarios directory; the synthetic observer correctly
    # marks phases skipped. We just assert exit code is 0 (no failures).
    def observe(phase_name, inputs, fixture, diagnostics):
        return generic_observe(
            phase_name,
            inputs,
            fixture,
            diagnostics,
            expected_keys=[
                "issue_number_present",
                "repo_created",
                "batch_job_comment_present",
                "envelope_run_status",
                "error_kind_absent",
                "summary_keys_present",
            ],
        )

    rc = scenario_runner.run_scenario(
        "batch-job-happy-path",
        observe,
        run_id="smoke-degrade",
        target_override="live-new-repo",
        live_observer_factory=None,
        env={},
    )
    assert rc == 0  # all phases skipped, no failures.
    # Cleanup so subsequent runs don't see stale state in repo tree.
    import shutil

    shutil.rmtree(
        Path("harness/runs/smoke-degrade"), ignore_errors=True
    )
