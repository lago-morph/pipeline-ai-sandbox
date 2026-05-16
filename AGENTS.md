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

## 6. GitHub MCP discipline

The protocol is designed to run under the **most restrictive** GitHub
MCP toolset. The agent side never needs label-create, repo-create,
lock/unlock, delete-comment, workflow-dispatch, or run-rerun tools.
All of those live inside GitHub Actions workflows that talk to the
REST API directly via `GITHUB_TOKEN`.

### 6.1 Confirmed-missing tools (and their workarounds)

| Agent-side operation | MCP tool? | Workaround |
|---|---|---|
| Apply a label to an issue | No | `lock-and-sweep.yml` auto-applies `agent-task` when the issue creator is trusted. |
| Lock / unlock an issue | No | `close-on-merge.yml` locks via REST after PR merge. |
| Delete a stray comment | No | `lock-and-sweep.yml` sweeps via REST on `issues.opened`. |
| Create a repo | No (and MCP scope is single-repo here) | Use existing fixture repos; `live-new-repo` scenarios are opt-in. |
| Update an existing comment | No | Post a follow-up `agent-ack` envelope comment (POC SPEC §5.2.5). |
| Read workflow run logs | No (auth-walled) | Workflows post `<!-- workflow-marker -->` comments + base64-embedded stdout tails. |
| Trigger `workflow_dispatch` | No | Push a commit that triggers `on: push`, or post a comment that triggers `on: issue_comment`. |

If you reach for an MCP tool that doesn't exist, the answer is almost
always "let a workflow do it" — not "patch around it agent-side."

### 6.2 Source `agent_login` from `mcp__github__get_me`

The MCP server authenticates as the human user (e.g. some
`somebody123`), not as a generic bot. Hardcoded placeholders like
`"my-bot"` — or any specific personal login like `"jonathanmanton"` —
will silently mismatch on every comparison and break the
identity-based code paths.

**Do**: at session start, call `mcp__github__get_me` once and use
`me.login` as the `agent_login` argument to skill scripts (`submit.py`,
`task-dag.claim`, `task-dag.heartbeat`, etc.). Do not persist it
across sessions — re-resolve each time so a different agent identity
"just works."

**Don't**: hardcode a login in `.agent/config.json`, AGENTS.md, or any
workflow YAML literal. The bundled workflows already source from
`vars.AGENT_LOGIN` (a repo-level Actions variable) with no literal
fallback; setting that variable is optional (see §6.3).

### 6.3 Workflow authorisation model

The bundled `lock-and-sweep.yml`, `batch-job-handler.yml`, and
`close-on-merge.yml` gate on **author_association** from the GitHub
event payload. The `if:` clauses always require:

- The `agent-task` label is present on the issue.
- `author_association ∈ {OWNER, MEMBER, COLLABORATOR}` — i.e. the
  comment / issue author has repo write access.

If a repo admin sets `vars.AGENT_LOGIN` to a specific account, the
workflow additionally pins to that login (single-bot mode). With
`vars.AGENT_LOGIN` **unset** (the default), any user with repo write
access can drive the protocol — useful for clones / forks where the
maintainer isn't a fixed identity.

Random commenters and junk-issue spammers can't trigger the
handler in either mode: they're filtered out by the
`author_association` check before the workflow body runs.

## 7. Where to look for skill specs

Per-skill specs live at `docs/skills/<name>/SPEC.md`:

- [`docs/skills/batch-job/SPEC.md`](docs/skills/batch-job/SPEC.md)
- [`docs/skills/task-dag/SPEC.md`](docs/skills/task-dag/SPEC.md)
- [`docs/skills/orchestrate-issue/SPEC.md`](docs/skills/orchestrate-issue/SPEC.md)
- [`docs/skills/onboarding/SPEC.md`](docs/skills/onboarding/SPEC.md)
- [`docs/skills/composition-guide/SPEC.md`](docs/skills/composition-guide/SPEC.md)

The test-harness spec lives alongside its skill at
[`test-harness/SPEC.md`](test-harness/SPEC.md).

## 8. Anti-patterns

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
