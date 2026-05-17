"""Unit tests for live_observe.TaskDagClaimObserver.

Drives the observer with InMemoryGitHubClient. The task-dag scenarios
don't involve a workflow handler (no batch-job envelopes), so no
background thread is needed — phases are purely about issue
body/label state transitions.
"""
from __future__ import annotations

import importlib.util
import sys
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


def _build(client, **overrides):
    import live_observe

    defaults = dict(
        github_client=client,
        agent_login="alice",
        poll_interval_s=0.0,
        poll_timeout_s=5.0,
        sleep=lambda s: None,
        iso_now=lambda: "2026-05-17T00:00:00Z",
        new_session_id=lambda: "sess-task-dag",
    )
    defaults.update(overrides)
    return live_observe.TaskDagClaimObserver(**defaults)


class TestConstruction:
    def test_requires_agent_login(self, client):
        import live_observe

        with pytest.raises(ValueError):
            live_observe.TaskDagClaimObserver(
                github_client=client,
                agent_login="",
            )

    def test_starts_empty(self, client):
        obs = _build(client)
        assert obs.state.issue_number is None
        assert obs.state.brief is None
        assert obs.state.subagent_plan == []


class TestSetupPhase:
    def test_creates_issue_with_agent_meta(self, client, tmp_path):
        obs = _build(client)
        out = obs("setup", {}, tmp_path, {})
        assert out["issue_number_present"] is True
        issue = client.get_issue(out["issue_number"])
        meta = obs._parse_agent_meta(issue["body"])
        assert meta is not None
        assert meta["status"] is None
        assert meta["feature_branch"] == out["feature_branch"]

    def test_passes_through_instructions(self, client, tmp_path):
        obs = _build(client)
        obs(
            "setup",
            {"issue_body": "write a hello world test"},
            tmp_path,
            {},
        )
        meta = obs._parse_agent_meta(client.get_issue(1)["body"])
        assert meta["instructions_inline"] == "write a hello world test"

    def test_raises_when_base_branch_missing(self, common, tmp_path):
        c = common.InMemoryGitHubClient(default_user="alice")
        obs = _build(c)
        with pytest.raises(RuntimeError, match="base branch does not exist"):
            obs("setup", {}, tmp_path, {})


class TestClaimPhase:
    def test_requires_setup_first(self, client, tmp_path):
        obs = _build(client)
        with pytest.raises(RuntimeError, match="setup phase has not run"):
            obs("claim", {}, tmp_path, {})

    def test_claim_writes_meta_and_label(self, client, tmp_path):
        obs = _build(client)
        obs("setup", {}, tmp_path, {})
        out = obs("claim", {"agent_id": "harness-claim"}, tmp_path, {})
        assert out["issue_locked"] is True
        assert out["issue_has_label"] is True
        assert out["claim_won"] is True
        # Confirm the actual state.
        issue = client.get_issue(obs.state.issue_number)
        meta = obs._parse_agent_meta(issue["body"])
        assert meta["status"] == "working"
        assert meta["agent_id"] == "harness-claim"
        labels = {lbl["name"] for lbl in (issue["labels"] or [])}
        assert "agent-task-claimed" in labels

    def test_claim_detects_race_loss(self, client, tmp_path):
        """If another agent writes a different agent_id during the
        re-read window, we self-abandon."""
        obs = _build(client)
        obs("setup", {}, tmp_path, {})

        # Wrap update_issue so that immediately after the observer
        # writes its meta, an interloper overwrites it. This simulates
        # the CAS race the protocol guards against.
        real_update = client.update_issue
        interloper_called = {"n": 0}

        def racy_update(number, body=None, **kw):
            result = real_update(number, body=body, **kw)
            # Only intercept the first update (the observer's), not
            # subsequent ones (e.g. add_label-induced).
            if interloper_called["n"] == 0:
                interloper_called["n"] = 1
                # Interloper rewrites the agent-meta with a different
                # agent_id. In the real protocol this would be another
                # agent's claim; here we just splice the body.
                from copy import deepcopy

                meta = obs._parse_agent_meta(body)
                assert meta is not None
                hostile = deepcopy(meta)
                hostile["agent_id"] = "interloper"
                hostile["session_id"] = "interloper-sess"
                hostile_body = obs._replace_agent_meta(body, hostile)
                real_update(number, body=hostile_body)
            return result

        client.update_issue = racy_update
        out = obs("claim", {"agent_id": "us"}, tmp_path, {})
        assert out["claim_won"] is False
        assert out["issue_locked"] is False


