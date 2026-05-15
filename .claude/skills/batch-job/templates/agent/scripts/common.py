"""Common helpers for the agent protocol POC.

Provides:
- ``GitHubClient`` Protocol/abstract definition of the operations the
  scripts need.
- ``InMemoryGitHubClient`` — fully working in-memory implementation
  used in tests and for local POC demonstrations.
- Envelope/agent-meta helpers (parse, render).
- ``LogWriter`` — a JSONL/gzip log writer that rotates by compressed
  size and produces a manifest.
- ``load_config`` and ``validate`` JSON-schema helpers.

The real GitHub REST integration is intentionally **not** implemented
here; for the POC we exercise behaviour through the in-memory client.
"""

from __future__ import annotations

import base64
import gzip
import html
import io
import json
import os
import re
import secrets
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import (
    Any,
    Optional,
    Protocol,
    runtime_checkable,
)

try:
    from jsonschema import Draft202012Validator
except ImportError:  # pragma: no cover - jsonschema is in requirements
    Draft202012Validator = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Time and config helpers
# ---------------------------------------------------------------------------

def iso_now() -> str:
    """Return the current UTC time as an ISO-8601 string with ``Z`` suffix."""
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_config(path: str | os.PathLike[str] = ".agent/config.json") -> dict[str, Any]:
    """Load the central agent configuration JSON file."""
    p = Path(path)
    with p.open("r", encoding="utf-8") as f:
        return json.load(f)


def validate(json_obj: Any, schema_obj: dict[str, Any]) -> None:
    """Validate a JSON object against a JSON schema (Draft 2020-12).

    Raises ``jsonschema.ValidationError`` on the first error encountered.
    """
    if Draft202012Validator is None:  # pragma: no cover
        raise RuntimeError("jsonschema is not installed; cannot validate")
    validator = Draft202012Validator(schema_obj)
    errors = sorted(validator.iter_errors(json_obj), key=lambda e: list(e.absolute_path))
    if errors:
        first = errors[0]
        path = ".".join(str(p) for p in first.absolute_path) or "<root>"
        raise ValueError(f"schema validation failed at {path}: {first.message}")


# ---------------------------------------------------------------------------
# agent-meta block parsing / rendering
# ---------------------------------------------------------------------------

_AGENT_META_RE = re.compile(
    r"```agent-meta\s*\n(?P<json>.*?)\n```",
    re.DOTALL,
)


def parse_agent_meta(body: Optional[str]) -> Optional[dict[str, Any]]:
    """Extract the JSON object inside the fenced ``agent-meta`` block.

    Returns ``None`` when:
    - the body is ``None`` or empty, OR
    - no ``agent-meta`` fenced block is present, OR
    - the block exists but its body is not valid JSON.

    The MCP server returns issue bodies with HTML-escaped entities
    (``&#34;`` for ``"``, etc.). We unescape the JSON region before
    parsing so the same parser works against MCP and REST responses.
    Workflow REST responses contain literal quotes so unescape is a
    no-op there.
    """
    if not body:
        return None
    m = _AGENT_META_RE.search(body)
    if not m:
        return None
    raw = html.unescape(m.group("json"))
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def render_agent_meta(meta: dict[str, Any], prose: str = "") -> str:
    """Render an issue body markdown with the given ``agent-meta`` block.

    The prose is placed before the fenced block; a blank line separates
    them when both are non-empty.
    """
    block = "```agent-meta\n" + json.dumps(meta, indent=2) + "\n```"
    if prose:
        return f"{prose.rstrip()}\n\n{block}\n"
    return block + "\n"


# ---------------------------------------------------------------------------
# GitHub client abstraction
# ---------------------------------------------------------------------------

