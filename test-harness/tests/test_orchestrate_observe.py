"""Unit tests for live_observe.OrchestrateIssueObserver.

Tests drive the observer with ``InMemoryGitHubClient`` from
``.agent/scripts/common.py`` (full-featured fake — branches, commits,
PRs) plus an injected clock + sleep so polling is deterministic.

No real GitHub.
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
# Load InMemoryGitHubClient from .agent/scripts/common.py without polluting
# sys.modules with a package-qualified name.
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


@pytest.fixture()
def client(common):
    c = common.InMemoryGitHubClient(default_user="alice")
    c.create_branch("main")
    return c


def _fake_clock():
    """A monotonic clock that ticks 1.0 per call."""
    counter = {"t": 0.0}

    def now():
        counter["t"] += 1.0
        return counter["t"]

    return now


def _make_observer(client, *, with_handler=False, **overrides):
    """Build an observer with deterministic clock + sleep.

    When ``with_handler=True`` the observer uses ``time.sleep(0.005)``
    so the background fake-handler thread gets scheduling slots; the
    fake clock still bounds the polling deadline so timeouts are
    deterministic.
    """
    import live_observe

    defaults = dict(
        github_client=client,
        agent_login="alice",
        max_parallel=1,
        poll_interval_s=0.005,
        poll_timeout_s=20.0,
        sleep=(lambda s: time.sleep(0.005)) if with_handler else (lambda s: None),
        clock=_fake_clock(),
        iso_now=lambda: "2026-05-17T00:00:00Z",
        new_session_id=lambda: "session-xyz",
    )
    defaults.update(overrides)
    return live_observe.OrchestrateIssueObserver(**defaults)


def _start_fake_handler(client, issue_number: int, *, stop_event: threading.Event):
    """Background thread: stamp every batch-job-request comment terminal."""
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


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------
class TestConstruction:
    def test_requires_agent_login(self, client):
        import live_observe

        with pytest.raises(ValueError):
            live_observe.OrchestrateIssueObserver(
                github_client=client,
                agent_login="",
            )

    def test_rejects_zero_max_parallel(self, client):
        import live_observe

        with pytest.raises(ValueError):
            live_observe.OrchestrateIssueObserver(
                github_client=client,
                agent_login="alice",
                max_parallel=0,
            )

    def test_starts_with_empty_state(self, client):
        obs = _make_observer(client)
        assert obs.state.issue_number is None
        assert obs.state.feature_branch is None
        assert obs.state.subagent_branches == []
        assert obs.state.pr_number is None


# ---------------------------------------------------------------------------
# setup
# ---------------------------------------------------------------------------
class TestSetupPhase:
    def test_creates_issue_with_agent_meta_block(self, client, tmp_path):
        obs = _make_observer(client)
        out = obs("setup", {}, tmp_path, {})
        assert out["issue_number_present"] is True
        issue = client.get_issue(out["issue_number"])
        meta_text = issue["body"]
        assert "```agent-meta" in meta_text
        # Round-trip parse.
        from_obs = obs._parse_agent_meta(meta_text)
        assert from_obs is not None
        assert from_obs["status"] is None
        assert from_obs["feature_branch"] == out["feature_branch"]
        assert from_obs["base_branch"] == "main"
        assert from_obs["instructions_inline"]

    def test_creates_feature_branch_from_base(self, client, tmp_path):
        obs = _make_observer(client)
        out = obs("setup", {}, tmp_path, {})
        head = client.get_branch_head_sha(out["feature_branch"])
        assert head is not None
        # InMemoryGitHubClient's create_branch stamps a fresh "create
        # branch X" commit on the new branch (the in-memory equivalent
        # of a branch ref + a baseline marker). The observer records
        # that as the feature baseline; subsequent commits advance past
        # it. We assert the baseline is recorded; we don't assert it
        # equals the base SHA (the in-memory client doesn't share commits
        # across branches in the way real git does).
        assert out["feature_baseline_sha"] == head

    def test_uses_explicit_feature_branch_when_provided(self, client, tmp_path):
        obs = _make_observer(client, feature_branch="agent/42-fixed-name")
        out = obs("setup", {}, tmp_path, {})
        assert out["feature_branch"] == "agent/42-fixed-name"
        assert client.get_branch_head_sha("agent/42-fixed-name") is not None

    def test_passes_through_title_and_instructions(self, client, tmp_path):
        obs = _make_observer(client)
        obs(
            "setup",
            {"title": "custom title", "issue_body": "do the thing"},
            tmp_path,
            {},
        )
        issue = client.get_issue(1)
        assert issue["title"] == "custom title"
        meta = obs._parse_agent_meta(issue["body"])
        assert meta["instructions_inline"] == "do the thing"

    def test_raises_when_base_branch_missing(self, common, tmp_path):
        c = common.InMemoryGitHubClient(default_user="alice")  # no main
        obs = _make_observer(c)
        with pytest.raises(RuntimeError, match="base branch does not exist"):
            obs("setup", {}, tmp_path, {})


# ---------------------------------------------------------------------------
# claim
# ---------------------------------------------------------------------------
class TestClaimPhase:
    def test_requires_setup_to_have_run(self, client, tmp_path):
        obs = _make_observer(client)
        with pytest.raises(RuntimeError, match="setup phase has not run"):
            obs("claim", {}, tmp_path, {})

    def test_updates_agent_meta_to_working(self, client, tmp_path):
        obs = _make_observer(client)
        obs("setup", {}, tmp_path, {})
        out = obs("claim", {"agent_id": "the-agent"}, tmp_path, {})
        assert out["issue_locked"] is True
        assert out["agent_id"] == "the-agent"
        assert out["meta_status"] == "working"
        # Inspect the actual issue body.
        issue = client.get_issue(obs.state.issue_number)
        meta = obs._parse_agent_meta(issue["body"])
        assert meta["status"] == "working"
        assert meta["agent_id"] == "the-agent"
        assert meta["session_id"] == "session-xyz"

    def test_defaults_agent_id_when_omitted(self, client, tmp_path):
        obs = _make_observer(client)
        obs("setup", {}, tmp_path, {})
        out = obs("claim", {}, tmp_path, {})
        assert out["agent_id"].startswith("orchestrate-")

    def test_raises_when_agent_meta_missing(self, client, tmp_path):
        obs = _make_observer(client)
        obs("setup", {}, tmp_path, {})
        # Corrupt the issue body so there is no agent-meta block.
        client.update_issue(obs.state.issue_number, body="just prose, no meta")
        with pytest.raises(RuntimeError, match="agent-meta block"):
            obs("claim", {}, tmp_path, {})


# ---------------------------------------------------------------------------
# fanout
# ---------------------------------------------------------------------------
class TestFanoutPhase:
    def test_requires_claim_to_have_run(self, client, tmp_path):
        obs = _make_observer(client)
        obs("setup", {}, tmp_path, {})
        with pytest.raises(RuntimeError, match="claim phase has not run"):
            obs("fanout", {}, tmp_path, {})

    def test_dispatches_one_subagent_and_observes_terminal(self, client, tmp_path):
        obs = _make_observer(client, with_handler=True)
        obs("setup", {}, tmp_path, {})
        obs("claim", {}, tmp_path, {})
        stop = threading.Event()
        h = _start_fake_handler(client, obs.state.issue_number, stop_event=stop)
        try:
            out = obs(
                "fanout",
                {"max_parallel": 1, "args": {"message": "hi"}},
                tmp_path,
                {},
            )
        finally:
            stop.set()
            h.join(timeout=2)
        assert out["subagents_dispatched"] == 1
        assert out["all_subagents_terminal"] is True
        assert len(out["subagent_branches"]) == 1
        assert out["subagent_branches"][0].endswith("--sub-01")
        # Sub-branch exists with a stub commit on top of the feature tip.
        sub_branch = out["subagent_branches"][0]
        sub_head = client.get_branch_head_sha(sub_branch)
        feature_head = client.get_branch_head_sha(obs.state.feature_branch)
        assert sub_head is not None and sub_head != feature_head

    def test_dispatches_multiple_subagents(self, client, tmp_path):
        obs = _make_observer(client, with_handler=True, max_parallel=3)
        obs("setup", {}, tmp_path, {})
        obs("claim", {}, tmp_path, {})
        stop = threading.Event()
        h = _start_fake_handler(client, obs.state.issue_number, stop_event=stop)
        try:
            out = obs("fanout", {"max_parallel": 3}, tmp_path, {})
        finally:
            stop.set()
            h.join(timeout=2)
        assert out["subagents_dispatched"] == 3
        assert out["all_subagents_terminal"] is True
        assert sorted(b.rsplit("--", 1)[-1] for b in out["subagent_branches"]) == [
            "sub-01",
            "sub-02",
            "sub-03",
        ]

    def test_times_out_when_handler_never_completes(self, client, tmp_path):
        obs = _make_observer(client, poll_timeout_s=3.0)
        obs("setup", {}, tmp_path, {})
        obs("claim", {}, tmp_path, {})
        # No background handler — the request stays running forever.
        out = obs("fanout", {"max_parallel": 1}, tmp_path, {})
        assert out["subagents_dispatched"] == 1
        assert out["all_subagents_terminal"] is False


# ---------------------------------------------------------------------------
# merge
# ---------------------------------------------------------------------------
class TestMergePhase:
    def test_requires_fanout_to_have_run(self, client, tmp_path):
        obs = _make_observer(client)
        obs("setup", {}, tmp_path, {})
        obs("claim", {}, tmp_path, {})
        with pytest.raises(RuntimeError, match="fanout phase has not run"):
            obs("merge", {}, tmp_path, {})

    def test_advances_feature_branch_and_opens_pr(self, client, tmp_path):
        obs = _make_observer(client, with_handler=True)
        obs("setup", {}, tmp_path, {})
        obs("claim", {}, tmp_path, {})
        stop = threading.Event()
        h = _start_fake_handler(client, obs.state.issue_number, stop_event=stop)
        try:
            obs("fanout", {"max_parallel": 1}, tmp_path, {})
        finally:
            stop.set()
            h.join(timeout=2)
        baseline = obs.state.feature_baseline_sha
        out = obs("merge", {}, tmp_path, {})
        new_head = client.get_branch_head_sha(obs.state.feature_branch)
        assert out["feature_branch_advanced"] is True
        assert new_head is not None and new_head != baseline
        assert out["pr_opened"] is True
        # The PR points head -> feature, base -> main.
        pr = client.get_pull_request(out["pr_number"])
        assert pr["head"]["ref"] == obs.state.feature_branch
        assert pr["base"]["ref"] == "main"


# ---------------------------------------------------------------------------
# verify
# ---------------------------------------------------------------------------
class TestVerifyPhase:
    def test_requires_merge_to_have_run(self, client, tmp_path):
        obs = _make_observer(client)
        obs("setup", {}, tmp_path, {})
        obs("claim", {}, tmp_path, {})
        with pytest.raises(RuntimeError, match="merge phase has not run"):
            obs("verify", {}, tmp_path, {})

    def test_writes_finished_meta_and_observes_pr_merged(self, client, tmp_path):
        obs = _make_observer(client, with_handler=True)
        obs("setup", {}, tmp_path, {})
        obs("claim", {}, tmp_path, {})
        stop = threading.Event()
        h = _start_fake_handler(client, obs.state.issue_number, stop_event=stop)
        try:
            obs("fanout", {"max_parallel": 1}, tmp_path, {})
        finally:
            stop.set()
            h.join(timeout=2)
        obs("merge", {}, tmp_path, {})
        # Simulate the user merging the PR.
        client.merge_pull_request(obs.state.pr_number)
        out = obs("verify", {}, tmp_path, {})
        assert out["pr_merged"] is True
        assert out["meta_status"] == "finished"
        # The agent-meta block on the issue body now reads finished.
        issue = client.get_issue(obs.state.issue_number)
        meta = obs._parse_agent_meta(issue["body"])
        assert meta["status"] == "finished"

    def test_pr_not_merged_yields_false(self, client, tmp_path):
        obs = _make_observer(client, with_handler=True, poll_timeout_s=3.0)
        obs("setup", {}, tmp_path, {})
        obs("claim", {}, tmp_path, {})
        stop = threading.Event()
        h = _start_fake_handler(client, obs.state.issue_number, stop_event=stop)
        try:
            obs("fanout", {"max_parallel": 1}, tmp_path, {})
        finally:
            stop.set()
            h.join(timeout=2)
        obs("merge", {}, tmp_path, {})
        # PR is intentionally NOT merged.
        out = obs("verify", {}, tmp_path, {})
        assert out["pr_merged"] is False
        # finished still got written — the orchestrator finishes the
        # issue before the PR merges.
        assert out["meta_status"] == "finished"


# ---------------------------------------------------------------------------
# unknown phase
# ---------------------------------------------------------------------------
class TestUnknownPhase:
    def test_unknown_phase_raises(self, client, tmp_path):
        obs = _make_observer(client)
        with pytest.raises(ValueError, match="unknown phase"):
            obs("nonsense", {}, tmp_path, {})


# ---------------------------------------------------------------------------
# factory
# ---------------------------------------------------------------------------
class TestFactory:
    def test_supported_scenarios_includes_orchestrate(self):
        import live_observe

        assert "orchestrate-issue-single-subagent" in live_observe.supported_scenarios()

    def test_make_observer_returns_orchestrate_observer(self, client):
        import live_observe

        obs = live_observe.make_observer(
            "orchestrate-issue-single-subagent",
            github_client=client,
            agent_login="alice",
        )
        assert isinstance(obs, live_observe.OrchestrateIssueObserver)


# ---------------------------------------------------------------------------
# End-to-end smoke through the runner
# ---------------------------------------------------------------------------
@pytest.mark.scenario
def test_orchestrate_single_subagent_end_to_end(client, tmp_path, common):
    """Drive the runner setup→claim→fanout→merge→verify with a fake handler."""
    import live_observe

    observer = live_observe.OrchestrateIssueObserver(
        github_client=client,
        agent_login="alice",
        max_parallel=1,
        poll_interval_s=0.0,
        poll_timeout_s=10.0,
        sleep=lambda s: time.sleep(0.0),
        iso_now=lambda: "2026-05-17T00:00:00Z",
        new_session_id=lambda: "sess-abc",
    )

    setup_out = observer("setup", {}, tmp_path, {})
    assert setup_out["issue_number_present"] is True
    issue_number = setup_out["issue_number"]

    stop = threading.Event()
    handler = _start_fake_handler(client, issue_number, stop_event=stop)
    try:
        claim_out = observer("claim", {"agent_id": "orchestrate-alice"}, tmp_path, {})
        assert claim_out["issue_locked"] is True

        fanout_out = observer("fanout", {"max_parallel": 1}, tmp_path, {})
        assert fanout_out["subagents_dispatched"] == 1
        assert fanout_out["all_subagents_terminal"] is True

        merge_out = observer("merge", {}, tmp_path, {})
        assert merge_out["feature_branch_advanced"] is True
        assert merge_out["pr_opened"] is True

        # Simulate the user merging the PR.
        client.merge_pull_request(merge_out["pr_number"])

        verify_out = observer("verify", {}, tmp_path, {})
        assert verify_out["pr_merged"] is True
        assert verify_out["meta_status"] == "finished"
    finally:
        stop.set()
        handler.join(timeout=2)
