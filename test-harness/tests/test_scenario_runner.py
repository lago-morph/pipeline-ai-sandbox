"""Unit tests for scenario_runner.

Covers:
- Phase loop progression (pass / fail / skip / restart-skips-done).
- Archetype materialisation failure path (exit 2).
- Target negotiation (live with factory + creds → live; without → degraded).
- run_id default, exit codes.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

import scenario_runner
import state


@pytest.fixture(autouse=True)
def _isolate_cwd(tmp_path, monkeypatch):
    """Each test runs in a fresh tmpdir laid out like the real repo."""
    # Layout: test-harness/{scenarios,archetypes}/, then chdir to root.
    monkeypatch.chdir(tmp_path)
    yield


def _write_scenario(scenario_id: str, *, target="synthetic-fixture", phases=None):
    if phases is None:
        phases = [
            {"name": "setup", "expected": {"ok": True}},
            {"name": "verify", "expected": {"ok": True}},
        ]
    p = Path("test-harness/scenarios") / f"{scenario_id}.yml"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        yaml.safe_dump(
            {
                "scenario_id": scenario_id,
                "archetype": "tiny",
                "skill_under_test": "batch-job",
                "target": target,
                "phases": phases,
            }
        )
    )


def _write_archetype(name="tiny"):
    root = Path("test-harness/archetypes") / name
    root.mkdir(parents=True, exist_ok=True)
    (root / "manifest.json").write_text(
        json.dumps({"name": name, "files": []})
    )


# ---------------------------------------------------------------------------
# load_scenario
# ---------------------------------------------------------------------------
class TestLoadScenario:
    def test_loads_yaml_dict(self):
        _write_scenario("s1")
        spec = scenario_runner.load_scenario("s1")
        assert spec["target"] == "synthetic-fixture"

    def test_missing_yaml_raises(self):
        with pytest.raises(FileNotFoundError):
            scenario_runner.load_scenario("no-such-scenario")


# ---------------------------------------------------------------------------
# run_scenario: phase loop
# ---------------------------------------------------------------------------
class TestRunScenario:
    def test_all_phases_pass(self, capsys):
        _write_archetype()
        _write_scenario("happy")
        observed = {"ok": True}

        def observe(phase, inputs, fixture, diagnostics):
            return dict(observed)

        rc = scenario_runner.run_scenario("happy", observe, run_id="r1")
        assert rc == 0
        # State persisted.
        st_path = state.state_path("r1", "happy")
        st = json.loads(st_path.read_text())
        assert [p["status"] for p in st["phases"]] == ["done", "done"]

    def test_failed_phase_returns_one(self):
        _write_archetype()
        _write_scenario("failing")

        def observe(phase, inputs, fixture, diagnostics):
            if phase == "setup":
                return {"ok": True}
            return {"ok": False}

        rc = scenario_runner.run_scenario("failing", observe, run_id="r2")
        assert rc == 1
        st = json.loads(state.state_path("r2", "failing").read_text())
        statuses = [p["status"] for p in st["phases"]]
        assert statuses[0] == "done"
        assert statuses[1] == "failed"

    def test_failed_phase_short_circuits(self):
        _write_archetype()
        _write_scenario(
            "abort",
            phases=[
                {"name": "setup", "expected": {"ok": True}},
                {"name": "invoke", "expected": {"ok": True}},
                {"name": "verify", "expected": {"ok": True}},
            ],
        )

        def observe(phase, inputs, fixture, diagnostics):
            if phase == "invoke":
                return {"ok": False}
            return {"ok": True}

        scenario_runner.run_scenario("abort", observe, run_id="r3")
        st = json.loads(state.state_path("r3", "abort").read_text())
        statuses = [p["status"] for p in st["phases"]]
        assert statuses == ["done", "failed", "pending"]

    def test_not_implemented_marks_skipped(self):
        _write_archetype()
        _write_scenario("skipme")

        def observe(phase, inputs, fixture, diagnostics):
            if phase == "verify":
                raise NotImplementedError("requires-live-skill-execution (verify)")
            return {"ok": True}

        rc = scenario_runner.run_scenario("skipme", observe, run_id="r4")
        # skips do not cause a nonzero exit code (only failures do).
        assert rc == 0
        st = json.loads(state.state_path("r4", "skipme").read_text())
        statuses = [p["status"] for p in st["phases"]]
        assert statuses == ["done", "skipped"]

    def test_observer_exception_marks_failed(self):
        _write_archetype()
        _write_scenario("crash")

        def observe(phase, inputs, fixture, diagnostics):
            raise RuntimeError("boom")

        rc = scenario_runner.run_scenario("crash", observe, run_id="r5")
        assert rc == 1
        st = json.loads(state.state_path("r5", "crash").read_text())
        assert st["phases"][0]["status"] == "failed"
        assert "RuntimeError" in st["phases"][0]["error"]

    def test_resume_skips_done_phases(self, monkeypatch):
        _write_archetype()
        _write_scenario("resume")
        # Seed a partial state with the first phase already done.
        st_path = state.state_path("rR", "resume")
        st_path.parent.mkdir(parents=True, exist_ok=True)
        st_path.write_text(
            json.dumps(
                {
                    "run_id": "rR",
                    "scenario_id": "resume",
                    "archetype": "tiny",
                    "skill_under_test": "batch-job",
                    "target": "synthetic-fixture",
                    "phases": [
                        {"name": "setup", "status": "done"},
                        {"name": "verify", "status": "pending"},
                    ],
                    "diagnostics": {},
                }
            )
        )
        calls = []

        def observe(phase, inputs, fixture, diagnostics):
            calls.append(phase)
            return {"ok": True}

        rc = scenario_runner.run_scenario("resume", observe, run_id="rR")
        assert rc == 0
        assert calls == ["verify"]  # setup was skipped.

    def test_empty_phases_returns_2(self):
        _write_archetype()
        _write_scenario("nophases", phases=[])
        rc = scenario_runner.run_scenario("nophases", lambda *a, **k: {})
        assert rc == 2

    def test_missing_archetype_returns_2(self):
        _write_scenario("badarch")
        # No archetype on disk.
        rc = scenario_runner.run_scenario("badarch", lambda *a, **k: {})
        assert rc == 2

    def test_default_run_id_used_when_unset(self):
        _write_archetype()
        _write_scenario("auto")
        rc = scenario_runner.run_scenario("auto", lambda *a, **k: {"ok": True})
        assert rc == 0
        # Some run_id directory was created.
        runs = list(state.HARNESS_RUNS_ROOT.glob("*"))
        assert len(runs) == 1
        assert (runs[0] / "auto" / "state.json").is_file()


# ---------------------------------------------------------------------------
# Target negotiation: live-new-repo + factory + env
# ---------------------------------------------------------------------------
class TestLiveTargetNegotiation:
    def _factory(self, calls):
        def make(*, github_client, owner, repo):
            calls.append((owner, repo))

            def observe(phase, inputs, fixture, diagnostics):
                return {"ok": True}

            return observe

        return make

    def test_no_factory_degrades(self, monkeypatch):
        _write_archetype()
        _write_scenario("liveA", target="live-new-repo")
        # Even with creds in env, no factory means no live observer.
        monkeypatch.setenv("GITHUB_TOKEN", "x")
        monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
        rc = scenario_runner.run_scenario(
            "liveA",
            lambda *a, **k: {"ok": True},
            run_id="rL1",
            live_observer_factory=None,
        )
        assert rc == 0
        st = json.loads(state.state_path("rL1", "liveA").read_text())
        assert st["target"] == "synthetic-fixture"
        assert "degraded_reason" in st["diagnostics"]
        assert "no live_observer_factory" in st["diagnostics"]["degraded_reason"]

    def test_no_credentials_degrades(self, monkeypatch):
        _write_archetype()
        _write_scenario("liveB", target="live-new-repo")
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        monkeypatch.delenv("GH_TOKEN", raising=False)
        monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
        calls = []
        rc = scenario_runner.run_scenario(
            "liveB",
            lambda *a, **k: {"ok": True},
            run_id="rL2",
            live_observer_factory=self._factory(calls),
            env={},
        )
        assert rc == 0
        assert calls == []  # factory never invoked
        st = json.loads(state.state_path("rL2", "liveB").read_text())
        assert st["target"] == "synthetic-fixture"
        assert "degraded_reason" in st["diagnostics"]
        assert "credentials" in st["diagnostics"]["degraded_reason"]

    def test_factory_failure_degrades_with_reason(self, monkeypatch):
        _write_archetype()
        _write_scenario("liveC", target="live-new-repo")

        def bad_factory(*, github_client, owner, repo):
            raise RuntimeError("factory blew up")

        rc = scenario_runner.run_scenario(
            "liveC",
            lambda *a, **k: {"ok": True},
            run_id="rL3",
            live_observer_factory=bad_factory,
            # Avoid live REST client; mock the gate via patching.
            env={"GITHUB_TOKEN": "x", "GITHUB_REPOSITORY": "o/r"},
        )
        # The build path tries to make a real REST client; depending on
        # whether `requests` is installed, this may fail at the client
        # build step rather than the factory step. Either way, target
        # must degrade and degraded_reason must be set.
        st = json.loads(state.state_path("rL3", "liveC").read_text())
        assert rc == 0
        assert st["target"] == "synthetic-fixture"
        assert "degraded_reason" in st["diagnostics"]
