"""Unit tests for live_observe.OrchestrateIssueRestartObserver.

Drives the 5-phase restart-recovery scenario against
InMemoryGitHubClient. Key properties under test:

- fanout with ``kill_after_dispatch=True`` returns immediately after
  posting envelopes (no polling).
- restart rehydrates state purely from GitHub: issue body
  (feature_branch), branch list (sub-branches), comment list
  (request envelopes).
- no_duplicate_dispatch holds: the comment count before restart
  equals the count immediately after restart begins.
- finalise + verify behave like the single-subagent observer.
"""
from __future__ import annotations

import importlib.util
import sys
import threading
import time
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]


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


@pytest.fixture()
def client(common):
    c = common.InMemoryGitHubClient(default_user="alice")
    c.create_branch("main")
    return c


def _start_fake_handler(client, issue_number, *, stop_event):
    import envelopes

    def loop():
        seen = set()
        while not stop_event.is_set():
            try:
                for c in client.list_comments(issue_number):
                    cid = int(c["id"])
                    if cid in seen:
                        continue
                    parsed = envelopes.parse(c.get("body") or "")
                    if parsed is None:
                        continue
                    if envelopes.is_terminal(parsed):
                        continue
                    if parsed.get("kind") != envelopes.KIND_REQUEST:
                        continue
                    terminal = dict(parsed)
                    terminal["run_status"] = "completed"
                    terminal["checked_out_sha"] = parsed["commit_sha"]
                    terminal["summary"] = {"echoed_args": parsed.get("args", {})}
                    client.update_comment(cid, envelopes.serialize(terminal))
                    seen.add(cid)
            except Exception:
                pass
            time.sleep(0.005)

    t = threading.Thread(target=loop, name="fake-handler", daemon=True)
    t.start()
    return t


def _build(client, **overrides):
    import live_observe

    defaults = dict(
        github_client=client,
        agent_login="alice",
        max_parallel=2,
        poll_interval_s=0.005,
        poll_timeout_s=10.0,
        sleep=lambda s: time.sleep(0.005),
        iso_now=lambda: "2026-05-17T00:00:00Z",
        new_session_id=lambda: "sess-restart",
    )
    defaults.update(overrides)
    return live_observe.OrchestrateIssueRestartObserver(**defaults)


class TestConstruction:
    def test_requires_agent_login(self, client):
        import live_observe

        with pytest.raises(ValueError):
            live_observe.OrchestrateIssueRestartObserver(
                github_client=client,
                agent_login="",
            )

    def test_rejects_zero_max_parallel(self, client):
        import live_observe

        with pytest.raises(ValueError):
            live_observe.OrchestrateIssueRestartObserver(
                github_client=client,
                agent_login="alice",
                max_parallel=0,
            )


class TestSetupPhase:
    def test_creates_issue_with_working_status(self, client, tmp_path):
        # The restart-recovery observer's setup pre-claims the issue
        # (status: working) because the scenario YAML has no separate
        # claim phase — the orchestrator owns the issue immediately.
        obs = _build(client)
        out = obs("setup", {}, tmp_path, {})
        assert out["issue_number_present"] is True
        meta = obs._parse_agent_meta(client.get_issue(out["issue_number"])["body"])
        assert meta["status"] == "working"
        assert meta["agent_id"]


class TestFanoutKill:
    def test_fanout_kill_returns_immediately(self, client, tmp_path):
        obs = _build(client)
        obs("setup", {}, tmp_path, {})
        out = obs("fanout", {"max_parallel": 2, "kill_after_dispatch": True}, tmp_path, {})
        assert out["subagents_dispatched"] == 2
        assert out["orchestrator_killed_mid_fanout"] is True
        assert out["subagent_branches_created"] == 2
        # No subagent terminal envelope has been recorded yet.
        assert all(e is None for e in obs.state.subagent_terminal_envelopes)
        # The comments are posted but not yet terminal.
        comments = client.list_comments(obs.state.issue_number)
        import envelopes

        envelope_comments = [c for c in comments if envelopes.parse(c["body"])]
        assert len(envelope_comments) == 2
        # None terminal yet.
        assert not any(
            envelopes.is_terminal(envelopes.parse(c["body"])) for c in envelope_comments
        )

    def test_fanout_without_kill_polls_to_terminal(self, client, tmp_path):
        obs = _build(client)
        obs("setup", {}, tmp_path, {})
        stop = threading.Event()
        h = _start_fake_handler(client, obs.state.issue_number, stop_event=stop)
        try:
            out = obs("fanout", {"max_parallel": 2}, tmp_path, {})
        finally:
            stop.set()
            h.join(timeout=2)
        assert out["orchestrator_killed_mid_fanout"] is False
        assert out["all_subagents_terminal"] is True


