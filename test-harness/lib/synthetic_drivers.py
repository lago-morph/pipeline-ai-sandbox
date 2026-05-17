"""In-process synthetic drivers for ``target: synthetic-fixture`` scenarios.

Where ``synthetic_observe.generic_observe`` answers a fixed catalogue of
fixture-only keys, this module hosts **scenario-specific observers** that
exercise real skill logic against an in-memory backend — exactly the
drivers the plan calls "in-process mock skill drivers".

The drivers reuse :class:`InMemoryGitHubClient` from ``.agent/scripts/
common.py`` plus the real ``handler.run`` function. They are *not* mocks
of the skill — they are the skill running against an in-memory client
instead of REST. That gives us high-fidelity test signal for the
error-path scenarios (``batch-job-parse-error``, ``...-branch-sha-mismatch``,
``...-runner-pickup-timeout``) without any live GitHub.

Per-scenario observers are exposed as classes whose ``__call__`` matches
the :data:`scenario_runner.ObserveFn` signature.
"""
from __future__ import annotations

import importlib.util
import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional


REPO_ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# Dynamic loader for .agent/scripts/{common,handler}.py so the harness
# doesn't depend on the package being installed.
# ---------------------------------------------------------------------------
def _load_agent_module(name: str) -> Any:
    """Load ``.agent/scripts/<name>.py`` as a top-level module."""
    p = REPO_ROOT / ".agent" / "scripts" / f"{name}.py"
    mod_key = f"_harness_agent_{name}"
    if mod_key in sys.modules:
        return sys.modules[mod_key]
    spec = importlib.util.spec_from_file_location(mod_key, p)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not import .agent/scripts/{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_key] = mod
    spec.loader.exec_module(mod)
    return mod


def load_common() -> Any:
    return _load_agent_module("common")


def load_handler() -> Any:
    return _load_agent_module("handler")


# ---------------------------------------------------------------------------
# Cross-phase state for the batch-job driver.
# ---------------------------------------------------------------------------
@dataclass
class _BatchJobErrorState:
    client: Optional[Any] = None
    issue_number: Optional[int] = None
    branch: str = "main"
    branch_head_sha: Optional[str] = None
    request_comment_id: Optional[int] = None
    terminal_envelope: Optional[dict[str, Any]] = None
    extra: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# SyntheticBatchJobErrorObserver
