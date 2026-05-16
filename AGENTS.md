# AGENTS.md

Guidance for any agent picking up work in `pipeline-ai-sandbox`.

## 1. Project shape

This repo is the maintenance project for 5 distributable Claude Code
skills implementing an agent-job dispatch protocol over GitHub Actions,
plus a development-only `test-harness` skill.

- High-level map: [`docs/OVERVIEW.md`](docs/OVERVIEW.md)
- Package-level contracts and cross-skill behaviour:
  [`docs/SPEC-PACKAGE.md`](docs/SPEC-PACKAGE.md)
- New-repo execution plan: [`NEW-REPO-PLAN.md`](NEW-REPO-PLAN.md)

Read those before doing anything non-trivial here.

## 2. Working conventions

- For any non-trivial change, open an `agent-task` issue first and
  invoke the `orchestrate-issue` skill to drive it from unclaimed to
  merged PR.
- For ad-hoc CI runs from inside an agent loop (tests, builds, deploys
  on a GitHub Actions runner), invoke the `batch-job` skill.
- For a multi-step issue being executed by a single agent (claim, plan
  subagents, merge sub-branches, schedule successors), use the
  `task-dag` skill.
- **Never modify bootstrap-installed files** under `.claude/skills/`,
  `docs/`, or `test-harness/{SKILL.md,SPEC.md,archetypes/,scenarios/}`
  without explicit user approval. Those are the bundle's source of
  truth and must round-trip through the POC for a re-bundle. Bugs
  found in them are fixed at the POC source and re-bundled, not
  patched in place here.
- Files OK to edit freely:
  - `README.md`, `AGENTS.md`, `CLAUDE.md`
  - `.gitignore`
  - `.github/workflows/*`
  - `.agent/*` (after self-install lays it down)
  - `test-harness/runners/*` (new directory for executable scenario
    runners; not part of the bundled source-of-truth)
  - `retrospective/*`
  - `runs/*`

## 3. Test harness conventions

The development-only `test-harness` skill drives the 5 distributable
skills against synthetic archetypes and (optionally) live GitHub.
Read [`test-harness/SKILL.md`](test-harness/SKILL.md) for the command
surface (`setup`, `step`, `inspect`, `reset`, `run-all`, `report`).

Scenarios with `target: live-new-repo` create temporary GitHub repos
under the running agent's own account via
`mcp__github__create_repository`, named `<run_id>-<scenario_id>`.
Failed scenarios deliberately leave their temporary repo intact for
forensics; the dispatcher should link them in the run report and
clean them up explicitly once diagnosed.

## 4. Branch and PR conventions

- Branch names: `claude/<short-desc>-<run_id>`
  (e.g. `claude/initial-setup-20260514-051200`).
- PRs target `main`.
- PRs are **draft by default**; mark ready for review only after the
  test harness has driven the relevant scenarios green.
- One PR per `agent-task` issue. Multiple subagent branches collapse
  into the primary agent's working branch before the PR opens.

## 5. Restart safety

Every long-running operation writes `state.json` under
`runs/<run_id>/`. Per-scenario state for harness runs lives at
`harness/runs/<run_id>/<scenario_id>/state.json`.

On restart:

1. Read `runs/<run_id>/state.json` (and any per-scenario sub-state).
2. Identify the earliest incomplete phase across the plan.
3. Resume from there. Phase implementations are idempotent — re-running
   `setup` on an already-materialised fixture is a no-op; re-running
   `invoke` asserts post-state rather than mutating again.

If state is missing or unreadable, do not invent a new run_id silently;
abort and surface the discrepancy.

## 6. Where to look for skill specs

Per-skill specs live at `docs/skills/<name>/SPEC.md`:

- [`docs/skills/batch-job/SPEC.md`](docs/skills/batch-job/SPEC.md)
- [`docs/skills/task-dag/SPEC.md`](docs/skills/task-dag/SPEC.md)
- [`docs/skills/orchestrate-issue/SPEC.md`](docs/skills/orchestrate-issue/SPEC.md)
- [`docs/skills/onboarding/SPEC.md`](docs/skills/onboarding/SPEC.md)
- [`docs/skills/composition-guide/SPEC.md`](docs/skills/composition-guide/SPEC.md)

The test-harness spec lives alongside its skill at
[`test-harness/SPEC.md`](test-harness/SPEC.md).

## 7. Anti-patterns

- Don't create real production-like GitHub repos. Live scenarios use
  the harness's temporary-repo namespace (`<run_id>-<scenario_id>`)
  under the agent's own account — nothing else.
- Don't skip the dogfood phase. Running `orchestrate-issue` against
  this repo's own `agent-task` issues is the single most valuable
  end-to-end signal we have.
- Don't modify bootstrap-installed files (see §2). Fixes flow back
  through the POC and a fresh bundle build.
- Don't call the 5 distributable skills via the Skill tool from inside
  a harness scenario phase. Use their bundled `lib/` Python entry
  points instead.
- Don't widen live-scenario fanout past the agent's GitHub rate limit
  (default wave size 4; raise only with observed slack).
