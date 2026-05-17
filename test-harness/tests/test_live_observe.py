"""Unit tests for live_observe.BatchJobObserver.

We don't talk to real GitHub. Instead we drive the observer with a
fake client that lets us script: branch HEAD SHA, list/get/post/update
comment behaviour, and add_label/create_issue. The fake also tracks
how many polls happened so tests can pin down timing-sensitive
behaviour without sleeping.
"""
from __future__ import annotations

from typing import Any, Optional

import pytest

import envelopes
import live_observe


VALID_SHA = "f" * 40


# ---------------------------------------------------------------------------
# Fake client
# ---------------------------------------------------------------------------
class FakeGitHubClient:
    def __init__(self, head_sha=VALID_SHA):
        self.head_sha = head_sha
        self.branches = {"main": head_sha}
        self.created_issues: list[dict[str, Any]] = []
        self.added_labels: list[tuple[int, str]] = []
        self.comments: dict[int, dict[str, Any]] = {}
        self.next_issue_number = 42
        self.next_comment_id = 1000
        self.comment_bodies_over_time: dict[int, list[str]] = {}
        # Optional: callable(call_idx, comment_id) -> body to override get_comment.
        self.get_comment_script: Optional[Any] = None
        self.get_comment_calls = 0

    def get_branch_head_sha(self, branch):
        return self.branches.get(branch)

    def create_issue(self, title, body, labels=None):
        number = self.next_issue_number
        self.next_issue_number += 1
        issue = {
            "number": number,
            "title": title,
            "body": body,
            "labels": [{"name": name} for name in (labels or [])],
        }
        self.created_issues.append(issue)
        return issue

    def add_label(self, number, label):
        self.added_labels.append((number, label))

    def add_comment(self, issue_number, body):
        comment_id = self.next_comment_id
        self.next_comment_id += 1
        comment = {"id": comment_id, "body": body, "issue_number": issue_number}
        self.comments[comment_id] = comment
        self.comment_bodies_over_time.setdefault(comment_id, []).append(body)
        return comment

    def list_comments(self, issue_number):
        return [c for c in self.comments.values() if c["issue_number"] == issue_number]

    def get_comment(self, comment_id):
        self.get_comment_calls += 1
        if self.get_comment_script is not None:
            body = self.get_comment_script(self.get_comment_calls, comment_id)
            return {"id": comment_id, "body": body}
        return dict(self.comments[comment_id])

    # Test helper: simulate the workflow updating a comment to a new body.
    def update_comment_body(self, comment_id, body):
        self.comments[comment_id]["body"] = body
        self.comment_bodies_over_time.setdefault(comment_id, []).append(body)


def _fake_clock():
    """A monotonic clock that ticks 1.0 per call."""
    counter = {"t": 0.0}

    def now():
        counter["t"] += 1.0
        return counter["t"]

    return now


def _make_observer(client, *, poll_interval_s=0.0, poll_timeout_s=10.0, sleep=None):
    return live_observe.BatchJobObserver(
        github_client=client,
        agent_login="alice",
        poll_interval_s=poll_interval_s,
        poll_timeout_s=poll_timeout_s,
        sleep=sleep or (lambda s: None),
        clock=_fake_clock(),
        iso_now=lambda: "2026-05-17T00:00:00Z",
    )


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------
class TestConstruction:
    def test_requires_agent_login(self):
        with pytest.raises(ValueError):
            live_observe.BatchJobObserver(
                github_client=FakeGitHubClient(),
                agent_login="",
            )

    def test_starts_with_empty_state(self):
        obs = _make_observer(FakeGitHubClient())
        assert obs.state.issue_number is None
        assert obs.state.request_comment_id is None
        assert obs.state.terminal_envelope is None


