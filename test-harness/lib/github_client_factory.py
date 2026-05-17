"""Resolve a live :class:`GitHubClient` from the environment.

The harness can drive scenarios live against real GitHub when:

- ``GITHUB_TOKEN`` (or ``GH_TOKEN``) is set, and
- ``GITHUB_REPOSITORY`` (in ``owner/repo`` form) is set, OR the working
  directory's ``origin`` remote resolves to a GitHub repo.

The factory imports :class:`RestGitHubClient` lazily so test-harness
code that doesn't need a live client (synthetic-fixture scenarios) can
still import this module without pulling ``requests`` into the process.
"""
from __future__ import annotations

import os
import re
import subprocess
from typing import Any, Optional, Tuple


def resolve_token(env: Optional[dict[str, str]] = None) -> Optional[str]:
    """Return the token from ``GITHUB_TOKEN`` / ``GH_TOKEN`` or ``None``."""
    e = env if env is not None else os.environ
    return e.get("GITHUB_TOKEN") or e.get("GH_TOKEN") or None


def resolve_repo(
    env: Optional[dict[str, str]] = None,
    *,
    git_remote_runner: Optional[Any] = None,
) -> Optional[Tuple[str, str]]:
    """Return ``(owner, repo)`` resolved from env or ``origin`` remote.

    Priority:
      1. ``GITHUB_REPOSITORY`` environment variable (``owner/repo``).
      2. The git ``origin`` remote URL, if it points to github.com.

    ``git_remote_runner`` is injected in tests; it receives the args
    list and returns the stdout text.
    """
    e = env if env is not None else os.environ
    slug = e.get("GITHUB_REPOSITORY")
    if slug and "/" in slug:
        owner, _, repo = slug.partition("/")
        owner = owner.strip()
        repo = repo.strip().removesuffix(".git")
        if owner and repo:
            return owner, repo
    runner = git_remote_runner or _git_remote_get_url
    try:
        url = runner(["git", "remote", "get-url", "origin"])
    except Exception:
        return None
    return parse_github_remote(url)


def parse_github_remote(url: Optional[str]) -> Optional[Tuple[str, str]]:
    """Parse a github remote URL into ``(owner, repo)``."""
    if not url:
        return None
    s = url.strip()
    # https://github.com/owner/repo(.git)
    m = re.match(r"^https?://github\.com/([^/]+)/([^/]+?)(?:\.git)?/?$", s)
    if m:
        return m.group(1), m.group(2)
    # git@github.com:owner/repo(.git)
    m = re.match(r"^git@github\.com:([^/]+)/([^/]+?)(?:\.git)?$", s)
    if m:
        return m.group(1), m.group(2)
    # ssh://git@github.com/owner/repo(.git)
    m = re.match(r"^ssh://git@github\.com/([^/]+)/([^/]+?)(?:\.git)?/?$", s)
    if m:
        return m.group(1), m.group(2)
    return None


def _git_remote_get_url(args: list[str]) -> str:
    out = subprocess.check_output(args, text=True, stderr=subprocess.STDOUT)
    return out.strip()


def can_make_live_client(env: Optional[dict[str, str]] = None) -> bool:
    """Return True iff the environment has enough to build a live client."""
    if resolve_token(env) is None:
        return False
    if resolve_repo(env) is None:
        return False
    return True


def make_live_client(env: Optional[dict[str, str]] = None) -> Any:
    """Construct a :class:`RestGitHubClient` from the resolved env.

    Raises ``RuntimeError`` if either the token or the repo can't be
    resolved. Callers should use :func:`can_make_live_client` first if
    they want a soft fallback.
    """
    token = resolve_token(env)
    if not token:
        raise RuntimeError(
            "no GitHub token in environment "
            "(set GITHUB_TOKEN or GH_TOKEN)"
        )
    repo = resolve_repo(env)
    if repo is None:
        raise RuntimeError(
            "could not resolve owner/repo "
            "(set GITHUB_REPOSITORY or run from a clone with origin pointing "
            "to a GitHub repo)"
        )
    owner, name = repo
    # Lazy import keeps `requests` out of the import graph for users that
    # only do synthetic-fixture work.
    import importlib.util
    import sys
    from pathlib import Path

    rest_client_path = (
        Path(__file__).resolve().parents[2] / ".agent" / "scripts" / "rest_client.py"
    )
    spec = importlib.util.spec_from_file_location(
        "_harness_rest_client", rest_client_path
    )
    if spec is None or spec.loader is None:  # pragma: no cover
        raise RuntimeError(
            f"could not locate rest_client.py at {rest_client_path}"
        )
    mod = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("_harness_rest_client", mod)
    spec.loader.exec_module(mod)
    return mod.RestGitHubClient(token=token, owner=owner, repo=name)


__all__ = [
    "can_make_live_client",
    "make_live_client",
    "parse_github_remote",
    "resolve_repo",
    "resolve_token",
]
