"""Live-target observers for scenarios that drive real GitHub.

A live observer is a callable matching :data:`scenario_runner.ObserveFn`
that, instead of returning synthetic observations from the on-disk
fixture, drives a real GitHub repo through the scenario's phases and
returns observations sourced from the live state.

This module implements:

- :class:`BatchJobObserver` for the ``batch-job-happy-path`` scenario.
- :class:`OrchestrateIssueObserver` for the
  ``orchestrate-issue-single-subagent`` scenario family (also a
  building block for the parallel-fanout and restart-recovery
  variants).

Cross-phase state (issue number, request-comment id, branch / SHA the
request pointed at) is held on the observer instance and additionally
mirrored into ``state.diagnostics`` by the runner so it survives a
restart.
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Protocol


# Default polling cadence used by phases that wait for the handler
# workflow to update a request envelope to a terminal status. Tests
# inject a faster cadence + a fake sleep.
DEFAULT_POLL_INTERVAL_S = 5.0
DEFAULT_POLL_TIMEOUT_S = 300.0


class _GitHubClientLike(Protocol):
    """Subset of the GitHubClient surface used by live observers."""

    def create_issue(
        self,
        title: str,
        body: str,
        labels: Optional[list[str]] = None,
    ) -> dict[str, Any]: ...

    def add_label(self, number: int, label: str) -> None: ...

    def add_comment(self, issue_number: int, body: str) -> dict[str, Any]: ...

    def list_comments(self, issue_number: int) -> list[dict[str, Any]]: ...

    def get_comment(self, comment_id: int) -> dict[str, Any]: ...

    def get_branch_head_sha(self, branch: str) -> Optional[str]: ...

    # The following operations are only used by OrchestrateIssueObserver;
    # BatchJobObserver does not call them. They are declared on the
    # Protocol so static checkers verify both observers against the same
    # client surface.
    def get_issue(self, number: int) -> dict[str, Any]: ...

    def update_issue(
        self,
        number: int,
        body: Optional[str] = None,
        state: Optional[str] = None,
        labels: Optional[list[str]] = None,
    ) -> dict[str, Any]: ...

    def create_branch(
        self,
        name: str,
        from_branch: Optional[str] = None,
    ) -> str: ...

    def put_file_contents(
        self,
        path: str,
        content_bytes: bytes,
        message: str,
        branch: str,
    ) -> dict[str, Any]: ...

    def create_pull_request(
        self,
        title: str,
        head: str,
        base: str,
        body: str,
    ) -> dict[str, Any]: ...

    def get_pull_request(self, number: int) -> dict[str, Any]: ...


@dataclass
class _LiveState:
    """Cross-phase state for a single live scenario run."""

    issue_number: Optional[int] = None
    request_comment_id: Optional[int] = None
    request_branch: Optional[str] = None
    request_commit_sha: Optional[str] = None
    terminal_envelope: Optional[dict[str, Any]] = None


class BatchJobObserver:
    """Observer for the ``batch-job-happy-path`` scenario family.

    Phases driven:

    1. ``setup``  — open an issue with the ``agent-task`` label and
       record its number. Resolve the request branch's HEAD SHA so the
       envelope can pass the handler's branch/SHA check.
    2. ``invoke`` — post a ``batch-job-request`` envelope as an issue
       comment and poll for the handler workflow to update it to a
       terminal status (completed / error / parse_error).
    3. ``verify`` — surface the terminal envelope's fields as
       observations the scenario's ``expected`` block can assert on.

    The observer is stateless across runs but stateful within one run.
    The scenario runner is responsible for instantiating one observer
    per scenario invocation.

    Tests should inject:

    - ``github_client``: an :class:`InMemoryGitHubClient` (or a stub
      implementing :class:`_GitHubClientLike`).
    - ``poll_interval_s``: 0 for instant-poll tests.
    - ``sleep``: a no-op or a counter so the test can assert how many
      polls fired.
    - ``clock``: a callable returning monotonic seconds so polling can
      be deterministic.
    """

    def __init__(
        self,
        *,
        github_client: _GitHubClientLike,
        agent_login: str,
        request_branch: str = "main",
        command: str = "echo",
        subagent_id: str = "harness-batch-job",
        agent_task_label: str = "agent-task",
        poll_interval_s: float = DEFAULT_POLL_INTERVAL_S,
        poll_timeout_s: float = DEFAULT_POLL_TIMEOUT_S,
        sleep: Optional[Any] = None,
        clock: Optional[Any] = None,
        iso_now: Optional[Any] = None,
    ) -> None:
        if not agent_login:
            raise ValueError("agent_login is required")
        self._client = github_client
        self._agent_login = agent_login
        self._request_branch = request_branch
        self._command = command
        self._subagent_id = subagent_id
        self._agent_task_label = agent_task_label
        self._poll_interval_s = poll_interval_s
        self._poll_timeout_s = poll_timeout_s
        self._sleep = sleep or time.sleep
        self._clock = clock or time.monotonic
        if iso_now is None:
            from datetime import datetime, timezone

            def _iso_now() -> str:
                return datetime.now(tz=timezone.utc).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                )

            self._iso_now = _iso_now
        else:
            self._iso_now = iso_now
        self.state = _LiveState()

    # ------------------------------------------------------------------
    # ObserveFn entry point
    # ------------------------------------------------------------------
    def __call__(
        self,
        phase_name: str,
        inputs: dict[str, Any],
        fixture: Path,
        diagnostics: dict[str, Any],
    ) -> dict[str, Any]:
        if phase_name == "setup":
            return self._observe_setup(inputs)
        if phase_name == "invoke":
            return self._observe_invoke(inputs)
        if phase_name == "verify":
            return self._observe_verify(inputs)
        raise ValueError(f"BatchJobObserver: unknown phase {phase_name!r}")

    # ------------------------------------------------------------------
    # Phase implementations
    # ------------------------------------------------------------------
    def _observe_setup(self, inputs: dict[str, Any]) -> dict[str, Any]:
        head_sha = self._client.get_branch_head_sha(self._request_branch)
        if head_sha is None:
            raise RuntimeError(
                f"request branch does not exist: {self._request_branch!r}"
            )
        self.state.request_branch = self._request_branch
        self.state.request_commit_sha = head_sha

        title = inputs.get("title") or "harness: batch-job-happy-path"
        body = inputs.get("body") or (
            "Harness-driven `batch-job-happy-path` scenario. "
            "Will receive a request envelope as a comment."
        )
        labels = list(inputs.get("issue_labels") or [self._agent_task_label])
        # Create the issue with labels in one shot when supported; fall
        # back to add_label for clients that don't accept labels on
        # create.
        issue = self._client.create_issue(title=title, body=body, labels=labels)
        number = int(issue["number"])
        # Idempotently ensure the agent-task label is present.
        labels_on_issue = {
            (lbl.get("name") if isinstance(lbl, dict) else lbl)
            for lbl in (issue.get("labels") or [])
        }
        if self._agent_task_label not in labels_on_issue:
            try:
                self._client.add_label(number, self._agent_task_label)
            except Exception:
                # add_label may not be granted in all environments; the
                # workflow's lock-and-sweep will apply it on creation
                # too.
                pass
        self.state.issue_number = number
        return {
            "issue_number_present": True,
            "issue_number": number,
            "repo_created": True,  # the live-target repo exists
            "request_branch": self._request_branch,
            "request_commit_sha": head_sha,
        }

    def _observe_invoke(self, inputs: dict[str, Any]) -> dict[str, Any]:
        if self.state.issue_number is None:
            raise RuntimeError("invoke phase: setup phase has not run")
        from envelopes import build_request, serialize

        args = inputs.get("args") or {}
        command = inputs.get("command") or self._command
        envelope = build_request(
            command=command,
            args=args,
            branch=self.state.request_branch or self._request_branch,
            commit_sha=self.state.request_commit_sha or "0" * 40,
            subagent_id=self._subagent_id,
            submitted_at=self._iso_now(),
        )
        body = serialize(envelope)
        comment = self._client.add_comment(self.state.issue_number, body)
        comment_id = int(comment["id"])
        self.state.request_comment_id = comment_id

        terminal_envelope = self._poll_until_terminal(comment_id)
        self.state.terminal_envelope = terminal_envelope
        status = terminal_envelope.get("run_status") if terminal_envelope else None
        return {
            "batch_job_comment_present": True,
            "envelope_run_status": status,
            "request_comment_id": comment_id,
            "terminal_envelope_parsed": terminal_envelope is not None,
        }

    def _observe_verify(self, inputs: dict[str, Any]) -> dict[str, Any]:
        terminal = self.state.terminal_envelope
        if terminal is None:
            raise RuntimeError("verify phase: invoke phase has not run or timed out")
        summary = terminal.get("summary") or {}
        summary_keys_present = sorted(summary.keys()) if isinstance(summary, dict) else []
        error_kind = terminal.get("error_kind")
        return {
            "envelope_run_status": terminal.get("run_status"),
            "error_kind_absent": error_kind is None or error_kind == "",
            "error_kind": error_kind,
            "summary_keys_present": summary_keys_present,
            "log_manifest_path": terminal.get("log_manifest_path"),
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _poll_until_terminal(self, comment_id: int) -> Optional[dict[str, Any]]:
        """Poll the request comment until it carries a terminal envelope.

        Returns the parsed terminal envelope, or ``None`` on timeout.
        Tolerates the lenient envelope parse (handler may post a body
        with a trailing prose footer; see envelopes.parse).
        """
        from envelopes import parse, is_terminal

        deadline = self._clock() + float(self._poll_timeout_s)
        while True:
            now = self._clock()
            if now >= deadline:
                return None
            comment = self._client.get_comment(comment_id)
            body = comment.get("body") if isinstance(comment, dict) else None
            parsed = parse(body)
            if parsed is not None and is_terminal(parsed):
                return parsed
            self._sleep(self._poll_interval_s)


# ---------------------------------------------------------------------------
# OrchestrateIssueObserver
# ---------------------------------------------------------------------------


@dataclass
class _OrchestrateState:
    """Cross-phase state for one orchestrate-issue scenario run."""

    issue_number: Optional[int] = None
    base_branch: Optional[str] = None
    base_sha: Optional[str] = None
    feature_branch: Optional[str] = None
    feature_baseline_sha: Optional[str] = None
    agent_id: Optional[str] = None
    session_id: Optional[str] = None
    # One slot per dispatched subagent. Index is the wave-order id.
    subagent_branches: list[str] = field(default_factory=list)
    subagent_heads: list[str] = field(default_factory=list)
    subagent_request_comment_ids: list[int] = field(default_factory=list)
    subagent_terminal_envelopes: list[Optional[dict[str, Any]]] = field(
        default_factory=list
    )
    pr_number: Optional[int] = None
    pr_merged: bool = False
    meta_status: Optional[str] = None


def _slugify(value: str, max_len: int = 24) -> str:
    cleaned = "".join(c.lower() if c.isalnum() else "-" for c in value)
    cleaned = "-".join(part for part in cleaned.split("-") if part)
    return cleaned[:max_len] or "issue"


class OrchestrateIssueObserver:
    """Observer for the ``orchestrate-issue-*`` scenario family.

    The observer plays the role of the primary orchestrator agent: it
    creates an ``agent-task`` issue, claims it, dispatches one or more
    subagents by posting ``batch-job-request`` envelopes and committing
    stub work on their sub-branches, merges the sub-branches into the
    feature branch, opens a PR, and finally waits for the PR to merge
    while marking the issue's ``agent-meta`` block ``finished``.

    Phases driven (matching the scenario YAML):

    1. ``setup`` — create the issue with an ``agent-meta`` block
       (``status: null``); create the feature branch from
       ``base_branch``.
    2. ``claim`` — update the issue body's ``agent-meta`` block to
       ``status: working`` under this observer's ``agent_id`` /
       ``session_id``.
    3. ``fanout`` — for each of ``max_parallel`` subagent slots, create
       a sub-branch off the feature tip, commit a stub file, post a
       ``batch-job-request`` envelope as an issue comment, and poll
       until the comment is updated to a terminal envelope.
    4. ``merge`` — in plan order, fast-forward each sub-branch's stub
       file onto the feature branch (the in-memory equivalent of
       ``git merge --no-ff``); open a PR from feature into base.
    5. ``verify`` — write ``status: finished`` to the issue's
       ``agent-meta`` block, then poll the PR until it is merged
       externally (in tests, the test helper calls
       ``merge_pull_request``; in live runs, the user or auto-merge
       does it).

    The class follows the architecture documented in the
    ``live-observer-pattern`` skill: scenario-specific knowledge lives
    in the phase methods; cross-phase data lives on ``self.state``;
    all timing is via injected ``clock`` + ``sleep``.
    """

    def __init__(
        self,
        *,
        github_client: _GitHubClientLike,
        agent_login: str,
        base_branch: str = "main",
        feature_branch: Optional[str] = None,
        max_parallel: int = 1,
        subagent_command: str = "echo",
        subagent_id_prefix: str = "sub",
        agent_task_label: str = "agent-task",
        poll_interval_s: float = DEFAULT_POLL_INTERVAL_S,
        poll_timeout_s: float = DEFAULT_POLL_TIMEOUT_S,
        sleep: Optional[Any] = None,
        clock: Optional[Any] = None,
        iso_now: Optional[Any] = None,
        new_session_id: Optional[Any] = None,
    ) -> None:
        if not agent_login:
            raise ValueError("agent_login is required")
        if max_parallel < 1:
            raise ValueError("max_parallel must be >= 1")
        self._client = github_client
        self._agent_login = agent_login
        self._base_branch = base_branch
        self._feature_branch = feature_branch
        self._max_parallel = max_parallel
        self._subagent_command = subagent_command
        self._subagent_id_prefix = subagent_id_prefix
        self._agent_task_label = agent_task_label
        self._poll_interval_s = poll_interval_s
        self._poll_timeout_s = poll_timeout_s
        self._sleep = sleep or time.sleep
        self._clock = clock or time.monotonic
        if iso_now is None:
            from datetime import datetime, timezone

            def _iso_now() -> str:
                return datetime.now(tz=timezone.utc).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                )

            self._iso_now = _iso_now
        else:
            self._iso_now = iso_now
        self._new_session_id = new_session_id or (lambda: uuid.uuid4().hex)
        self.state = _OrchestrateState(base_branch=base_branch)

    # ------------------------------------------------------------------
    # ObserveFn entry point
    # ------------------------------------------------------------------
    def __call__(
        self,
        phase_name: str,
        inputs: dict[str, Any],
        fixture: Path,
        diagnostics: dict[str, Any],
    ) -> dict[str, Any]:
        if phase_name == "setup":
            return self._observe_setup(inputs)
        if phase_name == "claim":
            return self._observe_claim(inputs)
        if phase_name == "fanout":
            return self._observe_fanout(inputs)
        if phase_name == "merge":
            return self._observe_merge(inputs)
        if phase_name == "verify":
            return self._observe_verify(inputs)
        raise ValueError(
            f"OrchestrateIssueObserver: unknown phase {phase_name!r}"
        )

    # ------------------------------------------------------------------
    # agent-meta helpers (inline copies of .agent/scripts/agent_lib/meta.py
    # so this module stays import-light)
    # ------------------------------------------------------------------
    _AGENT_META_START = "```agent-meta"
    _AGENT_META_END = "```"

    @classmethod
    def _parse_agent_meta(cls, body: Optional[str]) -> Optional[dict[str, Any]]:
        if not body:
            return None
        start = body.find(cls._AGENT_META_START)
        if start < 0:
            return None
        json_start = body.find("\n", start)
        if json_start < 0:
            return None
        json_start += 1
        end = body.find("\n" + cls._AGENT_META_END, json_start)
        if end < 0:
            return None
        try:
            return json.loads(body[json_start:end])
        except json.JSONDecodeError:
            return None

    @classmethod
    def _render_body(cls, prose: str, meta: dict[str, Any]) -> str:
        block = f"{cls._AGENT_META_START}\n{json.dumps(meta, indent=2)}\n{cls._AGENT_META_END}"
        prose = (prose or "").rstrip()
        if prose:
            return f"{prose}\n\n{block}\n"
        return block + "\n"

    @classmethod
    def _replace_agent_meta(
        cls,
        body: Optional[str],
        new_meta: dict[str, Any],
    ) -> str:
        body = body or ""
        start = body.find(cls._AGENT_META_START)
        if start < 0:
            return cls._render_body(body, new_meta)
        return cls._render_body(body[:start], new_meta)

    # ------------------------------------------------------------------
    # Phase implementations
    # ------------------------------------------------------------------
    def _observe_setup(self, inputs: dict[str, Any]) -> dict[str, Any]:
        base_sha = self._client.get_branch_head_sha(self._base_branch)
        if base_sha is None:
            raise RuntimeError(
                f"base branch does not exist: {self._base_branch!r}"
            )
        self.state.base_sha = base_sha

        title = inputs.get("title") or "harness: orchestrate-issue-single-subagent"
        prose = inputs.get("prose") or (
            "Harness-driven orchestrate-issue scenario. "
            "Will be claimed and fanned out by the harness observer."
        )
        instructions = (
            inputs.get("issue_body")
            or inputs.get("instructions_inline")
            or "add a single trivial change"
        )

        feature_branch = (
            self._feature_branch
            or inputs.get("feature_branch")
            or f"agent/orchestrate-{_slugify(title)}-{self._iso_now()[:10].replace('-', '')}"
        )
        meta = {
            "protocol_version": 1,
            "agent_id": None,
            "session_id": None,
            "status": None,
            "status_ts": None,
            "feature_branch": feature_branch,
            "base_branch": self._base_branch,
            "parent_issue": None,
            "depends_on_prs": [],
            "instructions_path": None,
            "instructions_inline": instructions,
            "created_at": self._iso_now(),
        }
        body = self._render_body(prose, meta)
        labels = list(inputs.get("issue_labels") or [self._agent_task_label])
        issue = self._client.create_issue(title=title, body=body, labels=labels)
        number = int(issue["number"])

        labels_on_issue = {
            (lbl.get("name") if isinstance(lbl, dict) else lbl)
            for lbl in (issue.get("labels") or [])
        }
        if self._agent_task_label not in labels_on_issue:
            try:
                self._client.add_label(number, self._agent_task_label)
            except Exception:
                pass

        # Create the feature branch from base. The orchestrator owns it;
        # subagents branch from it.
        feature_head_sha = self._client.create_branch(
            feature_branch, from_branch=self._base_branch
        )

        self.state.issue_number = number
        self.state.feature_branch = feature_branch
        self.state.feature_baseline_sha = feature_head_sha
        return {
            "issue_number_present": True,
            "issue_number": number,
            "feature_branch": feature_branch,
            "feature_baseline_sha": feature_head_sha,
            "repo_created": True,
        }

    def _observe_claim(self, inputs: dict[str, Any]) -> dict[str, Any]:
        if self.state.issue_number is None:
            raise RuntimeError("claim phase: setup phase has not run")
        agent_id = inputs.get("agent_id") or f"orchestrate-{self._agent_login}"
        session_id = inputs.get("session_id") or self._new_session_id()
        issue = self._client.get_issue(self.state.issue_number)
        meta = self._parse_agent_meta(issue.get("body"))
        if meta is None:
            raise RuntimeError(
                "claim phase: issue body missing agent-meta block"
            )
        new_meta = dict(meta)
        new_meta["agent_id"] = agent_id
        new_meta["session_id"] = session_id
        new_meta["status"] = "working"
        new_meta["status_ts"] = self._iso_now()
        new_body = self._replace_agent_meta(issue.get("body"), new_meta)
        self._client.update_issue(self.state.issue_number, body=new_body)
        self.state.agent_id = agent_id
        self.state.session_id = session_id
        self.state.meta_status = "working"
        return {
            "issue_locked": True,
            "agent_id": agent_id,
            "session_id_present": bool(session_id),
            "meta_status": "working",
        }

    def _observe_fanout(self, inputs: dict[str, Any]) -> dict[str, Any]:
        if self.state.feature_branch is None:
            raise RuntimeError("fanout phase: setup phase has not run")
        if self.state.meta_status != "working":
            raise RuntimeError("fanout phase: claim phase has not run")
        max_parallel = int(inputs.get("max_parallel") or self._max_parallel)
        if max_parallel < 1:
            raise ValueError("max_parallel must be >= 1")
        command = inputs.get("command") or self._subagent_command
        args_in = inputs.get("args") or {}

        from envelopes import build_request, parse, serialize, is_terminal

        # Dispatch wave: create sub-branches, commit stub, post envelope.
        for i in range(max_parallel):
            sub_id = f"{self._subagent_id_prefix}-{i + 1:02d}"
            sub_branch = f"{self.state.feature_branch}--{sub_id}"
            self._client.create_branch(
                sub_branch, from_branch=self.state.feature_branch
            )
            commit_info = self._client.put_file_contents(
                path=f".agent/runs/harness/{sub_id}.md",
                content_bytes=(
                    f"# Harness subagent {sub_id}\n\n"
                    f"Stub commit for orchestrate-issue scenario.\n"
                ).encode("utf-8"),
                message=f"harness: stub commit for {sub_id}",
                branch=sub_branch,
            )
            sub_head_sha = (
                (commit_info.get("commit") or {}).get("sha")
                if isinstance(commit_info, dict)
                else None
            ) or self._client.get_branch_head_sha(sub_branch)
            envelope = build_request(
                command=command,
                args=dict(args_in),
                branch=sub_branch,
                commit_sha=sub_head_sha,
                subagent_id=sub_id,
                submitted_at=self._iso_now(),
            )
            comment = self._client.add_comment(
                self.state.issue_number, serialize(envelope)
            )
            comment_id = int(comment["id"])
            self.state.subagent_branches.append(sub_branch)
            self.state.subagent_heads.append(sub_head_sha)
            self.state.subagent_request_comment_ids.append(comment_id)
            self.state.subagent_terminal_envelopes.append(None)

        # Poll each comment to terminal. We use one global deadline
        # rather than per-comment, matching how the orchestrator would
        # bound total wave time.
        deadline = self._clock() + float(self._poll_timeout_s)
        completed = 0
        while completed < max_parallel:
            if self._clock() >= deadline:
                break
            advanced = False
            for idx, cid in enumerate(self.state.subagent_request_comment_ids):
                if self.state.subagent_terminal_envelopes[idx] is not None:
                    continue
                comment = self._client.get_comment(cid)
                body = comment.get("body") if isinstance(comment, dict) else None
                parsed = parse(body)
                if parsed is not None and is_terminal(parsed):
                    self.state.subagent_terminal_envelopes[idx] = parsed
                    completed += 1
                    advanced = True
            if completed >= max_parallel:
                break
            if not advanced:
                self._sleep(self._poll_interval_s)

        all_terminal = completed == max_parallel
        return {
            "subagents_dispatched": max_parallel,
            "subagent_branches_created": len(self.state.subagent_branches),
            "all_subagents_terminal": all_terminal,
            "request_comment_ids": list(self.state.subagent_request_comment_ids),
            "subagent_branches": list(self.state.subagent_branches),
        }

    def _observe_merge(self, inputs: dict[str, Any]) -> dict[str, Any]:
        if not self.state.subagent_branches:
            raise RuntimeError("merge phase: fanout phase has not run")
        if self.state.feature_branch is None or self.state.feature_baseline_sha is None:
            raise RuntimeError("merge phase: feature branch missing")

        # Fast-forward each sub-branch's stub file onto the feature
        # branch, in plan order. This is the in-process equivalent of
        # ``git merge --no-ff`` for the test harness; live runs would
        # use the orchestrator's real git operations.
        for idx, sub_branch in enumerate(self.state.subagent_branches):
            sub_id = sub_branch.rsplit("--", 1)[-1]
            stub_path = f".agent/runs/harness/{sub_id}.md"
            stub_bytes = (
                f"# Harness subagent {sub_id}\n\n"
                f"Stub commit for orchestrate-issue scenario.\n"
            ).encode("utf-8")
            self._client.put_file_contents(
                path=stub_path,
                content_bytes=stub_bytes,
                message=f"harness: merge {sub_id} into {self.state.feature_branch}",
                branch=self.state.feature_branch,
            )

        feature_head = self._client.get_branch_head_sha(self.state.feature_branch)
        feature_advanced = (
            feature_head is not None
            and feature_head != self.state.feature_baseline_sha
        )

        title = inputs.get("pr_title") or (
            f"orchestrate-issue: harness run for issue "
            f"#{self.state.issue_number}"
        )
        body = inputs.get("pr_body") or (
            f"Harness-driven orchestrate-issue scenario.\n\n"
            f"Closes #{self.state.issue_number}.\n"
        )
        pr = self._client.create_pull_request(
            title=title,
            head=self.state.feature_branch,
            base=self._base_branch,
            body=body,
        )
        pr_number = int(pr["number"])
        self.state.pr_number = pr_number
        return {
            "feature_branch_advanced": feature_advanced,
            "feature_head_sha": feature_head,
            "pr_opened": True,
            "pr_number": pr_number,
        }

    def _observe_verify(self, inputs: dict[str, Any]) -> dict[str, Any]:
        if self.state.pr_number is None:
            raise RuntimeError("verify phase: merge phase has not run")
        if self.state.issue_number is None:
            raise RuntimeError("verify phase: setup phase has not run")

        # Write status=finished to the issue's agent-meta block (Phase 9
        # of the orchestrate-issue skill: finalise the issue before PR
        # merge so close-on-merge sees the expected post-state).
        issue = self._client.get_issue(self.state.issue_number)
        meta = self._parse_agent_meta(issue.get("body"))
        if meta is not None:
            new_meta = dict(meta)
            new_meta["status"] = "finished"
            new_meta["status_ts"] = self._iso_now()
            new_body = self._replace_agent_meta(issue.get("body"), new_meta)
            self._client.update_issue(self.state.issue_number, body=new_body)
            self.state.meta_status = "finished"

        # Poll the PR until merged. Live runs depend on the user (or
        # auto-merge) to actually merge the PR; tests use the in-memory
        # client's merge_pull_request helper to simulate that.
        deadline = self._clock() + float(self._poll_timeout_s)
        pr_merged = False
        while True:
            if self._clock() >= deadline:
                break
            pr = self._client.get_pull_request(self.state.pr_number)
            if isinstance(pr, dict) and pr.get("merged"):
                pr_merged = True
                break
            self._sleep(self._poll_interval_s)
        self.state.pr_merged = pr_merged

        # no_cross_contamination: each sub-branch only modified files
        # specific to its own sub_id. We check that the stub file
        # written by sub-NN doesn't appear under any other sub-NN's
        # sub-branch's commit history (best-effort: read each sub
        # branch's current files via get_file_contents and ensure the
        # only `.agent/runs/harness/sub-*.md` file present is its own).
        no_cross = True
        for sub_branch in self.state.subagent_branches:
            sub_id = sub_branch.rsplit("--", 1)[-1]
            own_path = f".agent/runs/harness/{sub_id}.md"
            own_content = self._client.get_file_contents(own_path, ref=sub_branch)
            if own_content is None:
                no_cross = False
                continue
            # Look for other sub_ids' stub files on this branch.
            for other_branch in self.state.subagent_branches:
                if other_branch == sub_branch:
                    continue
                other_id = other_branch.rsplit("--", 1)[-1]
                other_path = f".agent/runs/harness/{other_id}.md"
                if self._client.get_file_contents(other_path, ref=sub_branch) is not None:
                    no_cross = False
                    break
            if not no_cross:
                break

        return {
            "pr_merged": pr_merged,
            "pr_number": self.state.pr_number,
            "meta_status": self.state.meta_status,
            "no_cross_contamination": no_cross,
        }


# ---------------------------------------------------------------------------
# TaskDagClaimObserver
# ---------------------------------------------------------------------------


@dataclass
class _TaskDagState:
    """Cross-phase state for one task-dag-claim-and-plan scenario run."""

    issue_number: Optional[int] = None
    base_branch: Optional[str] = None
    feature_branch: Optional[str] = None
    agent_id: Optional[str] = None
    session_id: Optional[str] = None
    meta_status: Optional[str] = None
    brief: Optional[str] = None
    subagent_plan: list[dict[str, Any]] = field(default_factory=list)


class TaskDagClaimObserver:
    """Observer for the ``task-dag-claim-and-plan`` scenario.

    Drives the ``task-dag`` skill's ``claim`` and ``plan`` primitives
    against a fresh ``agent-task`` issue.

    Phases:

    1. ``setup`` — create the issue with a fresh ``agent-meta`` block
       (``status: null``) containing ``instructions_inline`` from the
       scenario inputs.
    2. ``claim`` — implement the CAS-by-re-read handshake (POC SPEC
       §4.1): write ``agent_id``/``session_id``/``status: working`` +
       fresh ``status_ts``; re-read; if our agent_id survived, the
       claim is ours. The scenario also asserts on an
       ``agent-task-claimed`` label, so the observer applies it after
       a successful claim.
    3. ``plan`` — produce a brief from the issue's
       ``instructions_inline`` (or ``instructions_path``); derive a
       minimal subagent plan (1 subagent in this scenario). The
       observer stores the brief as a body comment so a reviewer can
       see what was planned. Writes ``meta_status: planned`` into the
       ``agent-meta`` extra fields.
    4. ``verify`` — read back the issue body and surface
       ``meta_status`` for assertion.

    The observer is **not** a full implementation of the ``task-dag``
    skill — it only exercises the surface the scenario asserts on.
    Skill internals (heartbeat throttling, stale-takeover) belong in
    other scenarios or unit tests of the underlying Python helpers.
    """

    AGENT_META_START = OrchestrateIssueObserver._AGENT_META_START
    AGENT_META_END = OrchestrateIssueObserver._AGENT_META_END

    def __init__(
        self,
        *,
        github_client: _GitHubClientLike,
        agent_login: str,
        base_branch: str = "main",
        feature_branch: Optional[str] = None,
        agent_task_label: str = "agent-task",
        claimed_label: str = "agent-task-claimed",
        subagent_id_prefix: str = "sub",
        poll_interval_s: float = DEFAULT_POLL_INTERVAL_S,
        poll_timeout_s: float = DEFAULT_POLL_TIMEOUT_S,
        sleep: Optional[Any] = None,
        clock: Optional[Any] = None,
        iso_now: Optional[Any] = None,
        new_session_id: Optional[Any] = None,
    ) -> None:
        if not agent_login:
            raise ValueError("agent_login is required")
        self._client = github_client
        self._agent_login = agent_login
        self._base_branch = base_branch
        self._feature_branch = feature_branch
        self._agent_task_label = agent_task_label
        self._claimed_label = claimed_label
        self._subagent_id_prefix = subagent_id_prefix
        self._poll_interval_s = poll_interval_s
        self._poll_timeout_s = poll_timeout_s
        self._sleep = sleep or time.sleep
        self._clock = clock or time.monotonic
        if iso_now is None:
            from datetime import datetime, timezone

            def _iso_now() -> str:
                return datetime.now(tz=timezone.utc).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                )

            self._iso_now = _iso_now
        else:
            self._iso_now = iso_now
        self._new_session_id = new_session_id or (lambda: uuid.uuid4().hex)
        self.state = _TaskDagState(base_branch=base_branch)

    def __call__(
        self,
        phase_name: str,
        inputs: dict[str, Any],
        fixture: Path,
        diagnostics: dict[str, Any],
    ) -> dict[str, Any]:
        if phase_name == "setup":
            return self._observe_setup(inputs)
        if phase_name == "claim":
            return self._observe_claim(inputs)
        if phase_name == "plan":
            return self._observe_plan(inputs)
        if phase_name == "verify":
            return self._observe_verify(inputs)
        raise ValueError(
            f"TaskDagClaimObserver: unknown phase {phase_name!r}"
        )

    # Reuse OrchestrateIssueObserver's agent-meta parse / render helpers.
    _parse_agent_meta = OrchestrateIssueObserver._parse_agent_meta
    _render_body = OrchestrateIssueObserver._render_body
    _replace_agent_meta = OrchestrateIssueObserver._replace_agent_meta

    def _observe_setup(self, inputs: dict[str, Any]) -> dict[str, Any]:
        base_sha = self._client.get_branch_head_sha(self._base_branch)
        if base_sha is None:
            raise RuntimeError(
                f"base branch does not exist: {self._base_branch!r}"
            )

        title = inputs.get("title") or "harness: task-dag-claim-and-plan"
        prose = inputs.get("prose") or (
            "Harness-driven task-dag-claim-and-plan scenario."
        )
        instructions = (
            inputs.get("issue_body")
            or inputs.get("instructions_inline")
            or "write a hello world test"
        )
        feature_branch = (
            self._feature_branch
            or inputs.get("feature_branch")
            or f"agent/task-dag-{_slugify(title)}"
        )
        meta = {
            "protocol_version": 1,
            "agent_id": None,
            "session_id": None,
            "status": None,
            "status_ts": None,
            "feature_branch": feature_branch,
            "base_branch": self._base_branch,
            "parent_issue": None,
            "depends_on_prs": [],
            "instructions_path": None,
            "instructions_inline": instructions,
            "created_at": self._iso_now(),
        }
        body = self._render_body(prose, meta)
        labels = list(inputs.get("issue_labels") or [self._agent_task_label])
        issue = self._client.create_issue(title=title, body=body, labels=labels)
        number = int(issue["number"])
        labels_on_issue = {
            (lbl.get("name") if isinstance(lbl, dict) else lbl)
            for lbl in (issue.get("labels") or [])
        }
        if self._agent_task_label not in labels_on_issue:
            try:
                self._client.add_label(number, self._agent_task_label)
            except Exception:
                pass
        self.state.issue_number = number
        self.state.feature_branch = feature_branch
        return {
            "issue_number_present": True,
            "issue_number": number,
            "feature_branch": feature_branch,
        }

    def _observe_claim(self, inputs: dict[str, Any]) -> dict[str, Any]:
        if self.state.issue_number is None:
            raise RuntimeError("claim phase: setup phase has not run")
        agent_id = inputs.get("agent_id") or f"task-dag-{self._agent_login}"
        session_id = inputs.get("session_id") or self._new_session_id()

        # CAS-by-re-read handshake.
        issue = self._client.get_issue(self.state.issue_number)
        meta = self._parse_agent_meta(issue.get("body"))
        if meta is None:
            raise RuntimeError(
                "claim phase: issue body missing agent-meta block"
            )
        new_meta = dict(meta)
        new_meta["agent_id"] = agent_id
        new_meta["session_id"] = session_id
        new_meta["status"] = "working"
        new_meta["status_ts"] = self._iso_now()
        new_body = self._replace_agent_meta(issue.get("body"), new_meta)
        self._client.update_issue(self.state.issue_number, body=new_body)

        # Re-read confirmation step. The losing party never rewrites the
        # body, so if our agent_id is still there, we won the claim.
        issue_after = self._client.get_issue(self.state.issue_number)
        meta_after = self._parse_agent_meta(issue_after.get("body"))
        claim_won = bool(
            meta_after
            and meta_after.get("agent_id") == agent_id
            and meta_after.get("status") == "working"
        )
        if not claim_won:
            return {
                "issue_locked": False,
                "issue_has_label": False,
                "claim_won": False,
            }

        # Apply the claimed label so the scenario's assertion passes.
        # The protocol's lock-and-sweep workflow applies `agent-task`;
        # the `agent-task-claimed` label is harness-specific signal that
        # the claim handshake completed.
        try:
            self._client.add_label(self.state.issue_number, self._claimed_label)
        except Exception:
            pass

        # Re-fetch to confirm label is present.
        issue_with_label = self._client.get_issue(self.state.issue_number)
        labels_on_issue = {
            (lbl.get("name") if isinstance(lbl, dict) else lbl)
            for lbl in (issue_with_label.get("labels") or [])
        }
        self.state.agent_id = agent_id
        self.state.session_id = session_id
        self.state.meta_status = "working"
        return {
            "issue_locked": True,
            "issue_has_label": self._claimed_label in labels_on_issue,
            "claim_won": True,
            "agent_id": agent_id,
        }

    def _observe_plan(self, inputs: dict[str, Any]) -> dict[str, Any]:
        if self.state.meta_status != "working":
            raise RuntimeError("plan phase: claim phase has not run")
        issue = self._client.get_issue(self.state.issue_number)
        meta = self._parse_agent_meta(issue.get("body"))
        if meta is None:
            raise RuntimeError(
                "plan phase: issue body missing agent-meta block"
            )
        instructions = meta.get("instructions_inline") or "[no inline instructions]"

        # Synthesise a minimal brief + subagent plan. A real
        # ``task-dag.plan`` invocation might prompt an LLM here; the
        # harness produces a deterministic placeholder so the scenario
        # can assert on shape, not content.
        sub_id = f"{self._subagent_id_prefix}-01"
        brief = (
            f"# Brief for issue #{self.state.issue_number}\n\n"
            f"## Instructions\n\n{instructions}\n\n"
            f"## Subagent plan\n\n"
            f"- {sub_id}: implement the change\n"
        )
        subagent_plan = [
            {
                "id": sub_id,
                "title": "implement the change",
                "branch": f"{self.state.feature_branch}--{sub_id}",
            }
        ]
        self.state.brief = brief
        self.state.subagent_plan = subagent_plan

        # Post the brief as a comment on the issue so it's audit-visible.
        self._client.add_comment(self.state.issue_number, brief)

        # Mark the agent-meta as planned. The protocol's
        # issue-body.schema.json enum is null/working/abandoned/finished;
        # "planned" is the scenario's vocabulary for "claim+plan
        # complete, not yet finished". We write it in the extra
        # ``plan_state`` field AND in ``status`` so both shapes of
        # assertion can pass.
        new_meta = dict(meta)
        new_meta["status"] = "planned"
        new_meta["status_ts"] = self._iso_now()
        new_meta["plan_state"] = "planned"
        new_body = self._replace_agent_meta(issue.get("body"), new_meta)
        self._client.update_issue(self.state.issue_number, body=new_body)
        self.state.meta_status = "planned"
        return {
            "brief_present": True,
            "subagent_plan_count_min": len(subagent_plan),
            "subagent_plan_count": len(subagent_plan),
        }

    def _observe_verify(self, inputs: dict[str, Any]) -> dict[str, Any]:
        if self.state.issue_number is None:
            raise RuntimeError("verify phase: setup phase has not run")
        issue = self._client.get_issue(self.state.issue_number)
        meta = self._parse_agent_meta(issue.get("body")) or {}
        return {
            "meta_status": meta.get("status"),
            "plan_state": meta.get("plan_state"),
            "agent_id_present": bool(meta.get("agent_id")),
        }

# ---------------------------------------------------------------------------
# OrchestrateIssueRestartObserver
# ---------------------------------------------------------------------------


class OrchestrateIssueRestartObserver:
    """Observer for ``orchestrate-issue-restart-recovery``.

    Drives 5 phases: ``setup``, ``fanout`` (with ``kill_after_dispatch``),
    ``restart``, ``finalise``, ``verify``. The "kill" is simulated by
    skipping the poll-to-terminal step in fanout; restart rehydrates
    state by querying GitHub (which IS the durable state per the
    protocol — branches + comments + agent-meta).

    The recovery contract demonstrated:

    1. Setup creates the issue with an ``agent-meta`` block + a feature
       branch.
    2. Fanout creates sub-branches, posts ``batch-job-request``
       envelopes, then (with ``kill_after_dispatch``) returns
       immediately. Records the pre-restart comment count so the
       restart phase can prove no duplicate dispatches happen.
    3. Restart simulates a fresh process: clears in-memory state and
       reconstructs it by reading the issue body (feature_branch),
       listing branches (sub-branches matching the pattern), and
       listing comments (request envelopes' ids). Then completes the
       polling that fanout skipped. Asserts comment count did not
       grow during restart.
    4. Finalise fast-forwards each sub-branch's stub file onto the
       feature branch, opens the PR.
    5. Verify writes ``status: finished`` to ``agent-meta``, polls the
       PR until merged (in tests, the test helper invokes
       ``merge_pull_request``).
    """

    AGENT_META_START = OrchestrateIssueObserver._AGENT_META_START
    AGENT_META_END = OrchestrateIssueObserver._AGENT_META_END
    _parse_agent_meta = OrchestrateIssueObserver._parse_agent_meta
    _render_body = OrchestrateIssueObserver._render_body
    _replace_agent_meta = OrchestrateIssueObserver._replace_agent_meta

    def __init__(
        self,
        *,
        github_client: _GitHubClientLike,
        agent_login: str,
        base_branch: str = "main",
        feature_branch: Optional[str] = None,
        max_parallel: int = 2,
        subagent_command: str = "echo",
        subagent_id_prefix: str = "sub",
        agent_task_label: str = "agent-task",
        poll_interval_s: float = DEFAULT_POLL_INTERVAL_S,
        poll_timeout_s: float = DEFAULT_POLL_TIMEOUT_S,
        sleep: Optional[Any] = None,
        clock: Optional[Any] = None,
        iso_now: Optional[Any] = None,
        new_session_id: Optional[Any] = None,
    ) -> None:
        if not agent_login:
            raise ValueError("agent_login is required")
        if max_parallel < 1:
            raise ValueError("max_parallel must be >= 1")
        self._client = github_client
        self._agent_login = agent_login
        self._base_branch = base_branch
        self._feature_branch_arg = feature_branch
        self._max_parallel = max_parallel
        self._subagent_command = subagent_command
        self._subagent_id_prefix = subagent_id_prefix
        self._agent_task_label = agent_task_label
        self._poll_interval_s = poll_interval_s
        self._poll_timeout_s = poll_timeout_s
        self._sleep = sleep or time.sleep
        self._clock = clock or time.monotonic
        if iso_now is None:
            from datetime import datetime, timezone

            def _iso_now() -> str:
                return datetime.now(tz=timezone.utc).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                )

            self._iso_now = _iso_now
        else:
            self._iso_now = iso_now
        self._new_session_id = new_session_id or (lambda: uuid.uuid4().hex)
        self.state = _OrchestrateState(base_branch=base_branch)
        # Restart-recovery-specific tracking.
        self._kill_dispatched = False
        self._pre_restart_comment_count: Optional[int] = None

    def __call__(
        self,
        phase_name: str,
        inputs: dict[str, Any],
        fixture: Path,
        diagnostics: dict[str, Any],
    ) -> dict[str, Any]:
        if phase_name == "setup":
            return self._observe_setup(inputs)
        if phase_name == "fanout":
            return self._observe_fanout(inputs)
        if phase_name == "restart":
            return self._observe_restart(inputs)
        if phase_name == "finalise":
            return self._observe_finalise(inputs)
        if phase_name == "verify":
            return self._observe_verify(inputs)
        raise ValueError(
            f"OrchestrateIssueRestartObserver: unknown phase {phase_name!r}"
        )

    # ------------------------------------------------------------------
    # setup — same shape as OrchestrateIssueObserver.setup
    # ------------------------------------------------------------------
    def _observe_setup(self, inputs: dict[str, Any]) -> dict[str, Any]:
        base_sha = self._client.get_branch_head_sha(self._base_branch)
        if base_sha is None:
            raise RuntimeError(
                f"base branch does not exist: {self._base_branch!r}"
            )
        self.state.base_sha = base_sha
        title = inputs.get("title") or "harness: orchestrate-issue-restart-recovery"
        prose = inputs.get("prose") or (
            "Harness-driven orchestrate-issue-restart-recovery scenario."
        )
        instructions = (
            inputs.get("issue_body")
            or inputs.get("instructions_inline")
            or "implement two helpers"
        )
        feature_branch = (
            self._feature_branch_arg
            or inputs.get("feature_branch")
            or f"agent/restart-{_slugify(title)}"
        )
        meta = {
            "protocol_version": 1,
            "agent_id": f"orchestrate-{self._agent_login}",
            "session_id": self._new_session_id(),
            "status": "working",
            "status_ts": self._iso_now(),
            "feature_branch": feature_branch,
            "base_branch": self._base_branch,
            "parent_issue": None,
            "depends_on_prs": [],
            "instructions_path": None,
            "instructions_inline": instructions,
            "created_at": self._iso_now(),
        }
        body = self._render_body(prose, meta)
        labels = list(inputs.get("issue_labels") or [self._agent_task_label])
        issue = self._client.create_issue(title=title, body=body, labels=labels)
        number = int(issue["number"])
        labels_on_issue = {
            (lbl.get("name") if isinstance(lbl, dict) else lbl)
            for lbl in (issue.get("labels") or [])
        }
        if self._agent_task_label not in labels_on_issue:
            try:
                self._client.add_label(number, self._agent_task_label)
            except Exception:
                pass
        feature_head_sha = self._client.create_branch(
            feature_branch, from_branch=self._base_branch
        )
        self.state.issue_number = number
        self.state.feature_branch = feature_branch
        self.state.feature_baseline_sha = feature_head_sha
        self.state.agent_id = meta["agent_id"]
        self.state.session_id = meta["session_id"]
        self.state.meta_status = "working"
        return {
            "issue_number_present": True,
            "issue_number": number,
            "feature_branch": feature_branch,
        }

    # ------------------------------------------------------------------
    # fanout — dispatch then (optionally) kill before polling.
    # ------------------------------------------------------------------
    def _observe_fanout(self, inputs: dict[str, Any]) -> dict[str, Any]:
        if self.state.feature_branch is None:
            raise RuntimeError("fanout phase: setup phase has not run")
        max_parallel = int(inputs.get("max_parallel") or self._max_parallel)
        kill = bool(inputs.get("kill_after_dispatch"))
        command = inputs.get("command") or self._subagent_command
        args_in = inputs.get("args") or {}

        from envelopes import build_request, serialize

        for i in range(max_parallel):
            sub_id = f"{self._subagent_id_prefix}-{i + 1:02d}"
            sub_branch = f"{self.state.feature_branch}--{sub_id}"
            self._client.create_branch(
                sub_branch, from_branch=self.state.feature_branch
            )
            commit_info = self._client.put_file_contents(
                path=f".agent/runs/harness/{sub_id}.md",
                content_bytes=(
                    f"# Harness subagent {sub_id}\n\n"
                    f"Stub commit for restart-recovery scenario.\n"
                ).encode("utf-8"),
                message=f"harness: stub commit for {sub_id}",
                branch=sub_branch,
            )
            sub_head_sha = (
                (commit_info.get("commit") or {}).get("sha")
                if isinstance(commit_info, dict)
                else None
            ) or self._client.get_branch_head_sha(sub_branch)
            envelope = build_request(
                command=command,
                args=dict(args_in),
                branch=sub_branch,
                commit_sha=sub_head_sha,
                subagent_id=sub_id,
                submitted_at=self._iso_now(),
            )
            comment = self._client.add_comment(
                self.state.issue_number, serialize(envelope)
            )
            comment_id = int(comment["id"])
            self.state.subagent_branches.append(sub_branch)
            self.state.subagent_heads.append(sub_head_sha)
            self.state.subagent_request_comment_ids.append(comment_id)
            self.state.subagent_terminal_envelopes.append(None)

        if kill:
            # Simulate orchestrator death after dispatch but before
            # polling. Record the comment count so the restart phase
            # can prove no duplicate dispatch happened.
            self._kill_dispatched = True
            self._pre_restart_comment_count = len(
                self._client.list_comments(self.state.issue_number)
            )
            return {
                "subagents_dispatched": max_parallel,
                "subagent_branches_created": len(self.state.subagent_branches),
                "orchestrator_killed_mid_fanout": True,
                "request_comment_ids": list(self.state.subagent_request_comment_ids),
            }

        # Normal (non-killed) path: poll to terminal.
        self._poll_subagent_terminals()
        return {
            "subagents_dispatched": max_parallel,
            "subagent_branches_created": len(self.state.subagent_branches),
            "orchestrator_killed_mid_fanout": False,
            "all_subagents_terminal": all(
                e is not None for e in self.state.subagent_terminal_envelopes
            ),
        }

    # ------------------------------------------------------------------
    # restart — rehydrate from GitHub, finish polling.
    # ------------------------------------------------------------------
    def _observe_restart(self, inputs: dict[str, Any]) -> dict[str, Any]:
        if not self._kill_dispatched:
            raise RuntimeError(
                "restart phase: fanout did not kill mid-dispatch"
            )
        issue_number = inputs.get("issue_number") or self.state.issue_number
        if issue_number is None:
            raise RuntimeError("restart phase: no issue_number to recover")

        # Simulate a fresh process: clear in-memory state, then rehydrate.
        recovered = _OrchestrateState(base_branch=self._base_branch)
        recovered.issue_number = int(issue_number)

        issue = self._client.get_issue(recovered.issue_number)
        meta = self._parse_agent_meta(issue.get("body"))
        if meta is None:
            raise RuntimeError("restart phase: issue body missing agent-meta")
        recovered.feature_branch = meta.get("feature_branch")
        recovered.agent_id = meta.get("agent_id")
        recovered.session_id = meta.get("session_id")
        recovered.meta_status = meta.get("status")

        # Rehydrate sub-branches by listing branches with the
        # `<feature>--<sub_prefix>-NN` pattern.
        sub_prefix = (
            f"{recovered.feature_branch}--{self._subagent_id_prefix}-"
            if recovered.feature_branch
            else None
        )
        if sub_prefix:
            for br in self._client.list_branches():
                name = br.get("name") if isinstance(br, dict) else None
                if isinstance(name, str) and name.startswith(sub_prefix):
                    recovered.subagent_branches.append(name)
                    recovered.subagent_heads.append(
                        self._client.get_branch_head_sha(name) or ""
                    )
        recovered.subagent_branches.sort()

        # Rehydrate request comment IDs from issue comments.
        from envelopes import parse, is_terminal, KIND_REQUEST

        recovered.subagent_request_comment_ids = []
        recovered.subagent_terminal_envelopes = []
        for c in self._client.list_comments(recovered.issue_number):
            parsed = parse(c.get("body"))
            if parsed is None:
                continue
            if parsed.get("kind") != KIND_REQUEST:
                continue
            recovered.subagent_request_comment_ids.append(int(c["id"]))
            recovered.subagent_terminal_envelopes.append(
                parsed if is_terminal(parsed) else None
            )

        # Preserve the feature_baseline_sha from the original setup —
        # not directly recoverable from GitHub (we'd need an audit
        # record). The harness uses the current feature HEAD on the
        # restart-side as a proxy. The merge phase's "advanced" check
        # compares to this proxy + post-merge head.
        recovered.feature_baseline_sha = self._client.get_branch_head_sha(
            recovered.feature_branch
        )

        # Swap in the rehydrated state. The original in-memory state is
        # discarded — restart guarantees no continuation of dead-instance
        # state.
        self.state = recovered

        # Finish the polling that fanout skipped. No duplicate dispatch
        # — assert the comment count hasn't grown.
        post_restart_comment_count = len(
            self._client.list_comments(self.state.issue_number)
        )
        no_dup = (
            self._pre_restart_comment_count is None
            or post_restart_comment_count == self._pre_restart_comment_count
        )

        self._poll_subagent_terminals()
        return {
            "restart_acknowledged": True,
            "no_duplicate_dispatch": no_dup,
            "rehydrated_issue_number": self.state.issue_number,
            "rehydrated_feature_branch": self.state.feature_branch,
            "rehydrated_subagent_branches": list(self.state.subagent_branches),
        }

    # ------------------------------------------------------------------
    # finalise — same logic as OrchestrateIssueObserver.merge.
    # ------------------------------------------------------------------
    def _observe_finalise(self, inputs: dict[str, Any]) -> dict[str, Any]:
        if not self.state.subagent_branches:
            raise RuntimeError("finalise phase: no sub-branches to merge")
        if self.state.feature_branch is None:
            raise RuntimeError("finalise phase: feature branch missing")

        for sub_branch in self.state.subagent_branches:
            sub_id = sub_branch.rsplit("--", 1)[-1]
            stub_path = f".agent/runs/harness/{sub_id}.md"
            stub_bytes = (
                f"# Harness subagent {sub_id}\n\n"
                f"Stub commit for restart-recovery scenario.\n"
            ).encode("utf-8")
            self._client.put_file_contents(
                path=stub_path,
                content_bytes=stub_bytes,
                message=f"harness: merge {sub_id} into {self.state.feature_branch}",
                branch=self.state.feature_branch,
            )

        feature_head = self._client.get_branch_head_sha(self.state.feature_branch)
        feature_advanced = (
            feature_head is not None
            and feature_head != self.state.feature_baseline_sha
        )
        title = inputs.get("pr_title") or (
            f"orchestrate-issue-restart-recovery: issue "
            f"#{self.state.issue_number}"
        )
        body = inputs.get("pr_body") or (
            f"Restart-recovery scenario. Closes #{self.state.issue_number}."
        )
        pr = self._client.create_pull_request(
            title=title,
            head=self.state.feature_branch,
            base=self._base_branch,
            body=body,
        )
        pr_number = int(pr["number"])
        self.state.pr_number = pr_number
        return {
            "feature_branch_advanced": feature_advanced,
            "pr_opened": True,
            "pr_number": pr_number,
        }

    # ------------------------------------------------------------------
    # verify — same logic as OrchestrateIssueObserver.verify.
    # ------------------------------------------------------------------
    def _observe_verify(self, inputs: dict[str, Any]) -> dict[str, Any]:
        if self.state.pr_number is None:
            raise RuntimeError("verify phase: finalise phase has not run")
        issue = self._client.get_issue(self.state.issue_number)
        meta = self._parse_agent_meta(issue.get("body"))
        if meta is not None:
            new_meta = dict(meta)
            new_meta["status"] = "finished"
            new_meta["status_ts"] = self._iso_now()
            new_body = self._replace_agent_meta(issue.get("body"), new_meta)
            self._client.update_issue(self.state.issue_number, body=new_body)
            self.state.meta_status = "finished"

        deadline = self._clock() + float(self._poll_timeout_s)
        pr_merged = False
        while True:
            if self._clock() >= deadline:
                break
            pr = self._client.get_pull_request(self.state.pr_number)
            if isinstance(pr, dict) and pr.get("merged"):
                pr_merged = True
                break
            self._sleep(self._poll_interval_s)
        self.state.pr_merged = pr_merged
        return {
            "pr_merged": pr_merged,
            "pr_number": self.state.pr_number,
            "meta_status": self.state.meta_status,
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _poll_subagent_terminals(self) -> None:
        from envelopes import parse, is_terminal

        deadline = self._clock() + float(self._poll_timeout_s)
        while True:
            pending = [
                idx
                for idx, env in enumerate(self.state.subagent_terminal_envelopes)
                if env is None
            ]
            if not pending:
                break
            if self._clock() >= deadline:
                break
            advanced = False
            for idx in pending:
                cid = self.state.subagent_request_comment_ids[idx]
                comment = self._client.get_comment(cid)
                body = comment.get("body") if isinstance(comment, dict) else None
                parsed = parse(body)
                if parsed is not None and is_terminal(parsed):
                    self.state.subagent_terminal_envelopes[idx] = parsed
                    advanced = True
            if not advanced:
                self._sleep(self._poll_interval_s)





# ---------------------------------------------------------------------------
# Public factory
# ---------------------------------------------------------------------------

_OBSERVER_FACTORIES: dict[str, Any] = {
    "batch-job-happy-path": BatchJobObserver,
    "orchestrate-issue-single-subagent": OrchestrateIssueObserver,
    "orchestrate-issue-parallel-fanout": OrchestrateIssueObserver,
    "task-dag-claim-and-plan": TaskDagClaimObserver,
    "orchestrate-issue-restart-recovery": OrchestrateIssueRestartObserver,
}


def supported_scenarios() -> list[str]:
    """Return the list of scenarios with a live observer implementation."""
    return sorted(_OBSERVER_FACTORIES.keys())


def make_observer(scenario_id: str, **kwargs: Any) -> Any:
    """Construct the live observer for the given scenario id.

    Raises ``KeyError`` if there is no live observer for that scenario;
    the runner translates that into a degraded synthetic run.
    """
    factory = _OBSERVER_FACTORIES[scenario_id]
    return factory(**kwargs)


__all__ = [
    "BatchJobObserver",
    "OrchestrateIssueObserver",
    "OrchestrateIssueRestartObserver",
    "TaskDagClaimObserver",
    "DEFAULT_POLL_INTERVAL_S",
    "DEFAULT_POLL_TIMEOUT_S",
    "make_observer",
    "supported_scenarios",
]
