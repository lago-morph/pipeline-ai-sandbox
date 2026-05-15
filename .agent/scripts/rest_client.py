"""Live REST-backed implementation of the :class:`GitHubClient` Protocol.

This is the workflow side of the agent-job protocol: it is invoked from
GitHub Actions runners using ``GITHUB_TOKEN`` and talks to the
GitHub REST API.

The implementation focuses on the operations the workflow scripts need:

- Issues / labels / lock
- Comments (list, get, add, update, delete)
- Files (read, write — including orphan-branch creation for ``_agent_runs``)
- Branches (head SHA lookup, delete)
- Pull requests (create, get)

It also performs:

- Bearer-token auth with the standard GitHub headers.
- Bounded retry-with-backoff for 5xx and rate-limited 403 responses.
- The blob/tree/commit/ref dance required to commit to a fresh
  orphan branch (the Contents API cannot create branches).
"""

from __future__ import annotations

import base64
import time
from typing import Any, Optional

import requests


_DEFAULT_BASE_URL = "https://api.github.com"
_DEFAULT_TIMEOUT = 30.0
_MAX_RETRIES = 5
_BACKOFF_SECONDS = (1.0, 2.0, 4.0, 8.0, 16.0)


class RestGitHubClient:
    """REST implementation of the protocol used by the workflow scripts."""

    def __init__(
        self,
        token: str,
        owner: str,
        repo: str,
        *,
        base_url: str = _DEFAULT_BASE_URL,
        session: Optional[requests.Session] = None,
        timeout: float = _DEFAULT_TIMEOUT,
        sleep: Any = time.sleep,
    ) -> None:
        if not token:
            raise ValueError("token is required")
        if not owner or not repo:
            raise ValueError("owner and repo are required")
        self._token = token
        self._owner = owner
        self._repo = repo
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._session = session or requests.Session()
        self._sleep = sleep

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    @property
    def _repo_path(self) -> str:
        return f"/repos/{self._owner}/{self._repo}"

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "agent-job-protocol-poc",
        }

    def _url(self, path: str) -> str:
        if path.startswith("http://") or path.startswith("https://"):
            return path
        if not path.startswith("/"):
            path = "/" + path
        return self._base_url + path

    def _is_rate_limited(self, resp: requests.Response) -> bool:
        if resp.status_code != 403:
            return False
        # Primary rate limit signalled by remaining=0.
        remaining = resp.headers.get("X-RateLimit-Remaining")
        if remaining == "0":
            return True
        # Secondary rate limit / abuse detection signalled by Retry-After.
        if resp.headers.get("Retry-After"):
            return True
        # Some endpoints simply put it in the body.
        try:
            j = resp.json()
        except ValueError:
            return False
        msg = (j.get("message") or "").lower() if isinstance(j, dict) else ""
        return "rate limit" in msg or "abuse" in msg or "secondary rate" in msg

    def _rate_limit_sleep(self, resp: requests.Response, attempt: int) -> float:
        retry_after = resp.headers.get("Retry-After")
        if retry_after:
            try:
                return max(0.0, float(retry_after))
            except ValueError:
                pass
        reset = resp.headers.get("X-RateLimit-Reset")
        if reset:
            try:
                delta = float(reset) - time.time()
                if delta > 0:
                    # Cap the backoff so a clock-skew or far-future reset
                    # doesn't stall the runner forever.
                    return min(delta, 60.0)
            except ValueError:
                pass
        # Fall back to exponential backoff.
        return _BACKOFF_SECONDS[min(attempt, len(_BACKOFF_SECONDS) - 1)]

    def _request(
        self,
        method: str,
        path: str,
        *,
        json: Any = None,
        params: Optional[dict[str, Any]] = None,
        allow_404: bool = False,
    ) -> requests.Response:
        """Perform an HTTP request with retry on 5xx and rate-limited 403.

        Retries up to ``_MAX_RETRIES`` times. 4xx (other than rate-limited
        403) raise immediately via ``raise_for_status``. When ``allow_404``
        is True, a 404 response is returned without raising.
        """
        url = self._url(path)
        last_resp: Optional[requests.Response] = None
        for attempt in range(_MAX_RETRIES):
            resp = self._session.request(
                method,
                url,
                headers=self._headers(),
                json=json,
                params=params,
                timeout=self._timeout,
            )
            last_resp = resp
            if 200 <= resp.status_code < 300:
                return resp
            if resp.status_code == 404 and allow_404:
                return resp
            # Deterministic client errors: do NOT retry.
            if resp.status_code in (400, 401, 404, 405, 409, 410, 422):
                resp.raise_for_status()
                return resp  # unreachable; for mypy
            # Rate-limited 403: sleep then retry.
            if resp.status_code == 403 and self._is_rate_limited(resp):
                if attempt < _MAX_RETRIES - 1:
                    self._sleep(self._rate_limit_sleep(resp, attempt))
                    continue
                resp.raise_for_status()
                return resp
            # Other 4xx (e.g. plain 403 forbidden) — don't retry.
            if 400 <= resp.status_code < 500:
                resp.raise_for_status()
                return resp
            # 5xx — retry with exponential backoff.
            if attempt < _MAX_RETRIES - 1:
                self._sleep(_BACKOFF_SECONDS[min(attempt, len(_BACKOFF_SECONDS) - 1)])
                continue
            resp.raise_for_status()
            return resp
        assert last_resp is not None
        last_resp.raise_for_status()
        return last_resp  # unreachable

    # ------------------------------------------------------------------
    # Issue API
    # ------------------------------------------------------------------
    def get_issue(self, number: int) -> dict[str, Any]:
        resp = self._request("GET", f"{self._repo_path}/issues/{number}")
        return resp.json()

    def update_issue(
        self,
        number: int,
        body: Optional[str] = None,
        state: Optional[str] = None,
        labels: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        if body is not None:
            payload["body"] = body
        if state is not None:
            payload["state"] = state
        if labels is not None:
            payload["labels"] = list(labels)
        resp = self._request("PATCH", f"{self._repo_path}/issues/{number}", json=payload)
        return resp.json()

    def lock_issue(self, number: int) -> None:
        # PUT /repos/{owner}/{repo}/issues/{n}/lock returns 204 No Content.
        self._request("PUT", f"{self._repo_path}/issues/{number}/lock", json={})

    def add_label(self, number: int, label: str) -> None:
        self._request(
            "POST",
            f"{self._repo_path}/issues/{number}/labels",
            json={"labels": [label]},
        )

    def create_issue(
        self,
        title: str,
        body: str,
        labels: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"title": title, "body": body}
        if labels:
            payload["labels"] = list(labels)
        resp = self._request("POST", f"{self._repo_path}/issues", json=payload)
        return resp.json()

    # ------------------------------------------------------------------
    # Comment API
    # ------------------------------------------------------------------
    def list_comments(self, issue_number: int) -> list[dict[str, Any]]:
        # Paginate by following the Link header's ``rel="next"``.
        out: list[dict[str, Any]] = []
        path = f"{self._repo_path}/issues/{issue_number}/comments"
        params: Optional[dict[str, Any]] = {"per_page": 100}
        while True:
            resp = self._request("GET", path, params=params)
            page = resp.json() or []
            out.extend(page)
            next_url = _next_link(resp.headers.get("Link", ""))
            if not next_url:
                break
            path = next_url
            params = None  # the URL already contains the query string
        return out

    def get_comment(self, comment_id: int) -> dict[str, Any]:
        resp = self._request("GET", f"{self._repo_path}/issues/comments/{comment_id}")
        return resp.json()

    def update_comment(self, comment_id: int, body: str) -> dict[str, Any]:
        resp = self._request(
            "PATCH",
            f"{self._repo_path}/issues/comments/{comment_id}",
            json={"body": body},
        )
        return resp.json()

    def delete_comment(self, comment_id: int) -> None:
        self._request("DELETE", f"{self._repo_path}/issues/comments/{comment_id}")

    def add_comment(self, issue_number: int, body: str) -> dict[str, Any]:
        resp = self._request(
            "POST",
            f"{self._repo_path}/issues/{issue_number}/comments",
            json={"body": body},
        )
        return resp.json()

    # ------------------------------------------------------------------
    # File / branch operations
    # ------------------------------------------------------------------
    def get_file_contents(self, path: str, ref: str) -> Optional[str]:
        """Return the file contents at ``ref`` (utf-8 text or base64).

        Returns ``None`` on 404. Mirrors :class:`InMemoryGitHubClient`:
        attempts utf-8 decoding; returns base64 on failure.
        """
        resp = self._request(
            "GET",
            f"{self._repo_path}/contents/{path}",
            params={"ref": ref},
            allow_404=True,
        )
        if resp.status_code == 404:
            return None
        body = resp.json()
        if isinstance(body, list):
            # ``path`` resolved to a directory — treat like "no file".
            return None
        encoding = body.get("encoding")
        content = body.get("content") or ""
        if encoding == "base64":
            try:
                raw = base64.b64decode(content)
            except (ValueError, base64.binascii.Error):  # type: ignore[attr-defined]
                return content
            try:
                return raw.decode("utf-8")
            except UnicodeDecodeError:
                return base64.b64encode(raw).decode("ascii")
        # Unknown encoding: return as-is.
        return content if isinstance(content, str) else None

    def _get_file_sha(self, path: str, branch: str) -> Optional[str]:
        """Return the blob sha of ``path`` on ``branch`` if it exists."""
        resp = self._request(
            "GET",
            f"{self._repo_path}/contents/{path}",
            params={"ref": branch},
            allow_404=True,
        )
        if resp.status_code == 404:
            return None
        body = resp.json()
        if isinstance(body, list):
            return None
        sha = body.get("sha")
        return sha if isinstance(sha, str) else None

    def put_file_contents(
        self,
        path: str,
        content_bytes: bytes,
        message: str,
        branch: str,
    ) -> dict[str, Any]:
        """Commit a file to ``branch``.

        If ``branch`` does not exist, create it as an orphan via the Git
        Database API (blob/tree/commit with empty parents/ref). If the
        branch exists, prefer the simple Contents API path; if that fails
        we fall back to the Git Database API for the next-commit case
        (blob/tree-with-base/commit-with-parent/patch-ref) so additional
        files on ``_agent_runs`` accumulate into the tree correctly.
        """
        head_sha = self.get_branch_head_sha(branch)
        if head_sha is None:
            return self._create_orphan_commit(path, content_bytes, message, branch)
        # Branch exists — use the Git Database API so the tree is
        # explicitly built from the previous commit, preserving existing
        # files (Contents API would also do this implicitly, but the GDB
        # path is what we tested for orphan-branch follow-ups).
        return self._append_commit(path, content_bytes, message, branch, head_sha)

    def _create_orphan_commit(
        self,
        path: str,
        content_bytes: bytes,
        message: str,
        branch: str,
    ) -> dict[str, Any]:
        blob_sha = self._create_blob(content_bytes)
        tree_sha = self._create_tree(
            [{"path": path, "mode": "100644", "type": "blob", "sha": blob_sha}],
            base_tree=None,
        )
        commit_sha = self._create_commit(message, tree_sha, parents=[])
        # Create the ref; raises if it already exists.
        self._request(
            "POST",
            f"{self._repo_path}/git/refs",
            json={"ref": f"refs/heads/{branch}", "sha": commit_sha},
        )
        return {
            "path": path,
            "branch": branch,
            "commit": {"sha": commit_sha, "message": message},
            "size": len(content_bytes),
        }

    def _append_commit(
        self,
        path: str,
        content_bytes: bytes,
        message: str,
        branch: str,
        parent_sha: str,
    ) -> dict[str, Any]:
        # Get the parent commit's tree sha.
        resp = self._request("GET", f"{self._repo_path}/git/commits/{parent_sha}")
        parent_tree_sha = resp.json()["tree"]["sha"]
        blob_sha = self._create_blob(content_bytes)
        tree_sha = self._create_tree(
            [{"path": path, "mode": "100644", "type": "blob", "sha": blob_sha}],
            base_tree=parent_tree_sha,
        )
        commit_sha = self._create_commit(message, tree_sha, parents=[parent_sha])
        self._request(
            "PATCH",
            f"{self._repo_path}/git/refs/heads/{branch}",
            json={"sha": commit_sha},
        )
        return {
            "path": path,
            "branch": branch,
            "commit": {"sha": commit_sha, "message": message},
            "size": len(content_bytes),
        }

    def _create_blob(self, content_bytes: bytes) -> str:
        b64 = base64.b64encode(content_bytes).decode("ascii")
        resp = self._request(
            "POST",
            f"{self._repo_path}/git/blobs",
            json={"content": b64, "encoding": "base64"},
        )
        return resp.json()["sha"]

    def _create_tree(
        self,
        entries: list[dict[str, Any]],
        *,
        base_tree: Optional[str],
    ) -> str:
        payload: dict[str, Any] = {"tree": entries}
        if base_tree is not None:
            payload["base_tree"] = base_tree
        resp = self._request("POST", f"{self._repo_path}/git/trees", json=payload)
        return resp.json()["sha"]

    def _create_commit(
        self,
        message: str,
        tree_sha: str,
        *,
        parents: list[str],
    ) -> str:
        payload: dict[str, Any] = {
            "message": message,
            "tree": tree_sha,
            "parents": list(parents),
        }
        resp = self._request("POST", f"{self._repo_path}/git/commits", json=payload)
        return resp.json()["sha"]

    def get_branch_head_sha(self, branch: str) -> Optional[str]:
        resp = self._request(
            "GET",
            f"{self._repo_path}/git/refs/heads/{branch}",
            allow_404=True,
        )
        if resp.status_code == 404:
            return None
        body = resp.json()
        # The refs endpoint returns an object for a single match; some
        # variations of the API return a list when the prefix matched
        # multiple refs. Defensive parsing handles both.
        if isinstance(body, list):
            for entry in body:
                if entry.get("ref") == f"refs/heads/{branch}":
                    return entry.get("object", {}).get("sha")
            return None
        obj = body.get("object") or {}
        sha = obj.get("sha")
        return sha if isinstance(sha, str) else None

    def delete_branch(self, name: str) -> None:
        # 404 is treated as success (idempotent), matching the in-memory client.
        resp = self._request(
            "DELETE",
            f"{self._repo_path}/git/refs/heads/{name}",
            allow_404=True,
        )
        if resp.status_code not in (200, 204, 404):
            resp.raise_for_status()

    def list_branches(self) -> list[dict[str, Any]]:
        """List branches in the repo, paginated.

        Returns a list of ``{"name": str, "sha": str, "protected": bool}``
        entries built from the REST ``GET /repos/{owner}/{repo}/branches``
        response. Pagination follows the ``Link: rel="next"`` header.
        """
        out: list[dict[str, Any]] = []
        path = f"{self._repo_path}/branches"
        params: Optional[dict[str, Any]] = {"per_page": 100}
        while True:
            resp = self._request("GET", path, params=params)
            page = resp.json() or []
            for b in page:
                if not isinstance(b, dict):
                    continue
                commit = b.get("commit") or {}
                out.append({
                    "name": b.get("name"),
                    "sha": commit.get("sha"),
                    "protected": bool(b.get("protected", False)),
                })
            next_url = _next_link(resp.headers.get("Link", ""))
            if not next_url:
                break
            path = next_url
            params = None
        return out

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
        resp = self._request(
            "POST",
            f"{self._repo_path}/pulls",
            json={"title": title, "head": head, "base": base, "body": body},
        )
        return resp.json()

    def get_pull_request(self, number: int) -> dict[str, Any]:
        resp = self._request("GET", f"{self._repo_path}/pulls/{number}")
        return resp.json()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _next_link(link_header: str) -> Optional[str]:
    """Parse a ``Link`` header and return the URL with ``rel="next"``."""
    if not link_header:
        return None
    for part in link_header.split(","):
        section = part.strip().split(";")
        if len(section) < 2:
            continue
        url_part = section[0].strip()
        if not (url_part.startswith("<") and url_part.endswith(">")):
            continue
        rel = None
        for s in section[1:]:
            s = s.strip()
            if s.startswith("rel="):
                rel = s.split("=", 1)[1].strip().strip('"')
                break
        if rel == "next":
            return url_part[1:-1]
    return None


__all__ = ["RestGitHubClient"]
