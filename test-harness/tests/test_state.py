"""Unit tests for harness state persistence."""
from __future__ import annotations

import json

import pytest

import state


@pytest.fixture(autouse=True)
def _chdir_tmp(tmp_path, monkeypatch):
    """Run each test in a fresh tmpdir so HARNESS_RUNS_ROOT writes don't
    pollute the actual repo."""
    monkeypatch.chdir(tmp_path)
    yield


class TestPhaseDataclass:
    def test_default_status_pending(self):
        ph = state.Phase(name="setup")
        assert ph.status == "pending"
        assert ph.elapsed_s is None
        assert ph.started_at is None
        assert ph.detail == ""
        assert ph.error is None

    def test_to_dict_only_includes_set_fields(self):
        ph = state.Phase(name="setup")
        d = ph.to_dict()
        assert d == {"name": "setup", "status": "pending"}

    def test_to_dict_includes_detail_and_error_when_set(self):
        ph = state.Phase(
            name="invoke",
            status="failed",
            elapsed_s=1.23456,
            started_at="2026-05-17T00:00:00Z",
            detail="2/3 assertions",
            error="something",
        )
        d = ph.to_dict()
        assert d["status"] == "failed"
        assert d["elapsed_s"] == 1.235  # rounded
        assert d["started_at"] == "2026-05-17T00:00:00Z"
        assert d["detail"] == "2/3 assertions"
        assert d["error"] == "something"


class TestLoadOrInit:
    def test_fresh_run_creates_phases(self):
        st = state.load_or_init(
            run_id="r1",
            scenario_id="batch-job-happy-path",
            archetype="python-gha-with-agents-md",
            skill_under_test="batch-job",
            target="synthetic-fixture",
            phase_names=["setup", "invoke", "verify"],
        )
        assert [p.name for p in st.phases] == ["setup", "invoke", "verify"]
        assert all(p.status == "pending" for p in st.phases)
        assert st.run_id == "r1"
        assert st.scenario_id == "batch-job-happy-path"
        assert st.target == "synthetic-fixture"
        assert st.diagnostics == {}

    def test_resumes_from_existing_state(self):
        # Hand-write a state.json that's "partially done".
        p = state.HARNESS_RUNS_ROOT / "r2" / "scenarioX" / "state.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "run_id": "r2",
            "scenario_id": "scenarioX",
            "archetype": "blank-repo",
            "skill_under_test": "onboarding",
            "target": "live-new-repo",
            "github_repo": "x/y",
            "phases": [
                {"name": "setup", "status": "done", "elapsed_s": 0.5},
                {"name": "invoke", "status": "pending"},
            ],
            "diagnostics": {"fixture_dir": "x"},
        }
        p.write_text(json.dumps(payload))
        st = state.load_or_init(
            run_id="r2",
            scenario_id="scenarioX",
            archetype="blank-repo",
            skill_under_test="onboarding",
            target="live-new-repo",
            phase_names=["setup", "invoke"],
        )
        assert st.phases[0].status == "done"
        assert st.phases[0].elapsed_s == 0.5
        assert st.phases[1].status == "pending"
        assert st.github_repo == "x/y"
        assert st.diagnostics == {"fixture_dir": "x"}


class TestPersist:
    def test_writes_state_atomically(self):
        st = state.load_or_init(
            run_id="r1",
            scenario_id="s",
            archetype="a",
            skill_under_test="sk",
            target="synthetic-fixture",
            phase_names=["one"],
        )
        st.phases[0].status = "done"
        state.persist(st)
        p = state.state_path("r1", "s")
        assert p.is_file()
        raw = json.loads(p.read_text())
        assert raw["phases"][0]["status"] == "done"
        # No leftover .tmp.
        tmp = p.with_suffix(".json.tmp")
        assert not tmp.exists()

    def test_persist_then_load_round_trip(self):
        st = state.load_or_init(
            run_id="rX",
            scenario_id="sX",
            archetype="a",
            skill_under_test="sk",
            target="synthetic-fixture",
            phase_names=["setup", "verify"],
        )
        st.diagnostics["k"] = "v"
        state.persist(st)
        # Loading by the same coordinates should return equivalent state.
        loaded = state.load_or_init(
            run_id="rX",
            scenario_id="sX",
            archetype="a",
            skill_under_test="sk",
            target="synthetic-fixture",
            phase_names=["setup", "verify"],
        )
        assert loaded.diagnostics == {"k": "v"}
        assert [p.name for p in loaded.phases] == ["setup", "verify"]


class TestConsoleBlock:
    def test_writes_a_state_block(self, capsys):
        st = state.load_or_init(
            run_id="rb",
            scenario_id="s",
            archetype="a",
            skill_under_test="sk",
            target="synthetic-fixture",
            phase_names=["setup", "invoke", "verify"],
        )
        st.phases[0].status = "done"
        st.phases[1].status = "in_progress"
        state.write_state_block_console(st, next_action="run invoke")
        out = capsys.readouterr().out
        assert "scenario: s" in out
        assert "phase 2/3 (invoke)" in out
        assert "setup" in out and "done" in out
        assert "Next: run invoke" in out


class TestNowIso:
    def test_format(self):
        s = state.now_iso()
        # YYYY-MM-DDTHH:MM:SSZ
        assert len(s) == 20
        assert s.endswith("Z")
        assert s[4] == "-" and s[10] == "T"
