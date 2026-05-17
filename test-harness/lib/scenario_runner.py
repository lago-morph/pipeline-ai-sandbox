"""Generic scenario runner.

Each `test-harness/runners/<scenario_id>.py` calls
:func:`run_scenario` with an ``observe_fn`` that turns a phase's
``inputs`` + the current fixture into the ``observed`` dict that
assertions are evaluated against.

The runner is **target-aware**:

- ``synthetic-fixture``: materialise the archetype into a temp dir;
  observe_fn runs against that dir; no GitHub interaction.
- ``live-new-repo``: if the runner provides a ``live_observer_factory``
  AND the environment can build a live GitHub client (token + repo),
  the live observer drives the scenario against real GitHub. If either
  is missing the run degrades to synthetic-fixture and records
  ``degraded_reason`` in state diagnostics.

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
from typing import Any, Callable, Optional

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

# A live-observer factory returns an ObserveFn given the resolved
# github_client + the run context. The runner calls this once per
# scenario invocation when target=live-new-repo and credentials are
# available.
LiveObserverFactory = Callable[..., ObserveFn]


def _default_run_id() -> str:
    return time.strftime("%Y%m%d-%H%M%S", time.gmtime())


def load_scenario(scenario_id: str) -> dict:
    p = Path("test-harness/scenarios") / f"{scenario_id}.yml"
    if not p.is_file():
        raise FileNotFoundError(f"scenario YAML not found: {p}")
    return yaml.safe_load(p.read_text())


def _maybe_build_live_observer(
    *,
    factory: Optional[LiveObserverFactory],
    env: Optional[dict[str, str]] = None,
) -> tuple[Optional[ObserveFn], Optional[str]]:
    """Try to build the live observer.

    Returns ``(observe_fn, degraded_reason)``. On success: ``(fn, None)``.
    On failure: ``(None, "<why we degraded>")``.
    """
    if factory is None:
        return None, (
            "no live_observer_factory provided by this runner; "
            "synthetic-fixture is the only available target"
        )
    try:
        # Lazy import to avoid pulling requests / .agent code unless needed.
        from github_client_factory import (
            can_make_live_client,
            make_live_client,
            resolve_repo,
        )
    except ImportError as exc:  # pragma: no cover
        return None, f"github_client_factory unavailable: {exc!r}"
    if not can_make_live_client(env):
        return None, (
            "no live GitHub credentials in environment "
            "(need GITHUB_TOKEN / GH_TOKEN and a resolvable owner/repo)"
        )
    try:
        client = make_live_client(env)
    except Exception as exc:
        return None, f"could not build live client: {exc!r}"
    repo = resolve_repo(env) or ("?", "?")
    try:
        observe_fn = factory(
            github_client=client,
            owner=repo[0],
            repo=repo[1],
        )
    except Exception as exc:
        return None, f"live observer factory failed: {exc!r}"
    return observe_fn, None


def run_scenario(
    scenario_id: str,
    observe_fn: ObserveFn,
    *,
    run_id: str | None = None,
    target_override: str | None = None,
    live_observer_factory: Optional[LiveObserverFactory] = None,
    env: Optional[dict[str, str]] = None,
) -> int:
    spec = load_scenario(scenario_id)

    archetype = spec.get("archetype")
    skill = spec.get("skill_under_test")
    requested_target = target_override or spec.get("target", "synthetic-fixture")
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
        target=requested_target,
        phase_names=phase_names,
    )

    # Materialise the archetype (always — even live runs use it for
    # phases that introspect the fixture, e.g. composition-guide).
    fixture_dir = state.HARNESS_RUNS_ROOT / run_id / scenario_id / "fixture"
    try:
        manifest = archetype_loader.materialise(archetype, fixture_dir)
    except Exception as exc:
        st.phases[0].status = "failed"
        st.phases[0].error = f"archetype_materialise: {exc}"
        state.persist(st)
        state.write_state_block_console(st, next_action="abort")
        return 2

    # Choose effective observer + target. When the runner provides a
    # live observer factory AND the env supports a live client, use it.
    # Otherwise record a degraded_reason and fall back to synthetic.
    effective_observe = observe_fn
    if requested_target == "live-new-repo":
        live_obs, degraded_reason = _maybe_build_live_observer(
            factory=live_observer_factory, env=env
        )
        if live_obs is not None:
            effective_observe = live_obs
            st.target = "live-new-repo"
        else:
            st.diagnostics["degraded_reason"] = degraded_reason
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
            observed = effective_observe(
                ph_spec["name"], inputs, fixture_dir, dict(st.diagnostics)
            )
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


def cli_main(
    scenario_id: str,
    observe_fn: ObserveFn,
    *,
    live_observer_factory: Optional[LiveObserverFactory] = None,
) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", default=os.environ.get("HARNESS_RUN_ID"))
    ap.add_argument("--target", default=None)
    args = ap.parse_args()
    return run_scenario(
        scenario_id,
        observe_fn,
        run_id=args.run_id,
        target_override=args.target,
        live_observer_factory=live_observer_factory,
    )
