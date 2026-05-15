"""``close-on-merge`` script (§7.3).

Triggered on merged PRs. Reads the PR body for ``Closes #N``, verifies
the linked issue is in ``status: finished``, then closes the issue,
comments the merge SHA, and locks the issue. Locking happens here
(after the close + final comment) rather than at issue creation,
because GitHub refuses comments from ``GITHUB_TOKEN`` on locked
issues — locking earlier would prevent the batch-job-handler workflow
from writing its terminal envelope. Once the issue is closed and
finalised the lock acts as a tamper-prevention seal on the audit
record.
"""

from __future__ import annotations

import os
import re
import sys
from typing import Any, Optional

if __package__ in (None, ""):
    _here = os.path.dirname(os.path.abspath(__file__))
    if _here not in sys.path:
        sys.path.insert(0, _here)
    from common import (  # type: ignore[import-not-found]
        GitHubClient,
        iso_now,
        load_config,
        parse_agent_meta,
    )
else:
    from .common import GitHubClient, iso_now, load_config, parse_agent_meta


_CLOSES_RE = re.compile(
    r"\b(?:closes|closed|close|fixes|fixed|fix|resolves|resolved|resolve)\s+#(\d+)\b",
    re.IGNORECASE,
)


# Branches that must NEVER be deleted by close_on_merge, regardless of
# how the PR head ref or any sub-* match looks. ``main`` is the default
# branch; ``_agent_runs`` is the orphan audit-trail branch (SPEC §6).
_PROTECTED_BRANCHES = frozenset({"main", "_agent_runs"})


def parse_closes_refs(body: Optional[str]) -> list[int]:
    """Return list of issue numbers the PR claims to close."""
    if not body:
        return []
    return [int(m.group(1)) for m in _CLOSES_RE.finditer(body)]


def _safe_to_delete(name: Optional[str]) -> bool:
    """Return True if it's safe to delete this branch.

    Defensive: only branches that start with ``agent/`` are eligible —
    so even if a PR head somehow points at ``main`` or any other
    non-agent branch, we leave it alone.
    """
    if not name:
        return False
    if name in _PROTECTED_BRANCHES:
        return False
    if not name.startswith("agent/"):
        return False
    return True


def _delete_feature_and_subagent_branches(
    client: GitHubClient,
    feature_branch: Optional[str],
) -> list[str]:
    """Delete the feature branch and any ``<feature>--sub-*`` branches.

    Each deletion is wrapped in try/except so a missing or already-deleted
    branch (or any transient REST error) does not fail the workflow. The
    surviving deletions are still applied. Returns the names of branches
    we *attempted to* and successfully deleted (best-effort: the in-memory
    client is fully idempotent; the REST client treats 404 as success).
    """
    if not feature_branch:
        return []
    targets: list[str] = []
    if _safe_to_delete(feature_branch):
        targets.append(feature_branch)
    # Discover subagent branches under the feature.
    sub_prefix = f"{feature_branch}--sub-"
    try:
        branches = client.list_branches()
    except Exception:  # noqa: BLE001
        branches = []
    for b in branches:
        name = b.get("name") if isinstance(b, dict) else None
        if not name or name == feature_branch:
            continue
        if name.startswith(sub_prefix) and _safe_to_delete(name):
            targets.append(name)

    deleted: list[str] = []
    for name in targets:
        try:
            client.delete_branch(name)
            deleted.append(name)
        except Exception:  # noqa: BLE001
            # Swallow: missing/already-deleted branches must not fail the
            # workflow. Other deletions in the batch should still proceed.
            continue
    return deleted


