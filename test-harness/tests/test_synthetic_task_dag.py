"""Tests for the task-dag synthetic drivers."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def _common_loadable():
    """Ensure the common module loads (its presence isn't asserted directly)."""
    p = REPO_ROOT / ".agent" / "scripts" / "common.py"
    spec = importlib.util.spec_from_file_location("_harness_agent_common", p)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("_harness_agent_common", mod)
    spec.loader.exec_module(mod)
    yield


class TestStaleTakeover:
    def test_construction_validates_inputs(self):
        import synthetic_drivers

        with pytest.raises(ValueError, match="agent_login"):
            synthetic_drivers.SyntheticTaskDagStaleTakeoverObserver(agent_login="")

    def test_setup_locks_issue(self, tmp_path):
        import synthetic_drivers

        obs = synthetic_drivers.SyntheticTaskDagStaleTakeoverObserver(
            agent_login="alice",
        )
        out = obs("setup", {"pre_lock_with_agent_id": "stale", "stale_age_minutes": 200}, tmp_path, {})
        assert out["issue_number_present"] is True
        assert out["issue_locked"] is True

    def test_claim_evicts_stale_agent(self, tmp_path):
        import synthetic_drivers

        obs = synthetic_drivers.SyntheticTaskDagStaleTakeoverObserver(
            agent_login="alice",
            stale_seconds=60,
        )
        obs("setup", {"stale_age_minutes": 200}, tmp_path, {})
        out = obs("claim", {"agent_id": "fresh-takeover-agent"}, tmp_path, {})
        assert out["claim_succeeded"] is True
        assert out["previous_agent_evicted"] is True

    def test_claim_refuses_when_not_stale(self, tmp_path):
        import synthetic_drivers

        # stale_seconds is 1 hour but the issue is only 1 minute old.
        obs = synthetic_drivers.SyntheticTaskDagStaleTakeoverObserver(
            agent_login="alice",
            stale_seconds=3600,
        )
        obs("setup", {"stale_age_minutes": 1}, tmp_path, {})
        out = obs("claim", {"agent_id": "fresh"}, tmp_path, {})
        assert out["claim_succeeded"] is False
        assert out.get("reason") == "not_stale"

    def test_verify_surfaces_agent_id_and_status(self, tmp_path):
        import synthetic_drivers

        obs = synthetic_drivers.SyntheticTaskDagStaleTakeoverObserver(
            agent_login="alice",
            stale_seconds=60,
        )
        obs("setup", {"stale_age_minutes": 200}, tmp_path, {})
        obs("claim", {"agent_id": "fresh-takeover-agent"}, tmp_path, {})
        out = obs("verify", {}, tmp_path, {})
        # Vocabulary mismatch: YAML expects "claimed", protocol writes "working".
        assert out["meta_status"] == "working"
        assert out["meta_agent_id"] == "fresh-takeover-agent"

    def test_phase_order_enforced(self, tmp_path):
        import synthetic_drivers

        obs = synthetic_drivers.SyntheticTaskDagStaleTakeoverObserver(
            agent_login="alice",
        )
        with pytest.raises(RuntimeError, match="setup phase has not run"):
            obs("claim", {}, tmp_path, {})

    def test_unknown_phase_raises(self, tmp_path):
        import synthetic_drivers

        obs = synthetic_drivers.SyntheticTaskDagStaleTakeoverObserver(
            agent_login="alice",
        )
        with pytest.raises(ValueError, match="unknown phase"):
            obs("nope", {}, tmp_path, {})


class TestMergeConflicts:
    def test_construction_validates_inputs(self):
        import synthetic_drivers

        with pytest.raises(ValueError):
            synthetic_drivers.SyntheticTaskDagMergeConflictsObserver(agent_login="")

    def test_setup_creates_subagent_branches(self, tmp_path):
        import synthetic_drivers

        obs = synthetic_drivers.SyntheticTaskDagMergeConflictsObserver()
        out = obs("setup", {}, tmp_path, {})
        assert out["issue_number_present"] is True
        assert out["subagent_branches_created"] == 2

    def test_merge_detects_conflict_under_fail_strategy(self, tmp_path):
        import synthetic_drivers

        obs = synthetic_drivers.SyntheticTaskDagMergeConflictsObserver()
        obs("setup", {}, tmp_path, {})
        out = obs("merge", {"conflict_strategy": "fail"}, tmp_path, {})
        assert out["merge_attempted"] is True
        assert out["merge_failed"] is True
        assert "shared.py" in out["conflict_paths_present"]

    def test_verify_reports_conflict(self, tmp_path):
        import synthetic_drivers

        obs = synthetic_drivers.SyntheticTaskDagMergeConflictsObserver()
        obs("setup", {}, tmp_path, {})
        obs("merge", {}, tmp_path, {})
        out = obs("verify", {}, tmp_path, {})
        assert out["meta_status"] == "merge_failed"
        assert out["diagnostics_has_conflict_report"] is True
        assert out["conflict_paths"] == ["shared.py"]

    def test_disjoint_subagents_merge_cleanly(self, tmp_path):
        import synthetic_drivers

        obs = synthetic_drivers.SyntheticTaskDagMergeConflictsObserver()
        out = obs(
            "setup",
            {
                "create_subagent_branches": [
                    {"id": "sub-01", "touches": ["a.py"]},
                    {"id": "sub-02", "touches": ["b.py"]},
                ]
            },
            tmp_path,
            {},
        )
        assert out["subagent_branches_created"] == 2
        merge_out = obs("merge", {"conflict_strategy": "fail"}, tmp_path, {})
        assert merge_out["merge_failed"] is False
        verify_out = obs("verify", {}, tmp_path, {})
        assert verify_out["meta_status"] == "merged"
        assert verify_out["diagnostics_has_conflict_report"] is False

    def test_phase_order_enforced(self, tmp_path):
        import synthetic_drivers

        obs = synthetic_drivers.SyntheticTaskDagMergeConflictsObserver()
        with pytest.raises(RuntimeError, match="setup phase has not run"):
            obs("merge", {}, tmp_path, {})

    def test_unknown_phase_raises(self, tmp_path):
        import synthetic_drivers

        obs = synthetic_drivers.SyntheticTaskDagMergeConflictsObserver()
        with pytest.raises(ValueError, match="unknown phase"):
            obs("frob", {}, tmp_path, {})


class TestRunnerCLIs:
    def test_runners_import_with_right_scenario_id(self):
        import importlib

        for runner_name in ("task-dag-stale-takeover", "task-dag-merge-conflicts"):
            mod_path = REPO_ROOT / "test-harness" / "runners" / f"{runner_name}.py"
            spec = importlib.util.spec_from_file_location(
                f"_runner_{runner_name.replace('-', '_')}", mod_path
            )
            assert spec is not None
            mod = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = mod
            spec.loader.exec_module(mod)
            assert mod.SCENARIO_ID == runner_name
