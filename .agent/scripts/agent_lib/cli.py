"""Thin CLI wrapper around the pure helpers.

Designed to be invoked by the dispatcher agent via ``Bash`` calls of
the form::

    python -m agent_lib <subcommand> <positional args> [--option ...]

All subcommands print JSON to stdout (the parsed structure or the
markdown body) so the agent can pipe the result into a subsequent MCP
call. Validation failures exit with a non-zero status; the error
message goes to stderr as a single ``{"error": "..."}`` JSON object.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Optional

from . import (
    EnvelopeArgsInvalid,
    abandon_meta,
    claim_meta,
    finish_meta,
    heartbeat_meta,
    make_ack_envelope,
    make_initial_meta,
    make_request_envelope,
    parse_body,
    parse_terminal_status,
    render_body,
    summary_path_for,
)
from ._common_loader import REPO_ROOT, load_common
from .meta import replace_meta_in_body


_common = load_common()


def _die(msg: str, code: int = 1) -> None:
    sys.stderr.write(json.dumps({"error": msg}) + "\n")
    raise SystemExit(code)


def _loads(s: str, *, name: str) -> Any:
    try:
        return json.loads(s)
    except (json.JSONDecodeError, ValueError) as e:
        _die(f"{name}: invalid JSON: {e}")


def _print(obj: Any) -> None:
    sys.stdout.write(json.dumps(obj, indent=2, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------
# Subcommand implementations
# ---------------------------------------------------------------------------

def cmd_make_request(ns: argparse.Namespace) -> int:
    args = _loads(ns.args_json, name="args")
    if not isinstance(args, dict):
        _die("args must be a JSON object")
    try:
        env = make_request_envelope(
            ns.command,
            args,
            ns.branch,
            ns.sha,
            ns.subagent_id,
            validate_args=not ns.no_validate,
        )
    except EnvelopeArgsInvalid as e:
        _die(str(e))
    except (TypeError, ValueError) as e:
        _die(str(e))
    _print(env)
    return 0


def cmd_make_ack(ns: argparse.Namespace) -> int:
    try:
        env = make_ack_envelope(
            ns.ack_for,
            agent_id=ns.agent_id,
            session_id=ns.session_id,
            note=ns.note,
        )
    except ValueError as e:
        _die(str(e))
    _print(env)
    return 0


def cmd_make_initial_meta(ns: argparse.Namespace) -> int:
    payload = _loads(ns.json_payload, name="payload")
    if not isinstance(payload, dict):
        _die("payload must be a JSON object")
    try:
        meta = make_initial_meta(**payload)
    except TypeError as e:
        _die(f"unsupported arguments: {e}")
    except ValueError as e:
        _die(str(e))
    body = render_body(meta, prose=ns.prose or "")
    sys.stdout.write(body if body.endswith("\n") else body + "\n")
    return 0


def cmd_claim_meta(ns: argparse.Namespace) -> int:
    meta = _loads(ns.meta_json, name="meta")
    if not isinstance(meta, dict):
        _die("meta must be a JSON object")
    try:
        new_meta = claim_meta(meta, ns.agent_id, ns.session_id)
    except ValueError as e:
        _die(str(e))
    body = render_body(new_meta, prose=ns.prose or "")
    sys.stdout.write(body if body.endswith("\n") else body + "\n")
    return 0


def cmd_heartbeat_meta(ns: argparse.Namespace) -> int:
    meta = _loads(ns.meta_json, name="meta")
    if not isinstance(meta, dict):
        _die("meta must be a JSON object")
    new_meta = heartbeat_meta(meta)
    body = render_body(new_meta, prose=ns.prose or "")
    sys.stdout.write(body if body.endswith("\n") else body + "\n")
    return 0


def cmd_finish_meta(ns: argparse.Namespace) -> int:
    meta = _loads(ns.meta_json, name="meta")
    if not isinstance(meta, dict):
        _die("meta must be a JSON object")
    new_meta = finish_meta(meta)
    body = render_body(new_meta, prose=ns.prose or "")
    sys.stdout.write(body if body.endswith("\n") else body + "\n")
    return 0


def cmd_abandon_meta(ns: argparse.Namespace) -> int:
    meta = _loads(ns.meta_json, name="meta")
    if not isinstance(meta, dict):
        _die("meta must be a JSON object")
    new_meta = abandon_meta(meta, ns.reason)
    body = render_body(new_meta, prose=ns.prose or "")
    sys.stdout.write(body if body.endswith("\n") else body + "\n")
    return 0


def cmd_parse_comment(ns: argparse.Namespace) -> int:
    run_status, parsed = parse_terminal_status(ns.body)
    summary_path: Optional[str] = None
    log_manifest_path: Optional[str] = None
    if run_status is not None:
        log_manifest_path = parsed.get("log_manifest_path")
        if log_manifest_path:
            base = log_manifest_path.rsplit("/", 1)[0]
            summary_path = base + "/summary.json"
    out = {
        "run_status": run_status,
        "summary": parsed.get("summary"),
        "log_manifest_path": log_manifest_path,
        "summary_path": summary_path,
        "envelope": parsed,
    }
    _print(out)
    return 0


def cmd_parse_meta(ns: argparse.Namespace) -> int:
    meta = parse_body(ns.body)
    if meta is None:
        _print(None)
    else:
        _print(meta)
    return 0


def cmd_summary_path(ns: argparse.Namespace) -> int:
    try:
        path = summary_path_for(ns.issue, ns.comment)
    except ValueError as e:
        _die(str(e))
    _print({"summary_path": path})
    return 0


def cmd_replace_meta(ns: argparse.Namespace) -> int:
    meta = _loads(ns.meta_json, name="meta")
    if not isinstance(meta, dict):
        _die("meta must be a JSON object")
    body = replace_meta_in_body(ns.body, meta)
    sys.stdout.write(body if body.endswith("\n") else body + "\n")
    return 0


def cmd_validate_summary(ns: argparse.Namespace) -> int:
    summary = _loads(ns.summary_json, name="summary")
    try:
        schema = _common.load_schema(
            f"commands/{ns.command}.schema.json", REPO_ROOT
        )
    except FileNotFoundError as e:
        _die(f"no schema for command {ns.command}: {e}")
    key = "summary_completed" if ns.status == "completed" else "summary_error"
    sub = schema.get("properties", {}).get(key)
    if sub is None:
        _die(f"schema has no {key} sub-schema for {ns.command}")
    try:
        _common.validate(summary, sub)
    except Exception as e:  # noqa: BLE001
        _die(f"invalid: {e}")
    _print({"valid": True, "command": ns.command, "status": ns.status})
    return 0


# ---------------------------------------------------------------------------
# argparse wiring
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="agent_lib")
    sub = p.add_subparsers(dest="cmd", required=True)

    # make-request
    s = sub.add_parser("make-request", help="build a batch-job-request envelope")
    s.add_argument("args_json", help="JSON object: command args")
    s.add_argument("--command", required=True)
    s.add_argument("--branch", required=True)
    s.add_argument("--sha", required=True, help="commit_sha (40 hex chars)")
    s.add_argument("--subagent-id", required=True)
    s.add_argument("--no-validate", action="store_true",
                   help="skip args schema validation")
    s.set_defaults(func=cmd_make_request)

    # make-ack
    s = sub.add_parser(
        "make-ack",
        help="build a follow-up agent-ack comment envelope",
    )
    s.add_argument(
        "--ack-for", type=int, dest="ack_for", required=True,
        help="comment_id of the batch-job-request to ack",
    )
    s.add_argument("--agent-id", dest="agent_id", default=None)
    s.add_argument("--session-id", dest="session_id", default=None)
    s.add_argument("--note", default=None)
    s.set_defaults(func=cmd_make_ack)

    # make-initial-meta
    s = sub.add_parser("make-initial-meta",
                       help="build initial agent-meta block + body markdown")
    s.add_argument("json_payload",
                   help="JSON object of kwargs for make_initial_meta")
    s.add_argument("--prose", default="", help="prose to put before block")
    s.set_defaults(func=cmd_make_initial_meta)

    # claim-meta
    s = sub.add_parser("claim-meta",
                       help="produce new body markdown for a claim")
    s.add_argument("meta_json", help="existing meta JSON")
    s.add_argument("--agent-id", required=True)
    s.add_argument("--session-id", required=True)
    s.add_argument("--prose", default="")
    s.set_defaults(func=cmd_claim_meta)

    # heartbeat-meta
    s = sub.add_parser("heartbeat-meta",
                       help="produce new body markdown with refreshed status_ts")
    s.add_argument("meta_json")
    s.add_argument("--prose", default="")
    s.set_defaults(func=cmd_heartbeat_meta)

    # finish-meta
    s = sub.add_parser("finish-meta",
                       help="produce new body markdown with status=finished")
    s.add_argument("meta_json")
    s.add_argument("--prose", default="")
    s.set_defaults(func=cmd_finish_meta)

    # abandon-meta
    s = sub.add_parser("abandon-meta",
                       help="produce new body markdown with status=abandoned")
    s.add_argument("meta_json")
    s.add_argument("--reason", required=True)
    s.add_argument("--prose", default="")
    s.set_defaults(func=cmd_abandon_meta)

    # parse-comment
    s = sub.add_parser("parse-comment",
                       help="extract run_status / summary / paths from comment body")
    s.add_argument("body", help="raw comment body text")
    s.set_defaults(func=cmd_parse_comment)

    # parse-meta
    s = sub.add_parser("parse-meta",
                       help="parse the agent-meta block out of an issue body")
    s.add_argument("body", help="raw issue body markdown")
    s.set_defaults(func=cmd_parse_meta)

    # summary-path
    s = sub.add_parser("summary-path",
                       help="compute the summary.json path for issue/comment")
    s.add_argument("--issue", type=int, required=True)
    s.add_argument("--comment", type=int, required=True)
    s.set_defaults(func=cmd_summary_path)

    # replace-meta
    s = sub.add_parser("replace-meta",
                       help="replace the agent-meta block in an existing body")
    s.add_argument("body")
    s.add_argument("--meta-json", dest="meta_json", required=True)
    s.set_defaults(func=cmd_replace_meta)

    # validate-summary
    s = sub.add_parser("validate-summary",
                       help="validate a summary against the command schema")
    s.add_argument("summary_json")
    s.add_argument("--command", required=True)
    s.add_argument("--status", choices=("completed", "error"), required=True)
    s.set_defaults(func=cmd_validate_summary)

    return p


def main(argv: Optional[list[str]] = None) -> int:
    parser = _build_parser()
    ns = parser.parse_args(argv)
    return ns.func(ns)


if __name__ == "__main__":  # pragma: no cover - dispatched by __main__.py
    raise SystemExit(main())