def run(
    client: GitHubClient,
    pr_number: int,
    *,
    config: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Close issues referenced by a merged PR. Returns a result dict."""
    cfg = config or load_config()

    pr = client.get_pull_request(pr_number)
    if not pr.get("merged"):
        return {"action": "noop", "reason": "pr_not_merged"}

    head_ref = (pr.get("head") or {}).get("ref") if isinstance(pr.get("head"), dict) else None

    refs = parse_closes_refs(pr.get("body"))
    if not refs:
        deleted_branches = _delete_feature_and_subagent_branches(client, head_ref)
        return {
            "action": "noop",
            "reason": "no_closes_refs",
            "deleted_branches": deleted_branches,
        }

    closed: list[int] = []
    skipped: list[dict[str, Any]] = []

    for issue_number in refs:
        try:
            issue = client.get_issue(issue_number)
        except KeyError:
            skipped.append({"issue": issue_number, "reason": "missing"})
            continue

        meta = parse_agent_meta(issue.get("body"))
        if meta is None:
            skipped.append({"issue": issue_number, "reason": "no_agent_meta"})
            continue

        if meta.get("status") != "finished":
            skipped.append({
                "issue": issue_number,
                "reason": "not_finished",
                "status": meta.get("status"),
            })
            continue

        if issue.get("state") != "closed":
            client.update_issue(issue_number, state="closed")

        msg = (
            f"Issue closed by merge of #{pr_number} "
            f"(merge_sha={pr.get('merge_commit_sha')}). "
            f"Closed at {iso_now()}."
        )
        client.add_comment(issue_number, msg)
        # Lock the issue post-close as a tamper-prevention seal on the
        # audit record. We could not lock earlier without blocking the
        # batch-job-handler from writing terminal envelopes (GITHUB_TOKEN
        # cannot comment on locked issues).
        if not issue.get("locked"):
            client.lock_issue(issue_number)
        closed.append(issue_number)

    deleted_branches = _delete_feature_and_subagent_branches(client, head_ref)

    return {
        "action": "closed",
        "issues_closed": closed,
        "skipped": skipped,
        "deleted_branches": deleted_branches,
    }


def main() -> int:
    """``close-on-merge`` workflow entry point.

    Required environment variables:
      - ``PR_NUMBER``          the merged pull request number
      - ``GH_TOKEN`` / ``GITHUB_TOKEN``  REST API token
      - ``GITHUB_REPOSITORY``  ``owner/repo`` slug

    On success exits 0; on uncaught exception prints to stderr and
    exits 1. Tests call :func:`run` directly with an in-memory client.
    """
    required = ["PR_NUMBER", "GITHUB_TOKEN", "GITHUB_REPOSITORY"]
    print(
        "close_on_merge: required env vars: " + ", ".join(required) + ".",
        file=sys.stderr,
    )
    pr_number = os.environ.get("PR_NUMBER")
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    repo_slug = os.environ.get("GITHUB_REPOSITORY")
    missing = [
        name for name, val in (
            ("PR_NUMBER", pr_number),
            ("GITHUB_TOKEN", token),
            ("GITHUB_REPOSITORY", repo_slug),
        ) if not val
    ]
    if missing:
        print(f"close_on_merge: missing env vars: {missing}", file=sys.stderr)
        return 1
    assert pr_number is not None and token is not None and repo_slug is not None
    if "/" not in repo_slug:
        print(
            f"close_on_merge: GITHUB_REPOSITORY must be 'owner/repo', got: {repo_slug!r}",
            file=sys.stderr,
        )
        return 1
    owner, repo = repo_slug.split("/", 1)
    print(
        f"close_on_merge: handling PR #{pr_number}",
        file=sys.stderr,
    )
    try:
        if __package__ in (None, ""):
            from rest_client import RestGitHubClient  # type: ignore[import-not-found]
        else:
            from .rest_client import RestGitHubClient
        client = RestGitHubClient(token=token, owner=owner, repo=repo)
        run(client, int(pr_number))
    except Exception as exc:  # noqa: BLE001
        import traceback as _tb
        print(f"close_on_merge: uncaught exception: {exc!r}", file=sys.stderr)
        _tb.print_exc()
        # Self-diagnostic: post a debug comment. Prefer the issue named in
        # ``Closes #N`` (best-effort PR body fetch); otherwise fall back
        # to the PR itself, since PRs are issues to GitHub's REST API.
        if os.environ.get("HANDLER_DEBUG_COMMENT", "1") == "1":
            try:
                if __package__ in (None, ""):
                    from handler import _post_debug_comment  # type: ignore[import-not-found]
                else:
                    from .handler import _post_debug_comment
                target_issue = int(pr_number)
                try:
                    import requests as _requests
                    pr_resp = _requests.get(
                        f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}",
                        headers={
                            "Authorization": f"Bearer {token}",
                            "Accept": "application/vnd.github+json",
                            "X-GitHub-Api-Version": "2022-11-28",
                        },
                        timeout=15,
                    )
                    if pr_resp.status_code < 300:
                        refs = parse_closes_refs((pr_resp.json() or {}).get("body"))
                        if refs:
                            target_issue = refs[0]
                except Exception:  # noqa: BLE001
                    pass  # fall back to PR
                _post_debug_comment(
                    token=token,
                    owner=owner,
                    repo=repo,
                    issue_number=target_issue,
                    script="close_on_merge.py",
                    exc=exc,
                    extra_fields={"pr": pr_number},
                )
            except Exception as diag_exc:  # noqa: BLE001
                print(
                    f"close_on_merge: failed to post debug comment: {diag_exc!r}",
                    file=sys.stderr,
                )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
