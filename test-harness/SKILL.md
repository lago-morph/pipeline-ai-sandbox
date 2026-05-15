---
name: test-harness
description: |
  DEVELOPMENT-ONLY skill for validating the agent-job protocol skills
  against synthetic repo archetypes and live GitHub repos. Stepwise:
  setup/step/inspect/reset/run-all. Uses the running agent's GitHub
  MCP credentials. NOT for end-user distribution. Use in the
  pipeline-ai-sandbox maintenance repo only.
allowed-tools:
  - Bash
  - Read
  - Write
  - Edit
  - Agent
  - mcp__github__*
---

# test-harness — development-only skill

> **WARNING — DEVELOPMENT-ONLY**
>
> This skill is bundled with the bootstrap so it lives in the new
> `pipeline-ai-sandbox` repo from day one, but it is **never** included
> in the end-user distribution build. Its sole purpose is to validate
> the 5 distributable skills (`batch-job`, `task-dag`,
> `orchestrate-issue`, `onboarding`, `composition-guide`) before they
> ship.

## Triggers

The skill matches when a maintainer in the `pipeline-ai-sandbox` repo
asks:

- "Run the test harness scenario `<id>`"
- "Test the onboarding skill against archetype `<name>`"
- "Drive an end-to-end orchestrate-issue against the test harness"
- "/test-harness setup", "/test-harness step", "/test-harness inspect",
  "/test-harness reset", "/test-harness run-all", "/test-harness report"
- "Run all test harness scenarios"

It does **not** match end-user invocations of the 5 distributable
skills.

## Inputs

| Field | Type | Required | Notes |
|---|---|---|---|
| `command` | enum | yes | One of `setup`, `step`, `inspect`, `reset`, `run-all`, `report` |
| `scenario_id` | string | for `setup` | e.g. `onboarding-blank-repo` |
| `archetype` | string | for `setup` | Override the scenario's archetype; rare |
| `target` | enum | no | `synthetic-fixture` (default for unit scenarios) or `live-new-repo` |
| `phase_filter` | string | no | Restrict to phases whose name matches this token |
| `run_id` | string | no | Continue a prior run instead of creating a fresh one |

The `command` enum is the primary entry point. All other inputs are
contextual to the command being invoked.

## Outputs

- `harness/runs/<run_id>/state.json` — per-scenario run state. Written
  after every phase. Restart-safe.
- `harness/runs/<run_id>/report.md` — final scenario report, generated
  by the `report` command at the end of a run.
- `harness/runs/<run_id>/diagnostics/` — captured artifacts (raw logs,
  branch SHAs, comment ids, MCP responses). One file per phase.