# ---------------------------------------------------------------------------
class SyntheticBatchJobErrorObserver:
    """Synthetic driver for the 3 batch-job error-path scenarios.

    ``error_mode`` selects which error to provoke:

    - ``"parse_error"``: post a malformed envelope (missing required
      fields). The real handler's schema validation rejects it; the
      terminal envelope carries ``run_status: parse_error``,
      ``error_kind: schema_validation_failed``.
    - ``"sha_mismatch"``: post a valid envelope whose ``commit_sha``
      does not match the branch HEAD. Handler produces
      ``error_kind: branch_sha_mismatch``.
    - ``"pickup_timeout"``: post a valid envelope but **never run the
      handler**. After ``pickup_timeout_s``, the observer writes a
      synthetic ``error`` envelope with ``error_kind: pickup_timeout``
      (this models the orchestrator-side action the dispatcher would
      take when no workflow picks up the request).

    The scenario YAMLs use a slightly different vocabulary than the
    real handler (``invalid_envelope`` vs ``schema_validation_failed``,
    ``sha_mismatch`` vs ``branch_sha_mismatch``). The observer returns
    the **literal** error_kind from the handler so scenario assertions
    fail honestly when the vocabularies diverge — that's a real signal
    for the upstream POC to reconcile.
    """

    def __init__(
        self,
        *,
        error_mode: str,
        agent_login: str = "alice",
        branch: str = "main",
        command: str = "echo",
        subagent_id: str = "harness-batch-job-error",
        pickup_timeout_s: float = 1.0,
        clock: Optional[Any] = None,
        iso_now: Optional[Any] = None,
    ) -> None:
        if error_mode not in {"parse_error", "sha_mismatch", "pickup_timeout"}:
            raise ValueError(
                f"unknown error_mode: {error_mode!r}"
            )
        if not agent_login:
            raise ValueError("agent_login is required")
        self._error_mode = error_mode
        self._agent_login = agent_login
        self._branch = branch
        self._command = command
        self._subagent_id = subagent_id
        self._pickup_timeout_s = pickup_timeout_s
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
        self.state = _BatchJobErrorState(branch=branch)

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
        raise ValueError(
            f"SyntheticBatchJobErrorObserver: unknown phase {phase_name!r}"
        )

    # ------------------------------------------------------------------
    def _ensure_client(self) -> Any:
        if self.state.client is not None:
            return self.state.client
        common = load_common()
        client = common.InMemoryGitHubClient(default_user=self._agent_login)
        client.create_branch(self._branch)
        head_sha = client.get_branch_head_sha(self._branch)
        self.state.client = client
        self.state.branch_head_sha = head_sha
        return client

    def _observe_setup(self, inputs: dict[str, Any]) -> dict[str, Any]:
        client = self._ensure_client()
        title = inputs.get("title") or f"harness: batch-job {self._error_mode}"
        body = inputs.get("body") or "Synthetic harness scenario."
        issue = client.create_issue(
            title=title,
            body=body,
            labels=["agent-task"],
        )
        number = int(issue["number"])
        self.state.issue_number = number
        return {
            "issue_number_present": True,
            "issue_number": number,
            "branch_created": True,
            "repo_created": True,
        }

    def _observe_invoke(self, inputs: dict[str, Any]) -> dict[str, Any]:
        if self.state.issue_number is None:
            raise RuntimeError("invoke phase: setup phase has not run")
        client = self.state.client
        assert client is not None

        # Build the request envelope per error_mode.
        if self._error_mode == "parse_error":
            body = self._build_malformed_envelope(inputs)
        elif self._error_mode == "sha_mismatch":
            body = self._build_sha_mismatch_envelope(inputs)
        else:  # pickup_timeout
            body = self._build_valid_envelope(inputs)
        comment = client.add_comment(self.state.issue_number, body)
        comment_id = int(comment["id"])
        self.state.request_comment_id = comment_id

        terminal: Optional[dict[str, Any]] = None
        if self._error_mode == "pickup_timeout":
            # Simulate "no workflow ever picked this up": after the
            # pickup timeout, the orchestrator writes a synthetic
            # terminal error envelope. We do that directly.
            start = self._clock()
            while self._clock() - start < self._pickup_timeout_s:
                # Spin (test injects a no-op clock that advances on
                # each call); production paths would sleep.
                pass
            terminal = self._stamp_pickup_timeout(comment_id, body)
        else:
            # Run the real handler against the in-memory client.
            handler = load_handler()
            handler.run(
                client,
                self.state.issue_number,
                comment_id,
                workflow_run_id=42,
                workspace=None,
                repo_root=str(REPO_ROOT),
            )
            terminal_body = client.get_comment(comment_id)["body"]
            try:
                terminal = json.loads(terminal_body)
            except json.JSONDecodeError:
                terminal = None
        self.state.terminal_envelope = terminal
        run_status = terminal.get("run_status") if isinstance(terminal, dict) else None
        return {
            "batch_job_comment_present": True,
            "envelope_run_status": run_status,
            "request_comment_id": comment_id,
        }

    def _observe_verify(self, inputs: dict[str, Any]) -> dict[str, Any]:
        terminal = self.state.terminal_envelope
        if terminal is None:
            raise RuntimeError("verify phase: invoke phase has not run")
        return {
            "envelope_run_status": terminal.get("run_status"),
            "error_kind": terminal.get("error_kind"),
            "summary_keys_present": sorted(
                (terminal.get("summary") or {}).keys()
            ),
        }

    # ------------------------------------------------------------------
    # Envelope builders
    # ------------------------------------------------------------------
    def _build_valid_envelope(self, inputs: dict[str, Any]) -> str:
        env = {
            "protocol_version": 1,
            "kind": "batch-job-request",
            "command": inputs.get("command") or self._command,
            "args": dict(inputs.get("args") or {}),
            "branch": self._branch,
            "commit_sha": (
                inputs.get("commit_sha")
                or self.state.branch_head_sha
                or ("0" * 40)
            ),
            "subagent_id": self._subagent_id,
            "submitted_at": self._iso_now(),
        }
        return json.dumps(env, indent=2)

    def _build_malformed_envelope(self, inputs: dict[str, Any]) -> str:
        # Missing several required fields so the schema validation
        # fails. The handler then writes parse_error /
        # error_kind=schema_validation_failed.
        env = {
            "protocol_version": 1,
            "kind": "batch-job-request",
            # missing: command, args, branch, commit_sha, subagent_id,
            # submitted_at
        }
        return json.dumps(env, indent=2)

    def _build_sha_mismatch_envelope(self, inputs: dict[str, Any]) -> str:
        # Override commit_sha to a stale 40-char hex that doesn't match
        # the in-memory branch HEAD. The handler will respond with
        # error_kind=branch_sha_mismatch.
        bad_sha = inputs.get("commit_sha") or ("0" * 40)
        env = {
            "protocol_version": 1,
            "kind": "batch-job-request",
            "command": inputs.get("command") or self._command,
            "args": dict(inputs.get("args") or {}),
            "branch": self._branch,
            "commit_sha": bad_sha,
            "subagent_id": self._subagent_id,
            "submitted_at": self._iso_now(),
        }
        return json.dumps(env, indent=2)

    def _stamp_pickup_timeout(
        self,
        comment_id: int,
        body: str,
    ) -> dict[str, Any]:
        client = self.state.client
        try:
            envelope = json.loads(body)
        except json.JSONDecodeError:
            envelope = {}
        terminal = dict(envelope)
        terminal["run_status"] = "error"
        terminal["error_kind"] = "pickup_timeout"
        terminal["error_detail"] = (
            f"No batch-job-handler picked up the request within "
            f"{self._pickup_timeout_s}s."
        )
        terminal["workflow_run_id"] = 0
        client.update_comment(comment_id, json.dumps(terminal, indent=2))
        return terminal


__all__ = [
    "SyntheticBatchJobErrorObserver",
    "load_common",
    "load_handler",
]
