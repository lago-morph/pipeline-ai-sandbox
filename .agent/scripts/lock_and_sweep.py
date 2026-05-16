"""``lock-and-sweep`` script (§7.1).

Run on ``issues.opened``. Validates the issue belongs to the protocol
(body contains a parsable ``agent-meta`` block AND the creator is
authorised — see "Authorisation model" below); applies the
``agent-task`` label; sweeps any unauthorised comments that snuck in
before the label was applied.

Historically this script also locked the issue at creation time, but
GitHub refuses comments from ``GITHUB_TOKEN`` (the github-actions[bot]
identity) on locked issues — including the batch-job-handler's own
terminal envelope writes. Locking is therefore deferred to
``close_on_merge.py`` (post-merge), where the lock acts as an
audit-tamper-prevention seal rather than an injection guard. The
injection-guard role is filled by the batch-job-handler workflow's
label + author ``if:`` filter, which makes foreign comments inert.

Authorisation model
-------------------

The script supports two modes, both safe:

1. **Pinned mode** — ``AGENT_LOGIN`` is set (explicit arg or env var).
   The creator's ``login`` must match exactly. Use this for single-bot
   deployments where exactly one identity drives the protocol.

2. **Open mode** — ``AGENT_LOGIN`` is unset (empty). The creator's
   ``author_association`` must be one of ``OWNER``, ``MEMBER``,
   ``COLLABORATOR`` — i.e. they have write access to the repo. Use this
   for multi-user deployments (clones / forks where any maintainer can
   drive the protocol) so the gate is not tied to a personal login.

The comment sweep applies the same rule: in pinned mode, only the
agent's own comments are preserved; in open mode, comments from any
trusted-association author are preserved.

Importable as a module: call :func:`run` directly with a
``GitHubClient`` for tests. The ``__main__`` entry point reads
environment variables and is wired up by the workflow file.
"""

from __future__ import annotations

import os
import sys
from typing import Any, Optional

# When run as a script the package isn't on sys.path; add repo root.
if __package__ in (None, ""):
    _here = os.path.dirname(os.path.abspath(__file__))
    if _here not in sys.path:
        sys.path.insert(0, _here)
    from common import (  # type: ignore[import-not-found]
        GitHubClient,
        load_config,
        parse_agent_meta,
    )
else:
    from .common import GitHubClient, load_config, parse_agent_meta


# GitHub author_association values that imply write access to the repo.
# https://docs.github.com/en/graphql/reference/enums#commentauthorassociation
TRUSTED_ASSOCIATIONS = frozenset({"OWNER", "MEMBER", "COLLABORATOR"})


def _is_trusted(
    *,
    login: Optional[str],
    association: Optional[str],
    agent_login: Optional[str],
) -> bool:
    """Authorisation predicate. See module docstring for the two modes."""
    if agent_login:
        return login == agent_login
    return (association or "").upper() in TRUSTED_ASSOCIATIONS