@runtime_checkable
class GitHubClient(Protocol):
    """Minimal protocol for the operations the agent scripts need.

    Implementations may use the REST API, an MCP relay, or the
    in-memory mock used for the POC. Errors are raised as exceptions.
    """

    # Issue operations -----------------------------------------------------
    def get_issue(self, number: int) -> dict[str, Any]: ...
    def update_issue(
        self,
        number: int,
        body: Optional[str] = None,
        state: Optional[str] = None,
        labels: Optional[list[str]] = None,
    ) -> dict[str, Any]: ...
    def lock_issue(self, number: int) -> None: ...
    def add_label(self, number: int, label: str) -> None: ...
    def create_issue(
        self,
        title: str,
        body: str,
        labels: Optional[list[str]] = None,
    ) -> dict[str, Any]: ...

    # Comment operations ---------------------------------------------------
    def list_comments(self, issue_number: int) -> list[dict[str, Any]]: ...
    def get_comment(self, comment_id: int) -> dict[str, Any]: ...
    def update_comment(self, comment_id: int, body: str) -> dict[str, Any]: ...
    def delete_comment(self, comment_id: int) -> None: ...
    def add_comment(self, issue_number: int, body: str) -> dict[str, Any]: ...

    # File / branch operations --------------------------------------------
    def get_file_contents(self, path: str, ref: str) -> Optional[str]: ...
    def put_file_contents(
        self,
        path: str,
        content_bytes: bytes,
        message: str,
        branch: str,
    ) -> dict[str, Any]: ...
    def get_branch_head_sha(self, branch: str) -> Optional[str]: ...
    def delete_branch(self, name: str) -> None: ...
    def list_branches(self) -> list[dict[str, Any]]: ...

    # PR operations --------------------------------------------------------
    def create_pull_request(
        self,
        title: str,
        head: str,
        base: str,
        body: str,
    ) -> dict[str, Any]: ...
    def get_pull_request(self, number: int) -> dict[str, Any]: ...


# ---------------------------------------------------------------------------
# In-memory GitHub client (POC + tests)
# ---------------------------------------------------------------------------

@dataclass
class _Commit:
    sha: str
    parent: Optional[str]
    message: str
    files: dict[str, bytes]  # path -> content


@dataclass
class _Branch:
    name: str
    head_sha: Optional[str]  # None means orphan/uninitialised


@dataclass
class _Comment:
    id: int
    issue_number: int
    user: str
    body: str
    created_at: str
    updated_at: str


@dataclass
class _Issue:
    number: int
    title: str
    body: str
    user: str
    state: str = "open"
    locked: bool = False
    labels: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=iso_now)
    updated_at: str = field(default_factory=iso_now)


@dataclass
class _PullRequest:
    number: int
    title: str
    head: str
    base: str
    body: str
    state: str = "open"
    merged: bool = False
    merge_commit_sha: Optional[str] = None
    user: str = "agent"
    created_at: str = field(default_factory=iso_now)


