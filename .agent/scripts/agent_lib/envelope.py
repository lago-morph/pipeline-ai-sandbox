"""Envelope construction helpers for the agent harness.

Pure functions that build a ``batch-job-request`` envelope dict and
optionally validate args against the command's args sub-schema.

No I/O is performed: schemas are loaded from disk via
:mod:`agent_protocol_common`, but no network is touched.
"""

from __future__ import annotations

from typing import Any, Optional

from ._common_loader import REPO_ROOT, load_common


_common = load_common()


class EnvelopeArgsInvalid(ValueError):
    """Raised when ``args`` fail to validate against the command schema."""

    def __init__(self, command: str, message: str) -> None:
        super().__init__(f"args invalid for command {command!r}: {message}")
        self.command = command
        self.message = message


def make_request_envelope(
    command: str,
    args: dict[str, Any],
    branch: str,
    commit_sha: str,
    subagent_id: str,
    *,
    validate_args: bool = True,
    submitted_at: Optional[str] = None,
) -> dict[str, Any]:
    """Construct an unsubmitted ``batch-job-request`` envelope.

    Mirrors :func:`skills.batch-job.submit.submit` minus the I/O. When
    ``validate_args`` is True (default), ``args`` is checked against the
    command's ``args`` sub-schema; an ``EnvelopeArgsInvalid`` is raised
    on failure.

    The ``submitted_at`` timestamp is filled with :func:`iso_now` when
    not provided by the caller.
    """
    if not isinstance(command, str) or not command:
        raise ValueError("command must be a non-empty string")
    if not isinstance(args, dict):
        raise TypeError("args must be a dict")
    if not isinstance(branch, str) or not branch:
        raise ValueError("branch must be a non-empty string")
    if not isinstance(commit_sha, str) or not commit_sha:
        raise ValueError("commit_sha must be a non-empty string")
    if not isinstance(subagent_id, str) or not subagent_id:
        raise ValueError("subagent_id must be a non-empty string")

    if validate_args:
        try:
            schema = _common.load_schema(
                f"commands/{command}.schema.json", REPO_ROOT
            )
        except FileNotFoundError as e:
            raise EnvelopeArgsInvalid(command, f"no schema file: {e}") from e
        args_schema = schema.get("properties", {}).get("args")
        if args_schema is not None:
            try:
                _common.validate(args, args_schema)
            except Exception as e:  # noqa: BLE001 - rewrap
                raise EnvelopeArgsInvalid(command, str(e)) from e

    return {
        "protocol_version": 1,
        "kind": "batch-job-request",
        "command": command,
        "args": dict(args),
        "branch": branch,
        "commit_sha": commit_sha,
        "subagent_id": subagent_id,
        "submitted_at": submitted_at or _common.iso_now(),
        "run_status": None,
        "agent_ack": None,
    }


def make_ack_envelope(
    ack_for: int,
    *,
    agent_acked_at: Optional[str] = None,
    agent_id: Optional[str] = None,
    session_id: Optional[str] = None,
    note: Optional[str] = None,
) -> dict[str, Any]:
    """Construct an agent-ack follow-up comment envelope.

    ``ack_for`` is the comment_id of the original batch-job-request whose
    terminal envelope this comment acknowledges (SPEC §5.2). The
    handler treats agent-ack comments as informational; the
    working->finished gate (SPEC §4.1) accepts EITHER an in-place
    ``agent_ack: finished`` on the request comment OR a follow-up
    ``kind: agent-ack`` comment with ``ack_for`` matching the request.
    """
    if not isinstance(ack_for, int) or isinstance(ack_for, bool) or ack_for < 1:
        raise ValueError("ack_for must be a positive integer (comment_id)")
    env: dict[str, Any] = {
        "protocol_version": 1,
        "kind": "agent-ack",
        "ack_for": ack_for,
        "agent_acked_at": agent_acked_at or _common.iso_now(),
    }
    if agent_id is not None:
        env["agent_id"] = agent_id
    if session_id is not None:
        env["session_id"] = session_id
    if note is not None:
        env["note"] = note
    return env


__all__ = ["EnvelopeArgsInvalid", "make_request_envelope", "make_ack_envelope"]