# ---------------------------------------------------------------------------
# setup phase
# ---------------------------------------------------------------------------
class TestSetupPhase:
    def test_creates_issue_and_records_sha(self, tmp_path):
        client = FakeGitHubClient()
        obs = _make_observer(client)
        out = obs("setup", {}, tmp_path, {})
        assert out["issue_number_present"] is True
        assert out["issue_number"] == 42
        assert out["repo_created"] is True
        assert out["request_branch"] == "main"
        assert out["request_commit_sha"] == VALID_SHA
        # Issue was actually created.
        assert client.created_issues[0]["title"].startswith("harness:")
        assert obs.state.issue_number == 42

    def test_passes_through_title_and_body(self, tmp_path):
        client = FakeGitHubClient()
        obs = _make_observer(client)
        obs(
            "setup",
            {"title": "custom title", "body": "custom body"},
            tmp_path,
            {},
        )
        assert client.created_issues[0]["title"] == "custom title"
        assert client.created_issues[0]["body"] == "custom body"

    def test_adds_label_if_create_did_not(self, tmp_path):
        # Simulate a client that creates issues without applying labels
        # (e.g. when labels param is ignored).
        class NoLabelClient(FakeGitHubClient):
            def create_issue(self, title, body, labels=None):
                issue = super().create_issue(title, body, labels=None)
                issue["labels"] = []  # drop labels
                return issue

        client = NoLabelClient()
        obs = _make_observer(client)
        obs("setup", {}, tmp_path, {})
        assert ("agent-task" in [lbl for _n, lbl in client.added_labels])

    def test_does_not_double_label(self, tmp_path):
        client = FakeGitHubClient()
        obs = _make_observer(client)
        obs("setup", {}, tmp_path, {})
        # create_issue already attached the label; add_label should not
        # be invoked.
        assert client.added_labels == []

    def test_raises_when_branch_missing(self, tmp_path):
        client = FakeGitHubClient(head_sha=None)
        client.branches = {}
        obs = _make_observer(client)
        with pytest.raises(RuntimeError, match="branch does not exist"):
            obs("setup", {}, tmp_path, {})

    def test_tolerates_add_label_failure(self, tmp_path):
        """If add_label raises (insufficient perms etc.) we don't blow up."""

        class NoLabelClient(FakeGitHubClient):
            def create_issue(self, title, body, labels=None):
                issue = super().create_issue(title, body, labels=None)
                issue["labels"] = []
                return issue

            def add_label(self, number, label):
                raise PermissionError("nope")

        client = NoLabelClient()
        obs = _make_observer(client)
        # Should not raise; the workflow's lock-and-sweep will retry.
        obs("setup", {}, tmp_path, {})


# ---------------------------------------------------------------------------
# invoke phase
# ---------------------------------------------------------------------------
class TestInvokePhase:
    def test_requires_setup_to_have_run(self, tmp_path):
        obs = _make_observer(FakeGitHubClient())
        with pytest.raises(RuntimeError, match="setup phase has not run"):
            obs("invoke", {}, tmp_path, {})

    def test_posts_envelope_and_observes_completion(self, tmp_path):
        client = FakeGitHubClient()
        obs = _make_observer(client)
        obs("setup", {}, tmp_path, {})
        # Pre-stage the comment's terminal body. Posting via add_comment
        # records the initial request body; we then simulate the workflow
        # updating it to terminal *before* the first poll fires.
        def script(call_idx, comment_id):
            # On first poll, body is "running"; on second, "completed".
            if call_idx == 1:
                env = envelopes.build_request(
                    command="echo",
                    args={"message": "hi"},
                    branch="main",
                    commit_sha=VALID_SHA,
                    subagent_id="harness-batch-job",
                    submitted_at="2026-05-17T00:00:00Z",
                )
                env["run_status"] = "running"
                return envelopes.serialize(env)
            env = envelopes.build_request(
                command="echo",
                args={"message": "hi"},
                branch="main",
                commit_sha=VALID_SHA,
                subagent_id="harness-batch-job",
                submitted_at="2026-05-17T00:00:00Z",
            )
            env["run_status"] = "completed"
            env["summary"] = {"echoed_args": {"message": "hi"}, "message": "hi"}
            return envelopes.serialize(env)

        client.get_comment_script = script
        out = obs("invoke", {"args": {"message": "hi"}}, tmp_path, {})
        assert out["batch_job_comment_present"] is True
        assert out["envelope_run_status"] == "completed"
        assert out["terminal_envelope_parsed"] is True
        # Two polls fired (running, then completed).
        assert client.get_comment_calls == 2

    def test_times_out_returns_none_terminal(self, tmp_path):
        client = FakeGitHubClient()
        obs = _make_observer(client, poll_timeout_s=3.0)
        obs("setup", {}, tmp_path, {})
        # The comment stays in its initial (no run_status) form forever.
        out = obs("invoke", {}, tmp_path, {})
        # Without a terminal envelope, run_status is None.
        assert out["envelope_run_status"] is None
        assert out["terminal_envelope_parsed"] is False

    def test_tolerates_trailing_prose_in_body(self, tmp_path):
        client = FakeGitHubClient()
        obs = _make_observer(client)
        obs("setup", {}, tmp_path, {})

        def script(call_idx, comment_id):
            env = envelopes.build_request(
                command="echo",
                args={},
                branch="main",
                commit_sha=VALID_SHA,
                subagent_id="harness-batch-job",
                submitted_at="2026-05-17T00:00:00Z",
            )
            env["run_status"] = "completed"
            env["summary"] = {"echoed_args": {}, "message": "hi"}
            return envelopes.serialize(env) + "\n\n_Generated by Claude Code_"

        client.get_comment_script = script
        out = obs("invoke", {}, tmp_path, {})
        assert out["envelope_run_status"] == "completed"


