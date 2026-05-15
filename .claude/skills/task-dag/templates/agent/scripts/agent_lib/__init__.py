"""Pure-Python helpers for the agent-mode harness.

This package is the agent-side counterpart to the workflow-side handler.

The dispatcher AI cannot pass MCP tools as Python callables, so the
"skill" lifecycle in agent mode is split into:

- Pure helpers (here): envelope construction, agent-meta marshalling,
  terminal-status parsing, summary path derivation, schema validation.
- Markdown playbooks (under ``harness/scenarios/``): tell the agent
  which MCP calls to make and in what order.

Pure helpers run inside the sandbox — invoked via ``python -m agent_lib
<sub> ...``; the printed JSON is consumed by the agent's tool-use
stream.

This module deliberately performs **no** I/O against GitHub.
"""

from __future__ import annotations

from .envelope import (
    EnvelopeArgsInvalid,
    make_ack_envelope,
    make_request_envelope,
)
from .meta import (
    abandon_meta,
    claim_meta,
    finish_meta,
    heartbeat_meta,
    make_initial_meta,
    parse_body,
    render_body,
    replace_meta_in_body,
)
from .poll import (
    is_request_acked,
    is_terminal,
    manifest_path_for,
    parse_ack_comment,
    parse_terminal_status,
    summary_path_for,
)


__all__ = [
    "EnvelopeArgsInvalid",
    "abandon_meta",
    "claim_meta",
    "finish_meta",
    "heartbeat_meta",
    "is_request_acked",
    "is_terminal",
    "make_ack_envelope",
    "make_initial_meta",
    "make_request_envelope",
    "manifest_path_for",
    "parse_ack_comment",
    "parse_body",
    "parse_terminal_status",
    "render_body",
    "replace_meta_in_body",
    "summary_path_for",
]
