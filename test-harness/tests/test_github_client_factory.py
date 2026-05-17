"""Unit tests for github_client_factory."""
from __future__ import annotations

import pytest

import github_client_factory as gcf


class TestResolveToken:
    def test_github_token(self):
        assert gcf.resolve_token({"GITHUB_TOKEN": "abc"}) == "abc"

    def test_gh_token_fallback(self):
        assert gcf.resolve_token({"GH_TOKEN": "xyz"}) == "xyz"

    def test_github_token_wins_over_gh_token(self):
        assert gcf.resolve_token({"GITHUB_TOKEN": "a", "GH_TOKEN": "b"}) == "a"

    def test_no_token(self):
        assert gcf.resolve_token({}) is None

    def test_empty_string_is_none(self):
        assert gcf.resolve_token({"GITHUB_TOKEN": ""}) is None


class TestParseGithubRemote:
    @pytest.mark.parametrize(
        "url, expected",
        [
            ("https://github.com/o/r", ("o", "r")),
            ("https://github.com/o/r.git", ("o", "r")),
            ("https://github.com/o/r/", ("o", "r")),
            ("http://github.com/o/r", ("o", "r")),
            ("git@github.com:o/r", ("o", "r")),
            ("git@github.com:o/r.git", ("o", "r")),
            ("ssh://git@github.com/o/r.git", ("o", "r")),
        ],
    )
    def test_parses(self, url, expected):
        assert gcf.parse_github_remote(url) == expected

    @pytest.mark.parametrize(
        "url",
        [
            "",
            None,
            "not-a-url",
            "https://gitlab.com/o/r",
            "https://github.com/single-segment",
        ],
    )
    def test_rejects(self, url):
        assert gcf.parse_github_remote(url) is None


class TestResolveRepo:
    def test_env_var_wins(self):
        out = gcf.resolve_repo({"GITHUB_REPOSITORY": "foo/bar"})
        assert out == ("foo", "bar")

    def test_env_var_strips_dot_git(self):
        out = gcf.resolve_repo({"GITHUB_REPOSITORY": "foo/bar.git"})
        assert out == ("foo", "bar")

    def test_falls_back_to_remote(self):
        def runner(args):
            assert args == ["git", "remote", "get-url", "origin"]
            return "git@github.com:o/r.git\n"

        out = gcf.resolve_repo({}, git_remote_runner=runner)
        assert out == ("o", "r")

    def test_git_runner_error_returns_none(self):
        def runner(args):
            raise RuntimeError("no git")

        assert gcf.resolve_repo({}, git_remote_runner=runner) is None

    def test_remote_non_github_returns_none(self):
        def runner(args):
            return "https://gitlab.com/o/r"

        assert gcf.resolve_repo({}, git_remote_runner=runner) is None

    def test_malformed_env_repo_falls_back_to_remote(self):
        # GITHUB_REPOSITORY without slash → use remote.
        def runner(args):
            return "git@github.com:from/remote"

        out = gcf.resolve_repo(
            {"GITHUB_REPOSITORY": "no-slash"}, git_remote_runner=runner
        )
        assert out == ("from", "remote")


class TestCanMakeLiveClient:
    def test_true_with_token_and_repo(self):
        assert (
            gcf.can_make_live_client(
                {"GITHUB_TOKEN": "x", "GITHUB_REPOSITORY": "o/r"}
            )
            is True
        )

    def test_false_without_token(self):
        assert (
            gcf.can_make_live_client({"GITHUB_REPOSITORY": "o/r"}) is False
        )

    def test_false_without_repo(self, monkeypatch):
        # Force resolve_repo's git-remote fallback to fail.
        monkeypatch.setattr(
            gcf,
            "_git_remote_get_url",
            lambda args: (_ for _ in ()).throw(RuntimeError("nope")),
        )
        assert gcf.can_make_live_client({"GITHUB_TOKEN": "x"}) is False


class TestMakeLiveClient:
    def test_raises_without_token(self):
        with pytest.raises(RuntimeError, match="token"):
            gcf.make_live_client({})

    def test_raises_without_repo(self, monkeypatch):
        monkeypatch.setattr(
            gcf,
            "_git_remote_get_url",
            lambda args: (_ for _ in ()).throw(RuntimeError("nope")),
        )
        with pytest.raises(RuntimeError, match="owner/repo"):
            gcf.make_live_client({"GITHUB_TOKEN": "x"})

    def test_builds_real_client_when_env_present(self):
        # The factory imports `requests` lazily. If requests is not
        # installed, this test is meaningfully a smoke test of the
        # import-path; we skip in that case.
        pytest.importorskip("requests")
        client = gcf.make_live_client(
            {"GITHUB_TOKEN": "fake-token", "GITHUB_REPOSITORY": "o/r"}
        )
        # The returned object should look like RestGitHubClient.
        assert client.__class__.__name__ == "RestGitHubClient"