# ---------------------------------------------------------------------------
# verify phase
# ---------------------------------------------------------------------------
class TestVerifyPhase:
    def test_requires_invoke_to_have_run(self, tmp_path):
        obs = _make_observer(FakeGitHubClient())
        with pytest.raises(RuntimeError, match="invoke phase has not run"):
            obs("verify", {}, tmp_path, {})

    def test_surfaces_terminal_fields_for_completed(self, tmp_path):
        obs = _make_observer(FakeGitHubClient())
        obs.state.terminal_envelope = {
            "run_status": "completed",
            "summary": {"stdout": "ok", "exit_code": 0},
        }
        out = obs("verify", {}, tmp_path, {})
        assert out["envelope_run_status"] == "completed"
        assert out["error_kind_absent"] is True
        assert out["summary_keys_present"] == ["exit_code", "stdout"]

    def test_surfaces_error_kind(self, tmp_path):
        obs = _make_observer(FakeGitHubClient())
        obs.state.terminal_envelope = {
            "run_status": "error",
            "summary": {"error_kind": "X", "error_detail": "y"},
            "error_kind": "X",
        }
        out = obs("verify", {}, tmp_path, {})
        assert out["error_kind_absent"] is False
        assert out["error_kind"] == "X"

    def test_missing_summary_yields_empty_keys(self, tmp_path):
        obs = _make_observer(FakeGitHubClient())
        obs.state.terminal_envelope = {"run_status": "completed"}
        out = obs("verify", {}, tmp_path, {})
        assert out["summary_keys_present"] == []


# ---------------------------------------------------------------------------
# unknown phase
# ---------------------------------------------------------------------------
class TestUnknownPhase:
    def test_unknown_phase_raises(self, tmp_path):
        obs = _make_observer(FakeGitHubClient())
        with pytest.raises(ValueError, match="unknown phase"):
            obs("weird", {}, tmp_path, {})


# ---------------------------------------------------------------------------
# factory
# ---------------------------------------------------------------------------
class TestFactory:
    def test_supported_scenarios_includes_batch_job(self):
        assert "batch-job-happy-path" in live_observe.supported_scenarios()

    def test_make_observer_returns_batch_job_observer(self):
        obs = live_observe.make_observer(
            "batch-job-happy-path",
            github_client=FakeGitHubClient(),
            agent_login="alice",
        )
        assert isinstance(obs, live_observe.BatchJobObserver)

    def test_make_observer_unknown_raises(self):
        with pytest.raises(KeyError):
            live_observe.make_observer("not-a-scenario")