class InMemoryGitHubClient:
    """In-memory simulation of the subset of GitHub the protocol uses.

    Each call returns dict-shaped data resembling the REST API responses
    so that calling code is portable to a real REST client.
    """

    def __init__(self, default_user: str = "agent") -> None:
        self._lock = threading.RLock()
        self._issues: dict[int, _Issue] = {}
        self._comments: dict[int, _Comment] = {}
        self._comments_by_issue: dict[int, list[int]] = {}
        self._branches: dict[str, _Branch] = {}
        self._commits: dict[str, _Commit] = {}
        self._pulls: dict[int, _PullRequest] = {}
        self._next_issue_number = 1
        self._next_comment_id = 1_000_000
        self._next_pr_number = 5000
        self._default_user = default_user
        self._actor_stack: list[str] = [default_user]

    # ------------------------------------------------------------------
    # Test helpers
    # ------------------------------------------------------------------
    def as_user(self, login: str) -> "_ActAs":
        """Context manager: switch the effective acting user temporarily."""
        return _ActAs(self, login)

    @property
    def current_user(self) -> str:
        return self._actor_stack[-1]

    def create_issue(
        self,
        title: str,
        body: str,
        user: Optional[str] = None,
        labels: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        """Test helper: create a fresh issue in the in-memory state."""
        with self._lock:
            number = self._next_issue_number
            self._next_issue_number += 1
            issue = _Issue(
                number=number,
                title=title,
                body=body,
                user=user or self.current_user,
                labels=list(labels or []),
            )
            self._issues[number] = issue
            self._comments_by_issue[number] = []
            return self._issue_to_dict(issue)

    def create_branch(self, name: str, from_branch: Optional[str] = None) -> str:
        """Create a branch (optionally branching from another). Returns sha."""
        with self._lock:
            if name in self._branches:
                raise ValueError(f"branch already exists: {name}")
            parent_sha: Optional[str] = None
            files: dict[str, bytes] = {}
            if from_branch is not None:
                src = self._branches.get(from_branch)
                if src is None:
                    raise ValueError(f"unknown source branch: {from_branch}")
                parent_sha = src.head_sha
                if parent_sha is not None:
                    files = dict(self._commits[parent_sha].files)
            sha = _new_sha()
            commit = _Commit(
                sha=sha,
                parent=parent_sha,
                message=f"create branch {name}",
                files=files,
            )
            self._commits[sha] = commit
            self._branches[name] = _Branch(name=name, head_sha=sha)
            return sha

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _issue_to_dict(self, issue: _Issue) -> dict[str, Any]:
        return {
            "number": issue.number,
            "title": issue.title,
            "body": issue.body,
            "user": {"login": issue.user},
            "state": issue.state,
            "locked": issue.locked,
            "labels": [{"name": n} for n in issue.labels],
            "created_at": issue.created_at,
            "updated_at": issue.updated_at,
        }

    def _comment_to_dict(self, c: _Comment) -> dict[str, Any]:
        return {
            "id": c.id,
            "issue_number": c.issue_number,
            "user": {"login": c.user},
            "body": c.body,
            "created_at": c.created_at,
            "updated_at": c.updated_at,
        }

    # ------------------------------------------------------------------
    # Issue API
    # ------------------------------------------------------------------
    def get_issue(self, number: int) -> dict[str, Any]:
        with self._lock:
            issue = self._issues.get(number)
            if issue is None:
                raise KeyError(f"no such issue: {number}")
            return self._issue_to_dict(issue)

    def update_issue(
        self,
        number: int,
        body: Optional[str] = None,
        state: Optional[str] = None,
        labels: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        with self._lock:
            issue = self._issues.get(number)
            if issue is None:
                raise KeyError(f"no such issue: {number}")
            if body is not None:
                issue.body = body
            if state is not None:
                if state not in ("open", "closed"):
                    raise ValueError(f"bad state: {state}")
                issue.state = state
            if labels is not None:
                issue.labels = list(labels)
            issue.updated_at = iso_now()
            return self._issue_to_dict(issue)

    def lock_issue(self, number: int) -> None:
        with self._lock:
            issue = self._issues.get(number)
            if issue is None:
                raise KeyError(f"no such issue: {number}")
            issue.locked = True
            issue.updated_at = iso_now()

    def add_label(self, number: int, label: str) -> None:
        with self._lock:
            issue = self._issues.get(number)
            if issue is None:
                raise KeyError(f"no such issue: {number}")
            if label not in issue.labels:
                issue.labels.append(label)
            issue.updated_at = iso_now()

    # ------------------------------------------------------------------
    # Comment API
    # ------------------------------------------------------------------
    def list_comments(self, issue_number: int) -> list[dict[str, Any]]:
        with self._lock:
            ids = self._comments_by_issue.get(issue_number, [])
            return [self._comment_to_dict(self._comments[i]) for i in ids]

    def get_comment(self, comment_id: int) -> dict[str, Any]:
        with self._lock:
            c = self._comments.get(comment_id)
            if c is None:
                raise KeyError(f"no such comment: {comment_id}")
            return self._comment_to_dict(c)

    def update_comment(self, comment_id: int, body: str) -> dict[str, Any]:
        with self._lock:
            c = self._comments.get(comment_id)
            if c is None:
                raise KeyError(f"no such comment: {comment_id}")
            c.body = body
            c.updated_at = iso_now()
            return self._comment_to_dict(c)

    def delete_comment(self, comment_id: int) -> None:
        with self._lock:
            c = self._comments.pop(comment_id, None)
            if c is None:
                return
            self._comments_by_issue.get(c.issue_number, []).remove(comment_id)

    def add_comment(self, issue_number: int, body: str) -> dict[str, Any]:
        with self._lock:
            if issue_number not in self._issues:
                raise KeyError(f"no such issue: {issue_number}")
            cid = self._next_comment_id
            self._next_comment_id += 1
            now = iso_now()
            c = _Comment(
                id=cid,
                issue_number=issue_number,
                user=self.current_user,
                body=body,
                created_at=now,
                updated_at=now,
            )
            self._comments[cid] = c
            self._comments_by_issue.setdefault(issue_number, []).append(cid)
            return self._comment_to_dict(c)

    # ------------------------------------------------------------------
    # Files / branches / commits
    # ------------------------------------------------------------------
    def get_file_contents(self, path: str, ref: str) -> Optional[str]:
        with self._lock:
            branch = self._branches.get(ref)
            if branch is None or branch.head_sha is None:
                return None
            commit = self._commits[branch.head_sha]
            data = commit.files.get(path)
            if data is None:
                return None
            # Returned as text (utf-8) or base64 if binary; we always return
            # decoded utf-8 if possible, else b64. Tests typically compare
            # bytes via separate helpers.
            try:
                return data.decode("utf-8")
            except UnicodeDecodeError:
                return base64.b64encode(data).decode("ascii")

    def get_file_bytes(self, path: str, ref: str) -> Optional[bytes]:
        """Test convenience: raw bytes of a file at ref."""
        with self._lock:
            branch = self._branches.get(ref)
            if branch is None or branch.head_sha is None:
                return None
            commit = self._commits[branch.head_sha]
            return commit.files.get(path)

    def put_file_contents(
        self,
        path: str,
        content_bytes: bytes,
        message: str,
        branch: str,
    ) -> dict[str, Any]:
        with self._lock:
            br = self._branches.get(branch)
            if br is None:
                # Auto-create as orphan branch (no parent)
                br = _Branch(name=branch, head_sha=None)
                self._branches[branch] = br
            parent = br.head_sha
            files = dict(self._commits[parent].files) if parent else {}
            files[path] = content_bytes
            sha = _new_sha()
            commit = _Commit(sha=sha, parent=parent, message=message, files=files)
            self._commits[sha] = commit
            br.head_sha = sha
            return {
                "path": path,
                "branch": branch,
                "commit": {"sha": sha, "message": message},
                "size": len(content_bytes),
            }

    def get_branch_head_sha(self, branch: str) -> Optional[str]:
        with self._lock:
            br = self._branches.get(branch)
            if br is None:
                return None
            return br.head_sha

    def delete_branch(self, name: str) -> None:
        """Delete a branch ref. Idempotent: missing branches are ignored.

        Note: commits are not garbage-collected from the in-memory store —
        only the branch ref is removed (mirrors GitHub's ref-delete semantics).
        """
        with self._lock:
            self._branches.pop(name, None)

    def list_branches(self) -> list[dict[str, Any]]:
        """List all branches as dicts ``{name, sha, protected}``.

        Mirrors a paginated REST ``GET /repos/{owner}/{repo}/branches``
        response shape. The in-memory client has no notion of branch
        protection, so ``protected`` is always ``False``.
        """
        with self._lock:
            return [
                {"name": b.name, "sha": b.head_sha, "protected": False}
                for b in self._branches.values()
            ]

    def commit_files(
        self,
        branch: str,
        files: dict[str, bytes],
        message: str,
    ) -> str:
        """Test helper: commit multiple files atomically. Returns new sha."""
        with self._lock:
            br = self._branches.get(branch)
            if br is None:
                br = _Branch(name=branch, head_sha=None)
                self._branches[branch] = br
            parent = br.head_sha
            current = dict(self._commits[parent].files) if parent else {}
            current.update(files)
            sha = _new_sha()
            self._commits[sha] = _Commit(
                sha=sha, parent=parent, message=message, files=current
            )
            br.head_sha = sha
            return sha

    # ------------------------------------------------------------------
    # PR API
    # ------------------------------------------------------------------
    def create_pull_request(
        self,
        title: str,
        head: str,
        base: str,
        body: str,
    ) -> dict[str, Any]:
        with self._lock:
            if head not in self._branches:
                raise ValueError(f"head branch does not exist: {head}")
            if base not in self._branches:
                raise ValueError(f"base branch does not exist: {base}")
            number = self._next_pr_number
            self._next_pr_number += 1
            pr = _PullRequest(
                number=number,
                title=title,
                head=head,
                base=base,
                body=body,
                user=self.current_user,
            )
            self._pulls[number] = pr
            return self._pr_to_dict(pr)

    def get_pull_request(self, number: int) -> dict[str, Any]:
        with self._lock:
            pr = self._pulls.get(number)
            if pr is None:
                raise KeyError(f"no such PR: {number}")
            return self._pr_to_dict(pr)

    def merge_pull_request(self, number: int) -> dict[str, Any]:
        """Test helper: simulate a merged PR."""
        with self._lock:
            pr = self._pulls.get(number)
            if pr is None:
                raise KeyError(f"no such PR: {number}")
            pr.state = "closed"
            pr.merged = True
            pr.merge_commit_sha = _new_sha()
            return self._pr_to_dict(pr)

    def _pr_to_dict(self, pr: _PullRequest) -> dict[str, Any]:
        return {
            "number": pr.number,
            "title": pr.title,
            "head": {"ref": pr.head},
            "base": {"ref": pr.base},
            "body": pr.body,
            "state": pr.state,
            "merged": pr.merged,
            "merge_commit_sha": pr.merge_commit_sha,
            "user": {"login": pr.user},
            "created_at": pr.created_at,
        }


class _ActAs:
    """Context manager to switch the in-memory client's acting user."""

    def __init__(self, client: InMemoryGitHubClient, login: str) -> None:
        self._client = client
        self._login = login

    def __enter__(self) -> InMemoryGitHubClient:
        self._client._actor_stack.append(self._login)
        return self._client

    def __exit__(self, exc_type, exc, tb) -> None:
        self._client._actor_stack.pop()


def _new_sha() -> str:
    """Generate a 40-character lowercase hex 'sha'."""
    return secrets.token_hex(20)


# ---------------------------------------------------------------------------
# Log sanitisation (SPEC §14)
# ---------------------------------------------------------------------------

# GitHub PAT/OAuth-style tokens.
_RE_GH_TOKEN = re.compile(r"gh[ps]_[A-Za-z0-9]{36,}")
# AWS access key id.
_RE_AWS_KEY = re.compile(r"AKIA[0-9A-Z]{16}")
# Bearer tokens in Authorization-style strings.
_RE_BEARER = re.compile(r"Bearer\s+[A-Za-z0-9._\-]{20,}")
# Generic key=value patterns where the key looks secret-shaped. We
# intentionally redact only the captured group so the rest of the
# string (including the key name and separator) survives for context.
_RE_GENERIC_SECRET = re.compile(
    r"(?i)(?:api[_-]?key|secret|token|password)[\"'\s:=]+([A-Za-z0-9_\-]{16,})"
)


def _sanitize_string(s: str) -> str:
    """Redact common secret patterns in a single string."""
    out = _RE_GH_TOKEN.sub("***", s)
    out = _RE_AWS_KEY.sub("***", out)
    out = _RE_BEARER.sub("Bearer ***", out)

    def _redact_group(m: re.Match[str]) -> str:
        whole = m.group(0)
        captured = m.group(1)
        # Replace just the captured secret value with ``***``.
        start, end = m.span(1)
        # m.span is relative to the whole input string, not to ``whole``.
        return whole[: start - m.start()] + "***" + whole[end - m.start():]

    out = _RE_GENERIC_SECRET.sub(_redact_group, out)
    return out


def sanitize_record(record: dict[str, Any]) -> dict[str, Any]:
    """Return a deep-copied record with common secret patterns redacted.

    Per SPEC §14: log content on a public repo is world-readable, so
    the handler should pass log records through a sanitiser that drops
    anything matching common secret patterns before writing chunks.

    The original ``record`` is NOT mutated.
    """

    def _walk(node: Any) -> Any:
        if isinstance(node, str):
            return _sanitize_string(node)
        if isinstance(node, dict):
            return {k: _walk(v) for k, v in node.items()}
        if isinstance(node, list):
            return [_walk(v) for v in node]
        if isinstance(node, tuple):
            return tuple(_walk(v) for v in node)
        return node

    return _walk(record)


# ---------------------------------------------------------------------------
# LogWriter
# ---------------------------------------------------------------------------

@dataclass
class _ChunkInfo:
    path: str
    bytes_: int
    lines: int
    data: bytes


class LogWriter:
    """Append JSONL records, gzip-rotate at a configured size threshold.

    Usage::

        lw = LogWriter(max_chunk_bytes_compressed=512_000)
        lw.write({"ts": iso_now(), "stream": "stdout", "phase": "exec",
                  "data": "hello"})
        ...
        chunks = lw.finalize()        # list[(path, bytes, dict)]
        manifest = lw.manifest(...)   # build manifest dict

    Records are passed through :func:`sanitize_record` before being
    serialised, unless the writer was constructed with
    ``sanitize=False``.
    """

    def __init__(
        self,
        max_chunk_bytes_compressed: int = 524_288,
        chunk_name_template: str = "log-{n:04d}.jsonl.gz",
        sanitize: bool = True,
    ) -> None:
        self._max = int(max_chunk_bytes_compressed)
        self._template = chunk_name_template
        self._sanitize = bool(sanitize)
        self._buf = io.BytesIO()
        self._gz = gzip.GzipFile(fileobj=self._buf, mode="wb", mtime=0)
        self._cur_lines = 0
        self._chunk_index = 1
        self._chunks: list[_ChunkInfo] = []
        self._closed = False

    # ------------------------------------------------------------------
    def set_max_chunk_bytes(self, max_chunk_bytes_compressed: int) -> None:
        """Update the rotation threshold mid-stream (use sparingly).

        Useful for test commands like chatty that want to force rotation
        at a smaller threshold than the production default.
        """
        if self._closed:
            raise RuntimeError("LogWriter is closed")
        n = int(max_chunk_bytes_compressed)
        if n < 1:
            raise ValueError("max_chunk_bytes_compressed must be >= 1")
        self._max = n

    # ------------------------------------------------------------------
    def _rotate_if_needed(self) -> None:
        # Flush current gzip stream to estimate compressed size.
        self._gz.flush()
        if self._buf.tell() >= self._max and self._cur_lines > 0:
            self._close_current_chunk()
            self._open_new_chunk()

    def _close_current_chunk(self) -> None:
        self._gz.close()
        data = self._buf.getvalue()
        path = self._template.format(n=self._chunk_index)
        self._chunks.append(
            _ChunkInfo(path=path, bytes_=len(data), lines=self._cur_lines, data=data)
        )
        self._chunk_index += 1

    def _open_new_chunk(self) -> None:
        self._buf = io.BytesIO()
        self._gz = gzip.GzipFile(fileobj=self._buf, mode="wb", mtime=0)
        self._cur_lines = 0

    # ------------------------------------------------------------------
    def write(self, record: dict[str, Any]) -> None:
        """Append one JSON record (one line) to the current chunk.

        When ``sanitize=True`` (default), the record is passed through
        :func:`sanitize_record` before serialisation.
        """
        if self._closed:
            raise RuntimeError("LogWriter is closed")
        payload = sanitize_record(record) if self._sanitize else record
        line = (json.dumps(payload, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")
        self._gz.write(line)
        self._cur_lines += 1
        # Rotate after writing so chunks contain at least one line.
        self._rotate_if_needed()

    def finalize(self) -> list[tuple[str, bytes, dict[str, int]]]:
        """Close the writer; return list of ``(path, gz_bytes, info)``.

        ``info`` contains keys ``bytes`` and ``lines``.
        """
        if self._closed:
            return [(c.path, c.data, {"bytes": c.bytes_, "lines": c.lines}) for c in self._chunks]
        # Close current chunk if it has any lines.
        if self._cur_lines > 0:
            self._close_current_chunk()
        else:
            # discard empty buffer
            try:
                self._gz.close()
            except Exception:
                pass
        self._closed = True
        return [(c.path, c.data, {"bytes": c.bytes_, "lines": c.lines}) for c in self._chunks]

    def manifest(
        self,
        *,
        command: str,
        args: dict[str, Any],
        checked_out_sha: str,
        started_at: str,
        finished_at: str,
        exit_code: int,
        protocol_version: int = 1,
        extra_schema_fields: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Build a manifest dict matching ``log-manifest.schema.json``."""
        if not self._closed:
            self.finalize()
        fields = {
            "ts": {"type": "string", "description": "ISO 8601"},
            "stream": {"enum": ["stdout", "stderr", "meta"]},
            "phase": {"enum": ["setup", "exec", "teardown"]},
            "data": {"type": ["string", "object"]},
        }
        if extra_schema_fields:
            fields.update(extra_schema_fields)
        return {
            "protocol_version": protocol_version,
            "schema": {
                "chunk_format": "jsonl-gz",
                "fields": fields,
            },
            "command": command,
            "args": args,
            "checked_out_sha": checked_out_sha,
            "started_at": started_at,
            "finished_at": finished_at,
            "exit_code": exit_code,
            "chunks": [
                {"path": c.path, "bytes": c.bytes_, "lines": c.lines}
                for c in self._chunks
            ],
        }

    # Convenience for tests / debugging
    def chunks(self) -> list[tuple[str, bytes, dict[str, int]]]:
        return self.finalize()


# ---------------------------------------------------------------------------
# Schema loading helpers
# ---------------------------------------------------------------------------

def schemas_root(repo_root: str | os.PathLike[str] = ".") -> Path:
    return Path(repo_root) / ".agent" / "schemas"


def load_schema(name: str, repo_root: str | os.PathLike[str] = ".") -> dict[str, Any]:
    """Load a schema by relative name (e.g. ``commands/run-tests.schema.json``)."""
    p = schemas_root(repo_root) / name
    with p.open("r", encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Misc helpers
# ---------------------------------------------------------------------------

def b64_encode(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return base64.b64encode(data).decode("ascii")


def b64_decode(data: str) -> bytes:
    return base64.b64decode(data.encode("ascii"))


def new_uuid() -> str:
    return str(uuid.uuid4())


def slugify(text: str, max_len: int = 40) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", text.lower()).strip("-")
    return s[:max_len] or "task"


def is_terminal_run_status(status: Optional[str]) -> bool:
    return status in {"completed", "error", "parse_error"}


def has_protocol_markers(obj: Any) -> bool:
    """Return True if a parsed JSON object has ``protocol_version`` and ``kind``."""
    return (
        isinstance(obj, dict)
        and "protocol_version" in obj
        and "kind" in obj
    )


__all__ = [
    "GitHubClient",
    "InMemoryGitHubClient",
    "LogWriter",
    "iso_now",
    "load_config",
    "load_schema",
    "validate",
    "parse_agent_meta",
    "render_agent_meta",
    "b64_encode",
    "b64_decode",
    "new_uuid",
    "slugify",
    "is_terminal_run_status",
    "has_protocol_markers",
    "sanitize_record",
]
