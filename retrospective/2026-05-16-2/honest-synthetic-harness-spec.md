# Spec: `honest-synthetic-harness`

## Intent

Test harnesses run in environments more or less rich than the system under test was designed for. A scenario specified to run against a live GitHub repo can't always do so — the credentials might be scoped to a single repo, the rate limit might be exhausted, the network might be air-gapped. The two common reactions both lie:

1. **Skip the scenario silently.** No signal at all. Future runs don't know whether the scenario was run or not.
2. **Mark the scenario "pass" with a mock.** Looks green, but the test didn't exercise what the scenario claimed to.

This skill encodes the honest third option: a test runner that classifies each assertion as "answerable from the synthetic fixture" or "requires live execution", reports a tri-state per phase (`done` / `skipped` / `failed`), and never confuses the two failure modes.

In the `pipeline-ai-sandbox` run, 18 scenarios were authored for `target: live-new-repo`. The dispatcher's MCP scope could not create the required temporary GitHub repos. The runner detected the constraint, recorded `degraded_reason` in `state.diagnostics`, ran what it could synthetically, and marked the rest `skipped`. Final report: 1 full-pass, 4 partial-pass, 13 fully-skipped, **0 failures**. Zero false positives, zero false negatives.

## Trigger

**Direct triggers:**
- "Write a test harness for scenarios that may or may not have live infrastructure."
- "How do I distinguish 'test couldn't run' from 'test ran and failed'?"
- "Our tests pass locally but fail in CI because the live API isn't there."
- "Set up degraded-mode reporting."

**Proactive triggers:**
- A test/runner detects an environment mismatch (missing credential, missing scope, missing service) at startup.
- A YAML/JSON test spec references "live" features but is being run synthetically.
- A test report shows lots of failures that turn out to be infrastructure, not regression.

**Negative triggers:**
- Pure unit tests with no external dependency — no degraded mode possible, this skill doesn't apply.
- One-off ad-hoc scripts — overkill.

## Inputs

- Test spec files (YAML, JSON, or code) defining each scenario's assertions.
- A "synthetic catalogue" — the set of assertion keys answerable from the synthetic fixture (no live infra needed).
- An archetype / fixture loader that materialises starting state.
- An environment-capability probe (e.g., `mcp__github__get_me` succeeds, network reachable, credential present).

## Outputs

- Per-scenario `state.json` with `phases[].status ∈ {pending, in_progress, done, skipped, failed}`.
- A `diagnostics` dict including `degraded_reason` when fall-back was triggered.
- An aggregated report distinguishing the four outcomes:
  - **full_pass**: every phase `done`, no skips, no failures.
  - **partial_pass**: some phases `done`, others `skipped`, no failures.
  - **fully_skipped**: every phase `skipped` (nothing was actually exercised).
  - **failed**: at least one phase `failed`.
- Exit code: 0 if no `failed`; 1 if any `failed`; 2 if infrastructure error (archetype not found, spec parse error). Skipped does **not** trigger a non-zero exit.

## Workflow

1. **Define the synthetic catalogue explicitly.** A module (call it `synthetic_observe`) exports `SYNTHETIC_CATALOGUE: set[str]` listing the assertion keys it can answer. Keys absent from the catalogue are by definition live-only.
2. **At runner startup, probe the environment** for the target the scenario asks for. If the probe fails, record `degraded_reason` in diagnostics, downgrade `target` to `synthetic-fixture`, and continue.
3. **For each phase, compute `expected_keys = list(phase.expected.keys())`.** If any key is outside `SYNTHETIC_CATALOGUE`, raise `NotImplementedError("requires-live-skill-execution")` from the observe function. Catch that exception in the runner and mark the phase `skipped` (not `failed`).
4. **If every key is in the catalogue, compute observed values from the fixture** and run assertions. Mark `done` on all-pass, `failed` on any-mismatch.
5. **Persist state after every phase** so an interrupted run can resume.
6. **Aggregate at the end** into a tri-state-aware report.

### Code shape

```python
SYNTHETIC_CATALOGUE: set[str] = {
    "agents_md_present",
    "protocol_installed",
    # ... explicit list
}

def observe(phase_name, inputs, fixture, diagnostics, expected_keys):
    observed = _observe_synthetic(fixture)
    unknown = set(expected_keys) - SYNTHETIC_CATALOGUE
    if unknown:
        raise NotImplementedError(
            f"requires-live-skill-execution (phase={phase_name!r}, non-synthetic-keys={sorted(unknown)})"
        )
    return observed

# In the runner phase loop:
try:
    observed = observe(...)
    results = evaluate_expected(expected, observed)
    if all(ok for _, ok, _ in results):
        phase.status = "done"
    else:
        phase.status = "failed"   # <-- real failure, not synthetic-vs-live mismatch
        any_failed = True
except NotImplementedError as exc:
    phase.status = "skipped"      # <-- honest about what wasn't exercised
    phase.detail = str(exc)
```

