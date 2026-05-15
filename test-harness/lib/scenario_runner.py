"""Generic scenario runner.

Each `test-harness/runners/<scenario_id>.py` calls
`run_scenario(scenario_yaml_path, observe_fn)` with an `observe_fn` that
turns a phase's `inputs` + the current fixture into the `observed`
dict that assertions are evaluated against.

The runner is **target-aware**:

- `synthetic-fixture`: materialise the archetype into a temp dir;
  observe_fn runs against that dir; no GitHub interaction.
- `live-new-repo`: would create a live GitHub repo; in this dispatcher
  environment the MCP scope does not permit fresh-repo creation, so
  live-new-repo scenarios degrade to synthetic-fixture and record
  `degraded_reason` in state diagnostics.

Each runner is invokable as a CLI:

    python test-harness/runners/<scenario_id>.py [--run-id ID] [--target T]

It exits 0 on full success, 1 on assertion failure, 2 on infrastructure
failure (archetype not found, YAML parse error, etc).
"""
from __future__ import annotations

import argparse
import os
import sys
import time
import traceback
from pathlib import Path
from typing import Any, Callable

import yaml

# Allow `from lib import ...` when this file is imported by a runner.
_HERE = Path(__file__).resolve()
_LIB_DIR = _HERE.parent
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

import archetype_loader  # noqa: E402
import assertions  # noqa: E402
import state  # noqa: E402


ObserveFn = Callable[[str, dict, Path, dict], dict[str, Any]]


def _default_run_id() -> str:
    return time.strftime("%Y%m%d-%H%M%S", time.gmtime())


def load_scenario(scenario_id: str) -> dict:
    p = Path("test-harness/scenarios") / f"{scenario_id}.yml"
    if not p.is_file():
        raise FileNotFoundError(f"scenario YAML not found: {p}")
    return yaml.safe_load(p.read_text())


def run_scenario(
    scenario_id: str,
    observe_fn: ObserveFn,
    *,
    run_id: str | None = None,
    target_override: str | None = None,
) -> int:
    spec = load_scenario(scenario_id)

    archetype = spec.get("archetype")
    skill = spec.get("skill_under_test")
    target = target_override or spec.get("target", "synthetic-fixture")
    phases = spec.get("phases", [])
    if not isinstance(phases, list) or not phases:
        sys.stderr.write(f"scenario {scenario_id}: no phases defined\n")
        return 2

    phase_names = [p["name"] for p in phases]
    run_id = run_id or _default_run_id()
    st = state.load_or_init(
        run_id=run_id,
        scenario_id=scenario_id,
        archetype=archetype,
        skill_under_test=skill,
        target=target,
        phase_names=phase_names,
    )

    # Materialise the archetype (always synthetic in this environment).
    fixture_dir = state.HARNESS_RUNS_ROOT / run_id / scenario_id / "fixture"
    try:
        manifest = archetype_loader.materialise(archetype, fixture_dir)
    except Exception as exc:
        st.phases[0].status = "failed"
        st.phases[0].error = f"archetype_materialise: {exc}"
        state.persist(st)
        state.write_state_block_console(st, next_action="abort")
        return 2

    # Record degradation when scenario asked for live-new-repo.
    if target == "live-new-repo":
        st.diagnostics["degraded_reason"] = (
            "MCP scope restricted to current repo; cannot create test repos. "
            "Running as synthetic-fixture instead."
        )
        st.target = "synthetic-fixture"

    st.diagnostics.setdefault("fixture_dir", str(fixture_dir))
    st.diagnostics.setdefault("archetype_manifest", manifest.get("expected_discovery", {}))

    overall_ok = True
    any_failed = False
    for ph_idx, ph_spec in enumerate(phases):
        ph_state = st.phases[ph_idx]
        if ph_state.status == "done":
            continue
        ph_state.status = "in_progress"
        ph_state.started_at = state.now_iso()
        state.persist(st)
        state.write_state_block_console(
            st, next_action=f"run phase {ph_spec['name']!r}"
        )
        t0 = time.monotonic()
        try:
            inputs = ph_spec.get("inputs", {}) or {}
            expected = ph_spec.get("expected", {}) or {}
            observed = observe_fn(ph_spec["name"], inputs, fixture_dir, dict(st.diagnostics))
            results = assertions.evaluate_expected(expected, observed)
            passed = sum(1 for _, ok, _ in results if ok)
            total = len(results)
            failures = [msg for _, ok, msg in results if not ok]
            ph_state.detail = f"{passed}/{total} assertions"
            if failures:
                overall_ok = False
                any_failed = True
                ph_state.status = "failed"
                ph_state.error = "; ".join(failures)
            else:
                ph_state.status = "done"
        except NotImplementedError as exc:
            ph_state.status = "skipped"
            ph_state.detail = str(exc)[:120]
        except Exception as exc:
            overall_ok = False
            any_failed = True
            ph_state.status = "failed"
            ph_state.error = (
                f"{type(exc).__name__}: {exc}\n{traceback.format_exc(limit=3)}"
            )
        ph_state.elapsed_s = time.monotonic() - t0
        state.persist(st)
        state.write_state_block_console(
            st, next_action="next phase" if overall_ok else "abort"
        )
        if ph_state.status == "failed":
            break

    state.write_state_block_console(
        st, next_action="done" if overall_ok else "review failures"
    )
    # Exit code: 0 = all phases passed or skipped (no failures);
    # 1 = at least one phase failed assertions or raised;
    # (infra errors return 2 from earlier branches).
    return 0 if not any_failed else 1


def cli_main(scenario_id: str, observe_fn: ObserveFn) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", default=os.environ.get("HARNESS_RUN_ID"))
    ap.add_argument("--target", default=None)
    args = ap.parse_args()
    return run_scenario(
        scenario_id, observe_fn, run_id=args.run_id, target_override=args.target
    )