class TestRestartPhase:
    def test_requires_kill_first(self, client, tmp_path):
        obs = _build(client)
        obs("setup", {}, tmp_path, {})
        # fanout without kill — then restart should refuse.
        stop = threading.Event()
        h = _start_fake_handler(client, obs.state.issue_number, stop_event=stop)
        try:
            obs("fanout", {"max_parallel": 1}, tmp_path, {})
        finally:
            stop.set()
            h.join(timeout=2)
        with pytest.raises(RuntimeError, match="fanout did not kill"):
            obs("restart", {}, tmp_path, {})

    def test_restart_rehydrates_and_polls(self, client, tmp_path):
        obs = _build(client)
        obs("setup", {}, tmp_path, {})
        obs("fanout", {"max_parallel": 2, "kill_after_dispatch": True}, tmp_path, {})

        # Capture state before restart so we can assert it was rehydrated
        # (i.e. not just carried over).
        original_subagent_branches = list(obs.state.subagent_branches)
        original_issue_number = obs.state.issue_number

        # Start the fake handler so terminalisation happens during restart.
        stop = threading.Event()
        h = _start_fake_handler(client, original_issue_number, stop_event=stop)
        try:
            out = obs("restart", {}, tmp_path, {})
        finally:
            stop.set()
            h.join(timeout=2)

        assert out["restart_acknowledged"] is True
        assert out["no_duplicate_dispatch"] is True
        # Rehydrated state matches what was on disk pre-kill.
        assert out["rehydrated_issue_number"] == original_issue_number
        assert sorted(out["rehydrated_subagent_branches"]) == sorted(
            original_subagent_branches
        )
        # After polling, the terminal envelopes are populated.
        assert all(e is not None for e in obs.state.subagent_terminal_envelopes)

    def test_restart_detects_duplicate_dispatch(self, client, tmp_path):
        """If something posts an extra request comment after kill but
        before restart, no_duplicate_dispatch should be False."""
        obs = _build(client)
        obs("setup", {}, tmp_path, {})
        obs("fanout", {"max_parallel": 1, "kill_after_dispatch": True}, tmp_path, {})

        # Simulate a duplicate-dispatch bug: post another request envelope.
        from envelopes import build_request, serialize

        env = build_request(
            command="echo",
            args={},
            branch=obs.state.subagent_branches[0],
            commit_sha=obs.state.subagent_heads[0],
            subagent_id="bogus-extra",
            submitted_at="2026-05-17T00:00:01Z",
        )
        client.add_comment(obs.state.issue_number, serialize(env))

        # Start handler so the polling completes (otherwise we wait for
        # the timeout).
        stop = threading.Event()
        h = _start_fake_handler(client, obs.state.issue_number, stop_event=stop)
        try:
            out = obs("restart", {}, tmp_path, {})
        finally:
            stop.set()
            h.join(timeout=2)
        assert out["no_duplicate_dispatch"] is False


class TestFinaliseAndVerify:
    def test_finalise_opens_pr(self, client, tmp_path):
        obs = _build(client)
        obs("setup", {}, tmp_path, {})
        obs("fanout", {"max_parallel": 2, "kill_after_dispatch": True}, tmp_path, {})
        stop = threading.Event()
        h = _start_fake_handler(client, obs.state.issue_number, stop_event=stop)
        try:
            obs("restart", {}, tmp_path, {})
        finally:
            stop.set()
            h.join(timeout=2)
        out = obs("finalise", {}, tmp_path, {})
        assert out["pr_opened"] is True
        assert out["feature_branch_advanced"] is True
        pr = client.get_pull_request(out["pr_number"])
        assert pr["base"]["ref"] == "main"

    def test_verify_polls_pr_merged(self, client, tmp_path):
        obs = _build(client)
        obs("setup", {}, tmp_path, {})
        obs("fanout", {"max_parallel": 1, "kill_after_dispatch": True}, tmp_path, {})
        stop = threading.Event()
        h = _start_fake_handler(client, obs.state.issue_number, stop_event=stop)
        try:
            obs("restart", {}, tmp_path, {})
        finally:
            stop.set()
            h.join(timeout=2)
        obs("finalise", {}, tmp_path, {})
        client.merge_pull_request(obs.state.pr_number)
        out = obs("verify", {}, tmp_path, {})
        assert out["pr_merged"] is True
        assert out["meta_status"] == "finished"


class TestUnknownPhase:
    def test_unknown_phase_raises(self, client, tmp_path):
        obs = _build(client)
        with pytest.raises(ValueError, match="unknown phase"):
            obs("nope", {}, tmp_path, {})


class TestFactory:
    def test_supported_scenarios_includes_restart(self):
        import live_observe

        assert "orchestrate-issue-restart-recovery" in live_observe.supported_scenarios()

    def test_make_observer(self, client):
        import live_observe

        obs = live_observe.make_observer(
            "orchestrate-issue-restart-recovery",
            github_client=client,
            agent_login="alice",
        )
        assert isinstance(obs, live_observe.OrchestrateIssueRestartObserver)


@pytest.mark.scenario
def test_restart_recovery_end_to_end(client, tmp_path):
    """Drive all 5 phases and demonstrate restart from GitHub state."""
    import live_observe

    obs = live_observe.OrchestrateIssueRestartObserver(
        github_client=client,
        agent_login="alice",
        max_parallel=2,
        poll_interval_s=0.005,
        poll_timeout_s=10.0,
        sleep=lambda s: time.sleep(0.005),
        iso_now=lambda: "2026-05-17T00:00:00Z",
        new_session_id=lambda: "sess-e2e",
    )
    obs("setup", {}, tmp_path, {})
    obs("fanout", {"max_parallel": 2, "kill_after_dispatch": True}, tmp_path, {})

    stop = threading.Event()
    h = _start_fake_handler(client, obs.state.issue_number, stop_event=stop)
    try:
        restart_out = obs("restart", {}, tmp_path, {})
        assert restart_out["restart_acknowledged"] is True
        assert restart_out["no_duplicate_dispatch"] is True

        finalise_out = obs("finalise", {}, tmp_path, {})
        assert finalise_out["pr_opened"] is True
    finally:
        stop.set()
        h.join(timeout=2)

    client.merge_pull_request(obs.state.pr_number)
    verify_out = obs("verify", {}, tmp_path, {})
    assert verify_out["pr_merged"] is True
    assert verify_out["meta_status"] == "finished"