The key invariant: a phase becomes `failed` **only when a key it could have answered came back wrong**, never when the key was outside the catalogue.

## Concrete examples

### Example 1 — `pipeline-ai-sandbox` (this session)

Scenario `batch-job-happy-path` declares:
```yaml
phases:
  - name: setup
    expected:
      repo_created: true
      issue_number_present: true
```

`repo_created` and `issue_number_present` are NOT in `SYNTHETIC_CATALOGUE` — neither is observable without a live GitHub repo. The runner raises `NotImplementedError("requires-live-skill-execution (phase='setup', non-synthetic-keys=['issue_number_present', 'repo_created'])")`. Phase status: `skipped`. Detail captured for the report.

Compare with scenario `composition-guide-render`:
```yaml
phases:
  - name: render
    expected:
      frontmatter_parses: true
      markdown_renders: true
```

Both keys ARE in the catalogue (the runner reads the SKILL.md and checks frontmatter / markdown structure). Both pass. Phase status: `done`. The scenario reports `full_pass`.

### Example 2 — service-integration test in a CI without the service

Context: a Python test suite has integration tests against a Postgres instance. The CI for the open-source repo doesn't have Postgres provisioned. Today the test file is `@pytest.mark.skip` if `os.getenv("DATABASE_URL") is None`. The honest-synthetic-harness pattern would instead:

```python
SYNTHETIC_CATALOGUE = {
    "schema_parses",
    "migration_script_runs_against_sqlite",
    # ... assertions answerable from a local SQLite fixture
}

def probe():
    if "DATABASE_URL" in os.environ:
        return "live-postgres"
    return "synthetic-sqlite"

# Each test annotates its assertion keys; the harness compares to the
# catalogue and marks the test "skipped (live-postgres-required)" or runs it.
```

The CI report distinguishes "skipped because no postgres" from "failed". A regression in `schema_parses` (which runs synthetically) is caught even when postgres isn't there.

## Anti-patterns

- **One catalogue per scenario.** Centralise. The catalogue is a single source-of-truth for what's synthetically-observable across the repo.
- **`skipped` exits non-zero.** Skipped-only runs are not failures. Reserve non-zero for actual `failed` (and infrastructure errors).
- **Re-running with `target=synthetic-fixture` silently because live failed.** The downgrade must be recorded as `degraded_reason` in diagnostics.
- **Letting the synthetic observation lie.** A fixture that returns `repo_created=False` when the spec says `repo_created: true` is a false negative — synthetic-observe should raise `NotImplementedError`, not produce a falsy answer. Keys outside the catalogue are off-limits.
- **Aggregating `skipped` and `done` into one "ok" bucket.** Reviewers can't tell if anything was actually exercised. Always split.

## Acceptance criteria

1. The `SYNTHETIC_CATALOGUE` is a single, version-controlled, importable set; no scattered ad-hoc lists.
2. The runner's tri-state outcome (`done` / `skipped` / `failed`) is reflected in `state.json`, in the aggregated report, and in the runner's exit code semantics.
3. Running a scenario whose every expected key is in the catalogue against a live target produces the same `done` count as running it synthetic. (Live mode adds keys; it doesn't change synthetic-mode results.)
4. A scenario that requires live execution and is run synthetically reports `fully_skipped`, exit 0, with `requires-live-skill-execution` in diagnostics.
5. A scenario whose synthetic observation contradicts the spec produces `failed`, exit 1 — even when only one of N phases mismatches.
6. The report shows totals: full_pass / partial_pass / fully_skipped / failed counts.

## Files this skill creates / modifies

- A `synthetic_observe.py` (or equivalent) module exporting `SYNTHETIC_CATALOGUE: set[str]` and an observe function.
- A `scenario_runner.py` (or equivalent) with a tri-state phase loop and `NotImplementedError`-as-skip semantics.
- A `state.py` (or equivalent) that persists `status ∈ {pending, in_progress, done, skipped, failed}`.
- An aggregator (`analyze_results.py` or similar) that emits a tri-state report.
- Documentation in `AGENTS.md` / `test-harness/SKILL.md` describing the contract.
