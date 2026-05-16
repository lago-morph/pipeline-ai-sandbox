"""Per-scenario state persistence and console state-block emission.

State files live at `harness/runs/<run_id>/<scenario_id>/state.json`
inside the repo (relative to the working directory).
"""
from __future__ import annotations

import json
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


HARNESS_RUNS_ROOT = Path("harness/runs")


@dataclass
class Phase:
    name: str
    status: str = "pending"
    elapsed_s: float | None = None
    started_at: str | None = None
    detail: str = ""
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d = {"name": self.name, "status": self.status}
        if self.elapsed_s is not None:
            d["elapsed_s"] = round(self.elapsed_s, 3)
        if self.started_at is not None:
            d["started_at"] = self.started_at
        if self.detail:
            d["detail"] = self.detail
        if self.error is not None:
            d["error"] = self.error
        return d


@dataclass
class RunState:
    run_id: str
    scenario_id: str
    archetype: str
    skill_under_test: str
    target: str
    github_repo: str | None = None
    phases: list[Phase] = field(default_factory=list)
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["phases"] = [p.to_dict() for p in self.phases]
        return d


def state_path(run_id: str, scenario_id: str) -> Path:
    return HARNESS_RUNS_ROOT / run_id / scenario_id / "state.json"


def load_or_init(
    run_id: str,
    scenario_id: str,
    archetype: str,
    skill_under_test: str,
    target: str,
    phase_names: list[str],
) -> RunState:
    p = state_path(run_id, scenario_id)
    if p.exists():
        raw = json.loads(p.read_text())
        phases = [Phase(**ph) for ph in raw.get("phases", [])]
        return RunState(
            run_id=raw["run_id"],
            scenario_id=raw["scenario_id"],
            archetype=raw["archetype"],
            skill_under_test=raw["skill_under_test"],
            target=raw["target"],
            github_repo=raw.get("github_repo"),
            phases=phases,
            diagnostics=raw.get("diagnostics", {}),
        )
    return RunState(
        run_id=run_id,
        scenario_id=scenario_id,
        archetype=archetype,
        skill_under_test=skill_under_test,
        target=target,
        phases=[Phase(name=n) for n in phase_names],
    )


def persist(state: RunState) -> None:
    p = state_path(state.run_id, state.scenario_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state.to_dict(), indent=2) + "\n")
    tmp.replace(p)


def write_state_block_console(state: RunState, next_action: str = "") -> None:
    n = len(state.phases)
    cur = None
    for i, ph in enumerate(state.phases, start=1):
        if ph.status in ("in_progress", "ready", "pending"):
            cur = i
            cur_name = ph.name
            break
    if cur is None:
        cur = n
        cur_name = state.phases[-1].name if state.phases else "(none)"
    print(
        f"[test-harness . scenario: {state.scenario_id} . phase {cur}/{n} ({cur_name})]"
    )
    width = max((len(p.name) for p in state.phases), default=0) + 1
    for ph in state.phases:
        line = f"  {ph.name:<{width}} {ph.status}"
        if ph.detail:
            line += f"  ({ph.detail})"
        print(line)
    if next_action:
        print(f"Next: {next_action}")
    sys.stdout.flush()


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
