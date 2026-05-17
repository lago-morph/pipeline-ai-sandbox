"""Build and parse `batch-job-request` comment envelopes.

The protocol's comment-body envelopes are JSON objects whose required
markers are ``protocol_version`` and ``kind``. This module is a small,
explicitly-typed wrapper that:

- ``build_request(...)`` — produces an initial request envelope dict.
- ``serialize(envelope)`` — renders to the canonical 2-space-indented
  JSON string the handler updates in place.
- ``parse(body)`` — lenient prefix-JSON parse that tolerates trailing
  prose (e.g. the trailer Claude Code's GitHub MCP appends to every
  posted comment). Mirrors ``.agent/scripts/handler.py::_parse_envelope_lenient``
  so the dispatcher and the workflow agree on what's a valid envelope.
- ``run_status(envelope)`` / ``is_terminal`` / ``is_completed`` /
  ``is_error`` / ``is_parse_error`` — small accessors.

Kept dependency-free (stdlib only) so it can be imported by tests
without dragging in jsonschema or requests.
"""
from __future__ import annotations

import json
from typing import Any, Optional


PROTOCOL_VERSION = 1
KIND_REQUEST = "batch-job-request"
KIND_ACK = "agent-ack"

TERMINAL_STATUSES = frozenset({"completed", "error", "parse_error"})


def build_request(
    *,
    command: str,
    args: dict[str, Any],
    branch: str,
    commit_sha: str,
    subagent_id: str,
    submitted_at: str,
) -> dict[str, Any]:
    """Build an initial batch-job-request envelope.

    Mirrors the SPEC §5.2 required fields for a fresh request:
    ``protocol_version``, ``kind``, ``command``, ``args``, ``branch``,
    ``commit_sha``, ``subagent_id``, ``submitted_at``. ``run_status``
    is intentionally left out — it's ``null`` until the handler picks
    it up and writes ``"running"``.
    """
    if not command:
        raise ValueError("command is required")
    if not branch:
        raise ValueError("branch is required")
    if not (isinstance(commit_sha, str) and len(commit_sha) == 40):
        raise ValueError("commit_sha must be a 40-char hex string")
    if not subagent_id:
        raise ValueError("subagent_id is required")
    if not submitted_at:
        raise ValueError("submitted_at is required")
    return {
        "protocol_version": PROTOCOL_VERSION,
        "kind": KIND_REQUEST,
        "command": command,
        "args": dict(args or {}),
        "branch": branch,
        "commit_sha": commit_sha,
        "subagent_id": subagent_id,
        "submitted_at": submitted_at,
    }


def serialize(envelope: dict[str, Any]) -> str:
    """Render an envelope as the canonical pretty-printed JSON string."""
    return json.dumps(envelope, indent=2, sort_keys=False)


def parse(body: Optional[str]) -> Optional[dict[str, Any]]:
    """Lenient prefix-JSON parse of a comment body.

    Mirrors ``handler.py::_parse_envelope_lenient``. Returns ``None`` for
    any non-string input, any body that doesn't begin (after stripping
    leading whitespace) with a JSON object, or any object missing the
    minimal protocol markers (``protocol_version``, ``kind``).
    """
    if not isinstance(body, str):
        return None
    stripped = body.lstrip()
    if not stripped:
        return None
    try:
        parsed, _idx = json.JSONDecoder().raw_decode(stripped)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(parsed, dict):
        return None
    if "protocol_version" not in parsed or "kind" not in parsed:
        return None
    return parsed


def run_status(envelope: dict[str, Any]) -> Optional[str]:
    """Return the envelope's ``run_status`` field, or ``None``."""
    if not isinstance(envelope, dict):
        return None
    status = envelope.get("run_status")
    if status is None:
        return None
    return str(status)


def is_terminal(envelope: dict[str, Any]) -> bool:
    """True when ``run_status`` is one of completed / error / parse_error."""
    return run_status(envelope) in TERMINAL_STATUSES


def is_completed(envelope: dict[str, Any]) -> bool:
    return run_status(envelope) == "completed"


def is_error(envelope: dict[str, Any]) -> bool:
    return run_status(envelope) == "error"


def is_parse_error(envelope: dict[str, Any]) -> bool:
    return run_status(envelope) == "parse_error"


def is_running(envelope: dict[str, Any]) -> bool:
    return run_status(envelope) == "running"


__all__ = [
    "PROTOCOL_VERSION",
    "KIND_REQUEST",
    "KIND_ACK",
    "TERMINAL_STATUSES",
    "build_request",
    "serialize",
    "parse",
    "run_status",
    "is_terminal",
    "is_completed",
    "is_error",
    "is_parse_error",
    "is_running",
]