- Console output with a **state block** at every step (see
  [State-block formatting](#state-block-formatting) below).

The `<run_id>` is a `YYYYMMDD-HHMMSS` timestamp generated at `setup`
time, or recovered from `run_id` on subsequent commands.

## Stepwise commands

| Command | Effect |
|---|---|
| `setup <scenario_id>` | Materialise the archetype; initialise run state; report phase 1 ready |
| `step` | Run the next pending phase; persist state; emit state block |
| `inspect` | Show current state, last phase output, next phase plan |
| `reset` | Tear down the current scenario (delete synthetic fixture, archive run logs, optionally delete live GitHub repo); ready for next scenario |
| `run-all` | Iterate `step` until all phases complete or the first failure; emit per-phase state blocks throughout |
| `report` | Render `harness/runs/<run_id>/report.md` to console |

Every command writes state before returning. If interrupted, the next
command re-reads state and resumes from the first `pending` (or
`in_progress`) phase.

## Real-GitHub interaction model

The harness uses the **running agent's own** GitHub MCP credentials.
No separate test account. No secrets. No PAT setup. The agent must
have the `mcp__github__*` tools enabled in its sandbox.

### `target: live-new-repo`

1. Harness creates a fresh GitHub repo under the agent's account via
   `mcp__github__create_repository`. Naming is deterministic and
   unique-per-run: `<agent-login>/<run_id>-<scenario_id>`. Parallel
   scenarios never collide.
2. Archetype files are pushed via `mcp__github__push_files`.
3. Scenario phases run against the live repo.
4. On `reset`, the harness either deletes the temporary repo or
   archives it under a `harness-runs-*` prefix for forensic
   preservation (controlled by scenario config).

### `target: synthetic-fixture`

1. Harness materialises the archetype tree into a local temporary
   directory under `harness/runs/<run_id>/fixture/`.
2. Skills that would call `mcp__github__*` are run against an
   in-process mock (the POC's `InMemoryGitHubClient`, adapted).
3. No live GitHub interaction. Faster, used for unit-style scenarios.

The default is `target: live-new-repo` for end-to-end scenarios; some
lighter scenarios default to `synthetic-fixture` and declare so in
their YAML. Either default can be overridden at `setup` time.

## State and restart safety

State is written after every phase to `harness/runs/<run_id>/state.json`:

```json
{
  "run_id": "20260514-051200",
  "scenario_id": "orchestrate-issue-parallel-fanout",
  "archetype": "python-gha-with-agents-md",
  "skill_under_test": "orchestrate-issue",
  "target": "live-new-repo",
  "github_repo": "<agent-login>/20260514-051200-orchestrate-issue-parallel-fanout",
  "phases": [
    {"name": "setup",  "status": "done",        "elapsed_s": 23},
    {"name": "claim",  "status": "in_progress", "started_at": "2026-05-14T05:12:43Z"},
    {"name": "fanout", "status": "pending"},
    {"name": "merge",  "status": "pending"},
    {"name": "verify", "status": "pending"}
  ],
  "diagnostics": {
    "issue_numbers": [1],
    "pr_numbers": [],
    "branches_created": ["agent/1-..."]
  }
}
```

A subsequent `step` invocation:

1. Reads `state.json`.
2. Finds the first `in_progress` phase (resume) or `pending` phase
   (advance).
3. Runs that phase, updates its `status` to `done` or `failed`.
4. Persists state.
5. Emits a state block.

A scenario interrupted mid-phase is safe to resume because phase
implementations are idempotent: re-running a `setup` phase on an
already-materialised fixture is a no-op; re-running an `invoke` phase
asserts post-state rather than mutating again.

## State-block formatting

Every command emits a state block to the console before returning:

```
[test-harness • scenario: onboarding-blank-repo • phase 2/4 (interview)]
  setup:     done    (archetype materialised at harness/runs/20260514-055717/)
  detect:    done    (protocol_installed=false, onboarding_started=false)
  interview: ready   (22 questions queued; scripted answers loaded)
  recommend: pending
  apply:     pending
Next: invoke onboarding skill in interview mode with scripted answers
```

The block is generated by `lib/state.py :: write_state_block_console`.
Fields:

- Header: `[test-harness • scenario: <id> • phase <i>/<n> (<name>)]`
- One row per phase: `<name>: <status> (<short detail>)`
- Footer: `Next: <human description of next action>`

Statuses: `pending`, `ready`, `in_progress`, `done`, `failed`,
`skipped`.

## Self-install logic

On first invocation in a session, the skill verifies:

1. The 5 distributable skills exist at `.claude/skills/<name>/`
   (where `<name>` is one of `batch-job`, `task-dag`,
   `orchestrate-issue`, `onboarding`, `composition-guide`).
2. The `harness/runs/` directory exists; creates it if not.
3. `mcp__github__get_me` returns a usable login (only required for
   `target: live-new-repo` scenarios).

If any check fails the harness aborts with a clear error that names
the missing artifact. The harness itself **does not** install
templates into the target repo — that is the responsibility of each
distributable skill on its own first invocation.

## Failure modes

| Failure | Detection | Handling |
|---|---|---|
| Archetype not found | `setup` phase | Abort with the list of valid archetype names |
| Scenario YAML invalid | `setup` phase | Abort with a schema error citing the bad key |
| GitHub repo creation rate-limited | live-target `setup` | Backoff + retry up to 3 times; abort if still failing |
| Skill under test not installed | `invoke` phase | Surface as "missing dependency: `.claude/skills/<skill>/SKILL.md` not found"; abort |
| Phase assertion fails | any phase's verify step | Record failure in state; continue to the next phase or abort per scenario config |
| Live GitHub cleanup fails | `reset` phase | Log warning and leave artifacts on GitHub for forensics; do not raise |
| MCP token absent | first invocation | Abort with a clear "MCP github tools not available" message |

## Anti-patterns

- **Do not** ship this skill in the end-user distribution build. It
  exists only for development. The `bootstrap/distribution-exclude.txt`
  manifest in the bootstrap bundle MUST list `test-harness/` (and the
  build script enforces it).
- **Do not** run live scenarios against the user's production repo by
  accident. `target: live-new-repo` always creates a *fresh temporary*
  repo via `mcp__github__create_repository`; never reuse an existing
  repo for a scenario.
- **Do not** silently delete archetype fixtures; the harness should
  keep them for re-runs. Only `reset` removes a run's working
  directory, and only after archiving its logs.
- **Do not** assume scenarios are independent unless the scenario YAML
  explicitly marks it. The `multi-scenario-soak` scenario is a
  deliberate test for cross-contamination and must not be
  parallelised with itself.
- **Do not** call the 5 distributable skills via the Skill tool from
  inside a scenario phase. Use their Python helper entry points (the
  bundled `lib/` modules of each skill). Recursion is hard to debug.
- **Do not** edit AGENTS.md or CLAUDE.md from any harness scenario.
  Only the `onboarding` skill under test may propose pointer edits to
  those files, and only with explicit per-file approval.

## See also

- `SPEC.md` (same directory) — the long-form design spec
- `archetypes/<name>/manifest.json` — per-archetype metadata
- `scenarios/<id>.yml` — per-scenario phase specs
- `lib/archetype_loader.py`, `lib/scenario_runner.py`,
  `lib/assertions.py`, `lib/state.py` — Python helpers

---

Version: 0.1.0
Protocol-version: 1
Last-synced-from-POC: 2026-05-14