def run(
    client: GitHubClient,
    issue_number: int,
    agent_login: Optional[str] = None,
    agent_task_label: Optional[str] = None,
    config: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Apply lock-and-sweep behaviour to an issue.

    ``agent_login`` resolution order: explicit argument → ``AGENT_LOGIN``
    environment variable → unset (open mode). See module docstring.

    Returns a small dict describing what happened (useful for tests).
    """
    cfg = config or load_config()
    if agent_login is None:
        agent_login = os.environ.get("AGENT_LOGIN") or None
    agent_task_label = (
        agent_task_label
        or cfg.get("labels", {}).get("agent_task", "agent-task")
    )

    issue = client.get_issue(issue_number)
    body = issue.get("body") or ""
    creator_login = (issue.get("user") or {}).get("login")
    creator_assoc = issue.get("author_association")

    meta = parse_agent_meta(body)
    if meta is None:
        return {"action": "noop", "reason": "no_agent_meta"}
    if not _is_trusted(
        login=creator_login,
        association=creator_assoc,
        agent_login=agent_login,
    ):
        return {
            "action": "noop",
            "reason": (
                "creator_not_agent_login" if agent_login
                else "creator_not_trusted_association"
            ),
        }

    # 1. Apply label.
    client.add_label(issue_number, agent_task_label)

    # 2. Sweep unauthorised comments that snuck in before the label was
    #    applied. We deliberately do NOT lock the issue here: a locked
    #    issue rejects comments from the GITHUB_TOKEN bot identity, and
    #    the batch-job-handler workflow needs to write its terminal
    #    envelope back as a comment. The lock is applied later by
    #    close_on_merge.py once the issue is finished.
    deleted = 0
    kept_unexpected = 0
    for c in client.list_comments(issue_number):
        author = (c.get("user") or {}).get("login")
        assoc = c.get("author_association")
        cid = c["id"]
        if _is_trusted(
            login=author, association=assoc, agent_login=agent_login
        ):
            kept_unexpected += 1
            continue
        client.delete_comment(cid)
        deleted += 1

    return {
        "action": "labeled",
        "label_applied": agent_task_label,
        "deleted_comments": deleted,
        "kept_agent_comments": kept_unexpected,
    }


def main() -> int:
    """``lock-and-sweep`` workflow entry point.

    Required environment variables:
      - ``ISSUE_NUMBER``       the issue that just opened
      - ``GH_TOKEN`` / ``GITHUB_TOKEN``  REST API token
      - ``GITHUB_REPOSITORY``  ``owner/repo`` slug
    Optional:
      - ``AGENT_LOGIN``        bot login to pin against (set from
                                ``vars.AGENT_LOGIN``). When unset, the
                                script falls back to gating on the
                                issue creator's ``author_association``.
      - ``AGENT_TASK_LABEL``   override the label from ``.agent/config.json``

    On success exits 0; on uncaught exception prints to stderr and
    exits 1. Tests call :func:`run` directly with an in-memory client.
    """
    required = ["ISSUE_NUMBER", "GITHUB_TOKEN", "GITHUB_REPOSITORY"]
    print(
        "lock_and_sweep: required env vars: "
        + ", ".join(required)
        + ". Optional: AGENT_LOGIN, AGENT_TASK_LABEL.",
        file=sys.stderr,
    )
    issue_number = os.environ.get("ISSUE_NUMBER")
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    repo_slug = os.environ.get("GITHUB_REPOSITORY")
    agent_login = os.environ.get("AGENT_LOGIN") or None
    missing = [
        name for name, val in (
            ("ISSUE_NUMBER", issue_number),
            ("GITHUB_TOKEN", token),
            ("GITHUB_REPOSITORY", repo_slug),
        ) if not val
    ]
    if missing:
        print(f"lock_and_sweep: missing env vars: {missing}", file=sys.stderr)
        return 1
    assert issue_number is not None and token is not None and repo_slug is not None
    if "/" not in repo_slug:
        print(
            f"lock_and_sweep: GITHUB_REPOSITORY must be 'owner/repo', got: {repo_slug!r}",
            file=sys.stderr,
        )
        return 1
    owner, repo = repo_slug.split("/", 1)
    print(
        f"lock_and_sweep: processing issue #{issue_number}",
        file=sys.stderr,
    )
    try:
        if __package__ in (None, ""):
            from rest_client import RestGitHubClient  # type: ignore[import-not-found]
        else:
            from .rest_client import RestGitHubClient
        client = RestGitHubClient(token=token, owner=owner, repo=repo)
        run(
            client,
            int(issue_number),
            agent_login=agent_login,
            agent_task_label=os.environ.get("AGENT_TASK_LABEL") or None,
        )
    except Exception as exc:  # noqa: BLE001
        import traceback as _tb
        print(f"lock_and_sweep: uncaught exception: {exc!r}", file=sys.stderr)
        _tb.print_exc()
        # Self-diagnostic: post a debug comment on the originating issue.
        if os.environ.get("HANDLER_DEBUG_COMMENT", "1") == "1":
            try:
                if __package__ in (None, ""):
                    from handler import _post_debug_comment  # type: ignore[import-not-found]
                else:
                    from .handler import _post_debug_comment
                _post_debug_comment(
                    token=token,
                    owner=owner,
                    repo=repo,
                    issue_number=int(issue_number),
                    script="lock_and_sweep.py",
                    exc=exc,
                    extra_fields={},
                )
            except Exception as diag_exc:  # noqa: BLE001
                print(
                    f"lock_and_sweep: failed to post debug comment: {diag_exc!r}",
                    file=sys.stderr,
                )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
