"""Live-target observers for scenarios that drive real GitHub.

A live observer is a callable matching :data:`scenario_runner.ObserveFn`
that, instead of returning synthetic observations from the on-disk
fixture, drives a real GitHub repo through the scenario's phases and
returns observations sourced from the live state.

This module implements :class:`BatchJobObserver` for the
``batch-job-happy-path`` scenario. Subsequent scenarios (orchestrate-
issue, task-dag, etc.) get their own observer classes here.

Cross-phase state (issue number, request-comment id, branch / SHA the
request pointed at) is held on the observer instance and additionally
mirrored into ``state.diagnostics`` by the runner so it survives a
restart.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
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
# Public factory
# ---------------------------------------------------------------------------

_OBSERVER_FACTORIES: dict[str, Any] = {
    "batch-job-happy-path": BatchJobObserver,
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
    "DEFAULT_POLL_INTERVAL_S",
    "DEFAULT_POLL_TIMEOUT_S",
    "make_observer",
    "supported_scenarios",
]
