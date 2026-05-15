"""Pure helpers that produce / mutate ``agent-meta`` blocks.

Each function takes either a meta dict (for transformations) or kwargs
(for ``make_initial_meta``) and returns either a new dict or the
markdown body string ready to be sent to ``mcp__github__issue_write``
as the ``body`` field.

No GitHub I/O is performed.
"""

from __future__ import annotations

from typing import Any, Optional

from ._common_loader import load_common


_common = load_common()


def _extract_prose(body: Optional[str]) -> str:
    """Return everything before the agent-meta fenced block, if any."""
    if not body:
        return ""
    marker = "```agent-meta"
    idx = body.find(marker)
    if idx == -1:
        return body
    return body[:idx].rstrip()


def make_initial_meta(
    *,
    feature_branch: str,
    base_branch: str = "main",
    instructions_inline: Optional[str] = None,
    instructions_path: Optional[str] = None,
    parent_issue: Optional[int] = None,
    depends_on_prs: Optional[list[int]] = None,
    protocol_version: int = 1,
    extra: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Build a fresh agent-meta dict with ``status=None``.

    Either ``instructions_inline`` or ``instructions_path`` must be
    provided (matching the schema's ``anyOf``).
    """
    if not feature_branch:
        raise ValueError("feature_branch is required")
    if not instructions_inline and not instructions_path:
        raise ValueError(
            "either instructions_inline or instructions_path must be set"
        )
    meta = {
        "protocol_version": protocol_version,
        "agent_id": None,
        "session_id": None,
        "status": None,
        "status_ts": None,
        "feature_branch": feature_branch,
        "base_branch": base_branch,
        "parent_issue": parent_issue,
        "depends_on_prs": list(depends_on_prs or []),
        "instructions_path": instructions_path,
        "instructions_inline": instructions_inline,
        "created_at": _common.iso_now(),
    }
    if extra:
        for k, v in extra.items():
            meta[k] = v
    return meta


def claim_meta(
    meta: dict[str, Any],
    agent_id: str,
    session_id: str,
) -> dict[str, Any]:
    """Mark the meta as claimed by ``agent_id``/``session_id``.

    Returns a new dict; the input is not mutated.
    """
    if not agent_id:
        raise ValueError("agent_id is required")
    if not session_id:
        raise ValueError("session_id is required")
    new_meta = dict(meta)
    new_meta["agent_id"] = agent_id
    new_meta["session_id"] = session_id
    new_meta["status"] = "working"
    new_meta["status_ts"] = _common.iso_now()
    return new_meta


def heartbeat_meta(meta: dict[str, Any]) -> dict[str, Any]:
    """Refresh ``status_ts`` to now. Returns a new dict."""
    new_meta = dict(meta)
    new_meta["status_ts"] = _common.iso_now()
    return new_meta


def finish_meta(meta: dict[str, Any]) -> dict[str, Any]:
    """Mark the meta as ``status="finished"``. Returns a new dict."""
    new_meta = dict(meta)
    new_meta["status"] = "finished"
    new_meta["status_ts"] = _common.iso_now()
    return new_meta


def abandon_meta(meta: dict[str, Any], reason: str) -> dict[str, Any]:
    """Mark the meta as ``abandoned`` with a recorded reason.

    The ``reason`` is stored under the ``abandon_reason`` key (additional
    properties are allowed by the issue-body schema).
    """
    new_meta = dict(meta)
    new_meta["status"] = "abandoned"
    new_meta["status_ts"] = _common.iso_now()
    new_meta["abandon_reason"] = reason
    return new_meta


def render_body(meta: dict[str, Any], prose: str = "") -> str:
    """Convenience: render an issue body with the given meta."""
    return _common.render_agent_meta(meta, prose=prose)


def parse_body(body: Optional[str]) -> Optional[dict[str, Any]]:
    """Convenience: parse an agent-meta block out of a body."""
    return _common.parse_agent_meta(body)


def replace_meta_in_body(
    body: Optional[str],
    new_meta: dict[str, Any],
) -> str:
    """Replace the agent-meta block in ``body`` with ``new_meta``.

    The prose before the block is preserved; if there was no block, the
    new meta is appended.
    """
    prose = _extract_prose(body)
    return _common.render_agent_meta(new_meta, prose=prose)


__all__ = [
    "make_initial_meta",
    "claim_meta",
    "heartbeat_meta",
    "finish_meta",
    "abandon_meta",
    "render_body",
    "parse_body",
    "replace_meta_in_body",
]