class TestPlanPhase:
    def test_requires_claim_first(self, client, tmp_path):
        obs = _build(client)
        obs("setup", {}, tmp_path, {})
        with pytest.raises(RuntimeError, match="claim phase has not run"):
            obs("plan", {}, tmp_path, {})

    def test_plan_produces_brief_and_subagent_plan(self, client, tmp_path):
        obs = _build(client)
        obs("setup", {"issue_body": "write a hello world test"}, tmp_path, {})
        obs("claim", {}, tmp_path, {})
        out = obs("plan", {}, tmp_path, {})
        assert out["brief_present"] is True
        assert out["subagent_plan_count_min"] >= 1
        assert obs.state.brief is not None
        assert "hello world test" in obs.state.brief
        # The brief was posted as a comment.
        comments = client.list_comments(obs.state.issue_number)
        assert any("Brief for issue" in (c["body"] or "") for c in comments)

    def test_plan_writes_meta_status_planned(self, client, tmp_path):
        obs = _build(client)
        obs("setup", {}, tmp_path, {})
        obs("claim", {}, tmp_path, {})
        obs("plan", {}, tmp_path, {})
        meta = obs._parse_agent_meta(client.get_issue(obs.state.issue_number)["body"])
        assert meta["status"] == "planned"
        assert meta["plan_state"] == "planned"


class TestVerifyPhase:
    def test_requires_setup(self, client, tmp_path):
        obs = _build(client)
        with pytest.raises(RuntimeError, match="setup phase has not run"):
            obs("verify", {}, tmp_path, {})

    def test_verify_returns_meta_status_after_plan(self, client, tmp_path):
        obs = _build(client)
        obs("setup", {}, tmp_path, {})
        obs("claim", {}, tmp_path, {})
        obs("plan", {}, tmp_path, {})
        out = obs("verify", {}, tmp_path, {})
        assert out["meta_status"] == "planned"
        assert out["plan_state"] == "planned"
        assert out["agent_id_present"] is True


class TestUnknownPhase:
    def test_unknown_phase_raises(self, client, tmp_path):
        obs = _build(client)
        with pytest.raises(ValueError, match="unknown phase"):
            obs("frobnicate", {}, tmp_path, {})


class TestFactory:
    def test_supported_scenarios_includes_task_dag(self):
        import live_observe

        assert "task-dag-claim-and-plan" in live_observe.supported_scenarios()

    def test_make_observer_returns_task_dag_observer(self, client):
        import live_observe

        obs = live_observe.make_observer(
            "task-dag-claim-and-plan",
            github_client=client,
            agent_login="alice",
        )
        assert isinstance(obs, live_observe.TaskDagClaimObserver)


@pytest.mark.scenario
def test_task_dag_end_to_end(client, tmp_path):
    """Drive setup → claim → plan → verify against InMemoryGitHubClient."""
    import live_observe

    observer = live_observe.TaskDagClaimObserver(
        github_client=client,
        agent_login="alice",
        poll_interval_s=0.0,
        poll_timeout_s=5.0,
        sleep=lambda s: time.sleep(0.0),
        iso_now=lambda: "2026-05-17T00:00:00Z",
        new_session_id=lambda: "sess-e2e",
    )
    setup_out = observer("setup", {"issue_body": "write a hello world test"}, tmp_path, {})
    assert setup_out["issue_number_present"] is True

    claim_out = observer("claim", {"agent_id": "harness-claim"}, tmp_path, {})
    assert claim_out["issue_locked"] is True
    assert claim_out["issue_has_label"] is True

    plan_out = observer("plan", {}, tmp_path, {})
    assert plan_out["brief_present"] is True
    assert plan_out["subagent_plan_count_min"] >= 1

    verify_out = observer("verify", {}, tmp_path, {})
    assert verify_out["meta_status"] == "planned"
