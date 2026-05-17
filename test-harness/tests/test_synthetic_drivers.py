"""Tests for synthetic_drivers.SyntheticBatchJobErrorObserver.

Drives each of the 3 batch-job error scenarios through the real
handler.run function against the in-memory client. Verifies the
terminal envelope shape matches what the scenario YAML expects (or
documents the vocabulary mismatch where the scenario expects a
different error_kind name than the handler emits).
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_common():
    p = REPO_ROOT / ".agent" / "scripts" / "common.py"
    spec = importlib.util.spec_from_file_location("_harness_agent_common", p)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("_harness_agent_common", mod)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def common():
    return _load_common()


def _fake_clock_factory():
    counter = {"t": 0.0}

    def now():
        counter["t"] += 1.0
        return counter["t"]

    return now


def _build(error_mode, **overrides):
    import synthetic_drivers

    defaults = dict(
        error_mode=error_mode,
        agent_login="alice",
        clock=_fake_clock_factory(),
        iso_now=lambda: "2026-05-17T00:00:00Z",
    )
    defaults.update(overrides)
    return synthetic_drivers.SyntheticBatchJobErrorObserver(**defaults)


class TestConstruction:
    def test_rejects_bad_error_mode(self):
        import synthetic_drivers

        with pytest.raises(ValueError, match="error_mode"):
            synthetic_drivers.SyntheticBatchJobErrorObserver(error_mode="bogus")

    def test_requires_agent_login(self):
        import synthetic_drivers

        with pytest.raises(ValueError, match="agent_login"):
            synthetic_drivers.SyntheticBatchJobErrorObserver(
                error_mode="parse_error",
                agent_login="",
            )


class TestParseError:
    def test_handler_writes_terminal_parse_error(self, tmp_path):
        obs = _build("parse_error")
        obs("setup", {}, tmp_path, {})
        invoke_out = obs("invoke", {}, tmp_path, {})
        assert invoke_out["batch_job_comment_present"] is True
        assert invoke_out["envelope_run_status"] == "parse_error"
        verify_out = obs("verify", {}, tmp_path, {})
        assert verify_out["envelope_run_status"] == "parse_error"
        # The handler reports schema_validation_failed; the scenario
        # YAML expects invalid_envelope. Vocabulary mismatch to
        # reconcile upstream — observer returns the literal value.
        assert verify_out["error_kind"] == "schema_validation_failed"


class TestShaMismatch:
    def test_handler_writes_terminal_branch_sha_mismatch(self, tmp_path):
        obs = _build("sha_mismatch")
        obs("setup", {}, tmp_path, {})
        invoke_out = obs(
            "invoke",
            {"commit_sha": "0" * 40, "args": {"message": "stale"}},
            tmp_path,
            {},
        )
        assert invoke_out["envelope_run_status"] == "error"
        verify_out = obs("verify", {}, tmp_path, {})
        assert verify_out["envelope_run_status"] == "error"
        # Vocabulary: handler writes branch_sha_mismatch; YAML expects
        # sha_mismatch.
        assert verify_out["error_kind"] == "branch_sha_mismatch"


class TestPickupTimeout:
    def test_writes_synthetic_pickup_timeout_envelope(self, tmp_path):
        obs = _build("pickup_timeout", pickup_timeout_s=0.0)
        obs("setup", {}, tmp_path, {})
        invoke_out = obs(
            "invoke",
            {"command": "nonexistent-command"},
            tmp_path,
            {},
        )
        assert invoke_out["envelope_run_status"] == "error"
        verify_out = obs("verify", {}, tmp_path, {})
        assert verify_out["envelope_run_status"] == "error"
        # This one matches the scenario YAML literally.
        assert verify_out["error_kind"] == "pickup_timeout"


class TestPhaseOrdering:
    def test_invoke_without_setup_raises(self, tmp_path):
        obs = _build("parse_error")
        with pytest.raises(RuntimeError, match="setup phase has not run"):
            obs("invoke", {}, tmp_path, {})

    def test_verify_without_invoke_raises(self, tmp_path):
        obs = _build("parse_error")
        obs("setup", {}, tmp_path, {})
        with pytest.raises(RuntimeError, match="invoke phase has not run"):
            obs("verify", {}, tmp_path, {})

    def test_unknown_phase_raises(self, tmp_path):
        obs = _build("parse_error")
        with pytest.raises(ValueError, match="unknown phase"):
            obs("xyzzy", {}, tmp_path, {})


class TestRunnerCLIs:
    """The three runners should construct without error and have the
    right SCENARIO_ID."""

    def test_parse_error_runner_imports(self):
        import importlib

        for runner_name in (
            "batch-job-parse-error",
            "batch-job-branch-sha-mismatch",
            "batch-job-runner-pickup-timeout",
        ):
            mod_path = REPO_ROOT / "test-harness" / "runners" / f"{runner_name}.py"
            spec = importlib.util.spec_from_file_location(
                f"_runner_{runner_name.replace('-', '_')}", mod_path
            )
            assert spec is not None
            mod = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = mod
            spec.loader.exec_module(mod)
            assert mod.SCENARIO_ID == runner_name
