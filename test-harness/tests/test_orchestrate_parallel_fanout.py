"""Tests for the orchestrate-issue-parallel-fanout scenario.

The parallel-fanout variant reuses :class:`OrchestrateIssueObserver`
with ``max_parallel > 1``. These tests pin the extra observation keys
the scenario asserts on (``subagent_branches_created``,
``no_cross_contamination``) and the parallel-dispatch behaviour
(distinct sub-branches, distinct stub files).
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


def _build(client, *, max_parallel=3):
    import live_observe

    return live_observe.OrchestrateIssueObserver(
        github_client=client,
        agent_login="alice",
        max_parallel=max_parallel,
        poll_interval_s=0.005,
        poll_timeout_s=10.0,
        sleep=lambda s: time.sleep(0.005),
        iso_now=lambda: "2026-05-17T00:00:00Z",
        new_session_id=lambda: "sess-parallel",
    )


class TestParallelFanoutObservations:
    def test_factory_returns_orchestrate_observer(self, client):
        import live_observe

        obs = live_observe.make_observer(
            "orchestrate-issue-parallel-fanout",
            github_client=client,
            agent_login="alice",
            max_parallel=3,
        )
        assert isinstance(obs, live_observe.OrchestrateIssueObserver)

    def test_fanout_returns_subagent_branches_created(self, client, tmp_path):
        obs = _build(client, max_parallel=3)
        obs("setup", {}, tmp_path, {})
        obs("claim", {}, tmp_path, {})
        stop = threading.Event()
        h = _start_fake_handler(client, obs.state.issue_number, stop_event=stop)
        try:
            out = obs(
                "fanout",
                {"max_parallel": 3, "planned_subagents": 3},
                tmp_path,
                {},
            )
        finally:
            stop.set()
            h.join(timeout=2)
        assert out["subagents_dispatched"] == 3
        assert out["subagent_branches_created"] == 3
        # Each branch is distinct.
        assert len(set(out["subagent_branches"])) == 3
        # Each branch has its own stub file.
        for branch in out["subagent_branches"]:
            sub_id = branch.rsplit("--", 1)[-1]
            content = client.get_file_contents(
                f".agent/runs/harness/{sub_id}.md", ref=branch
            )
            assert content is not None

    def test_verify_reports_no_cross_contamination_true(self, client, tmp_path):
        obs = _build(client, max_parallel=3)
        obs("setup", {}, tmp_path, {})
        obs("claim", {}, tmp_path, {})
        stop = threading.Event()
        h = _start_fake_handler(client, obs.state.issue_number, stop_event=stop)
        try:
            obs("fanout", {"max_parallel": 3}, tmp_path, {})
        finally:
            stop.set()
            h.join(timeout=2)
        obs("merge", {"merge_order": "plan"}, tmp_path, {})
        client.merge_pull_request(obs.state.pr_number)
        out = obs("verify", {}, tmp_path, {})
        assert out["pr_merged"] is True
        assert out["no_cross_contamination"] is True

    def test_verify_detects_cross_contamination(self, client, tmp_path):
        """If one sub-branch contains another's stub file, flag it."""
        obs = _build(client, max_parallel=2)
        obs("setup", {}, tmp_path, {})
        obs("claim", {}, tmp_path, {})
        stop = threading.Event()
        h = _start_fake_handler(client, obs.state.issue_number, stop_event=stop)
        try:
            obs("fanout", {"max_parallel": 2}, tmp_path, {})
        finally:
            stop.set()
            h.join(timeout=2)
        # Inject contamination: write sub-02's stub file on sub-01's branch.
        contaminated = obs.state.subagent_branches[0]
        client.put_file_contents(
            path=".agent/runs/harness/sub-02.md",
            content_bytes=b"injected",
            message="inject cross-contamination for test",
            branch=contaminated,
        )
        obs("merge", {}, tmp_path, {})
        client.merge_pull_request(obs.state.pr_number)
        out = obs("verify", {}, tmp_path, {})
        assert out["no_cross_contamination"] is False
