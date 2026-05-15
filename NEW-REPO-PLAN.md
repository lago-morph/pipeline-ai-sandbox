# NEW-REPO-PLAN — the maintenance project for the 5 skills

Status: design-stage. Designed for **overnight, unattended, parallel
execution** by a Claude Code dispatcher in the new
`pipeline-ai-sandbox` repo.

Audience: the dispatcher agent that bootstraps and exercises the
new `pipeline-ai-sandbox` repo after the bundle has been applied.

> Read `OVERVIEW.md`, `SPEC-PACKAGE.md`, and the per-skill SPECs
> first. This plan assumes the bootstrap (`bootstrap/install.md`)
> has already laid out the file tree in the new repo.

## Prerequisites

Before this plan runs, the new repo must:

- Exist on GitHub as `<agent-account>/pipeline-ai-sandbox` (e.g. `jonathanmanton/pipeline-ai-sandbox`).
- Be checked out locally at a known path.
- Contain the bootstrap-applied file tree (see `bootstrap/install.md`).
- Have the dispatcher agent's GitHub MCP credentials available.

If any of these are unmet, the plan aborts in Phase 0.

## What this plan does

In the new `pipeline-ai-sandbox` repo, produces:

- An operational test harness with full archetype + scenario catalog
- A passing test baseline (target ~80% of scenarios green end-to-end)
- A CI setup that runs the test harness on every PR
- A README + AGENTS.md + CLAUDE.md tuned for the maintenance project
- An initial `agent-task` issue + protocol install (dogfooding)
- A retrospective document harvesting lessons from the new repo's
  first run

Does **not** modify the bootstrap-installed files except through
explicit, approved edits.

## Execution model

Same as `PLAN-PACKAGE.md`: parallel-subagent-fanout pattern,
state.json restart safety, MAX_PARALLEL=4, single-message dispatch
with `isolation: "worktree"`.

Working branch: `claude/initial-setup-<run_id>` off `main`.

## Phases

| Phase | Mode | Wall-clock estimate | Output |
|---|---|---|---|
| 0 — pre-flight | serial | ~5 min | Environment verified, state seeded |
| 1 — fanout: initial scaffolding | parallel (4 subagents) | ~30 min | CI, docs, .gitignore, project setup |
| 2 — apply protocol install | serial | ~10 min | `.agent/` + workflows live in this repo |
| 3 — fanout: archetype materialisation | parallel (8 subagents, 2 waves) | ~60 min | All 8 archetypes ready in `test-harness/archetypes/` (already there from bootstrap, this phase fleshes them out + validates) |
| 4 — fanout: scenario implementation | parallel (up to 8 waves of 4) | ~3 hours | All 18 scenarios as executable spec runners |
| 5 — fanout: drive scenarios live | parallel (waves of 4) | ~4 hours | Live execution against real GitHub; results captured |
| 6 — analyze results | serial | ~30 min | Test summary report; surface failures |
| 7 — dogfood: run orchestrate-issue end-to-end | serial | ~45 min | Open issue, drive orchestrate-issue, verify PR |
| 8 — self-retrospective | serial | ~15 min | Retrospective doc + per-skill specs if new lessons |
| 9 — commit + PR | serial | ~10 min | PR opened against main with full results |

Total: ~9-10 hours, dominated by live scenario execution. Suitable
for overnight.

## Phase 0 — pre-flight

Single-thread.

1. Verify on `main` branch initially: `git branch --show-current` returns `main`.
2. Verify working tree clean.
3. Verify the bootstrap-applied file tree is present:
   - `.claude/skills/batch-job/SKILL.md`
   - `.claude/skills/task-dag/SKILL.md`
   - `.claude/skills/orchestrate-issue/SKILL.md`
   - `.claude/skills/onboarding/SKILL.md`
   - `.claude/skills/composition-guide/SKILL.md`
   - `test-harness/SKILL.md`
   - `docs/OVERVIEW.md`
   - `docs/SPEC-PACKAGE.md`
   - `docs/skills/<name>/SPEC.md` (all 6)
   - `bootstrap/install.md` (kept for reference)
4. Verify the dispatcher's GitHub MCP credentials via `mcp__github__get_me`. Record the login as `agent_login`.
5. Verify Actions secrets / repo vars:
   - Set `vars.AGENT_LOGIN` to the agent_login from step 4 if not present (via REST through MCP if available; else surface a manual setup note).
6. Switch to a working branch: `git checkout -b claude/initial-setup-<run_id>`.
7. Create `runs/<run_id>/` directory.
8. Write initial `state.json`.

If anything fails in steps 1-5, abort.

## Phase 1 — fanout: initial scaffolding

Four subagents in parallel. Each touches disjoint paths.

| id | scope |
|---|---|
| sub-01 | Write top-level `README.md` for the maintenance project; document purpose, structure, how to run the test harness |
| sub-02 | Write `AGENTS.md` + `CLAUDE.md` for this repo (this is OK — it's a new repo, no pre-existing copies); include pointer to test harness conventions and the bundled docs |
| sub-03 | Write `.gitignore`, `pytest.ini`, `pyproject.toml` (Python dependencies); add `requirements.txt` for any dev deps |
| sub-04 | Write `.github/workflows/test-harness-ci.yml` to run the harness on every PR + a daily cron; write `.github/workflows/contract-tests.yml` if applicable |

Each subagent's brief follows the same 9-section pattern as
`PLAN-PACKAGE.md`'s Phase 1. Key constraints:

- Do not modify any bootstrap-installed file.
- Do not touch other subagents' assigned paths.
- Use `isolation: "worktree"`.
- Commit and push your sub-branch before reporting back.

Merge in plan order after all 4 complete.

## Phase 2 — apply protocol install (dogfood self-install)

Single-thread.

This phase invokes the **distributable skills' own self-install logic**
to lay out `.agent/` and `.github/workflows/` in this new repo. This is
the protocol's first dogfooding moment: the skills install themselves
in their own development repo.

Steps:

1. Read each of `batch-job`, `task-dag`, `orchestrate-issue`'s SKILL.md.
2. Execute their self-install logic (in dispatcher mode — the dispatcher
   plays the role of the invoking agent).
3. Verify `.agent/config.json`, `.agent/scripts/*`, `.agent/schemas/*`,
   `.github/workflows/{lock-and-sweep,batch-job-handler,close-on-merge}.yml`
   are in place.
4. Create the `agent-task` label on the GitHub repo (idempotent).
5. Create the `_agent_runs` orphan branch (idempotent).
6. Commit and push.

If any install step fails, the failure is interesting — it's a real
bug in the skill's install logic. Surface to the run report.

## Phase 3 — fanout: archetype materialisation

The 8 archetypes are already in the bootstrap. This phase **verifies**
each archetype is correctly materialised and adds any
archetype-specific runtime initialisation (e.g. for the `partial-protocol`
archetype, pre-populating `.agent/config.json` without workflows).

Eight subagents, two waves of 4.

| id | archetype | task |
|---|---|---|
| sub-01 | blank-repo | Verify manifest matches files; confirm `manifest.json` `expected_discovery` is correct |
| sub-02 | python-gha-with-agents-md | Same + verify pytest baseline runs in the archetype |
| sub-03 | node-circleci-no-agents-md | Same + verify `npm install` succeeds (if Node is available in sandbox) |
| sub-04 | monorepo-multi-language | Same + verify both GHA and Jenkinsfile parse |
| sub-05 | existing-skills-conflict | Same + verify the conflicting older skill file is present and differs from current bundle |
| sub-06 | partial-protocol | Same + verify `.agent/config.json` but no workflows |
| sub-07 | protocol-installed-not-onboarded | Same + verify full protocol install with no dialog file |
| sub-08 | gitlab-only | Same + verify `.gitlab-ci.yml` is present |

## Phase 4 — fanout: scenario implementation

The 18 scenarios from `test-harness/SPEC.md` need executable runners.
Each scenario's `lib/scenario_runner.py` orchestrates phases per the
YAML spec.

Dispatch in **5 waves of 4** (last wave has 2):

| Wave | Scenarios |
|---|---|
| 1 | `batch-job-happy-path`, `batch-job-parse-error`, `batch-job-branch-sha-mismatch`, `batch-job-runner-pickup-timeout` |
| 2 | `task-dag-claim-and-plan`, `task-dag-stale-takeover`, `task-dag-merge-conflicts`, `orchestrate-issue-single-subagent` |
| 3 | `orchestrate-issue-parallel-fanout`, `orchestrate-issue-restart-recovery`, `onboarding-blank-repo`, `onboarding-existing-agents-md` |
| 4 | `onboarding-resume-mid-interview`, `onboarding-decline`, `onboarding-revise`, `composition-guide-render` |
| 5 | `multi-scenario-soak`, `protocol-installed-not-onboarded` |

Each subagent's task: implement one scenario's runner. The brief
includes:

- Scenario YAML spec
- Archetype to use
- Skill under test
- Expected assertions per phase
- File path to write the runner to (`test-harness/runners/<scenario_id>.py`)
- Don't touch other scenarios' runners

Collect results between waves. If wave N produces a high failure
rate, surface to the run report before dispatching wave N+1.

## Phase 5 — fanout: drive scenarios live

For each implemented scenario, run it. The dispatcher does this in
**waves of 4** to balance throughput against the new repo's GitHub
quota (rate limit, Actions minutes).

For each wave:

1. Pick 4 scenarios ready to run (their runners are merged).
2. Dispatch 4 subagents in one message, each running one scenario.
3. Each subagent uses `target: live-new-repo` for scenarios that
   require live GitHub.
4. Each subagent creates a temporary GitHub repo per
   `test-harness/SPEC.md` (using `mcp__github__create_repository`
   under the dispatcher's GitHub identity), runs the scenario, and
   reports back results.
5. Wait for the wave to complete. Update state. Continue.

Failed scenarios:

- For `UNATTENDED=1`: leave the test repo for forensics, mark scenario failed, continue.
- Each failed scenario's temporary repo + diagnostics get linked in the run report.

## Phase 6 — analyze results

Single-thread.

1. Read every `harness/runs/<run_id>/<scenario_id>/state.json`.
2. Aggregate: total scenarios, pass count, fail count, error count.
3. For each failure, capture: scenario id, last completed phase, expected vs actual, link to the temporary GitHub repo + workflow runs.
4. Identify patterns: are failures concentrated in one skill? In one phase across scenarios? In live-GitHub flakiness?
5. Write `runs/<run_id>/test-results.md` with full summary.

## Phase 7 — dogfood: run orchestrate-issue end-to-end

Single-thread, but the orchestrate-issue invocation itself fans out
subagents internally.

This is the **dogfooding test**: use the protocol the new repo
maintains to do real work on the new repo.

1. Open a real `agent-task` issue in `pipeline-ai-sandbox`:
   - Title: "Add per-archetype README templates"
   - Body: includes `agent-meta` block; instructions say to add a 1-paragraph README to each archetype directory describing its purpose.
2. Invoke `orchestrate-issue` against that issue.
3. The skill claims the issue, plans subagents (one per archetype = 8 subagents), fans them out, merges, opens a PR.
4. The dispatcher monitors the run; if it gets stuck, intervene; otherwise wait for completion.
5. Verify the PR has 8 README files added, one per archetype.

This is the most ambitious live test. If it works, the protocol is
end-to-end validated in its own dev repo.

## Phase 8 — self-retrospective

Single-thread. Apply the `self-retrospective` skill pattern.

1. Verify UTC date via `date -u`.
2. Write `retrospective/YYYY-MM-DD-NN.md`:

```markdown
# Retrospective — new repo bootstrap run <run_id>

## Goal
Bootstrap pipeline-ai-sandbox and validate the 5 distributable skills
+ test harness end-to-end against real GitHub.

## Phases
[summary table from state.json]

## Live test results
[summary from Phase 6]

## Dogfooding result (Phase 7)
[did orchestrate-issue end-to-end succeed?]

## Bugs surfaced
[one bullet per bug; ground in concrete evidence]

## Workarounds invented
[anything where the as-designed behavior didn't work and we hand-patched]

## Patterns to harvest
[reusable lessons; if any merit a skill spec, list them]

## Specs/SPEC.md updates needed
[anything that should flow back to the SPEC]
```

3. If any new reusable lessons emerged, draft per-skill specs at
   `retrospective/<date>-<seq>/skills/<skill-name>/SPEC.md` per the
   `self-retrospective` skill output structure.

4. Draft `AGENTS-suggestions.md` with 5-15 proposed `AGENTS.md`
   additions, each with a copy-paste-ready rule and a one-line
   rationale.

## Phase 9 — commit + open PR

Single-thread.

1. Merge any remaining sub-branches into the working branch.
2. Push the working branch to origin.
3. Open a PR via `mcp__github__create_pull_request`:
   - Title: `Initial setup + first live-test sweep (<run_id>)`
   - Body: summary table from `runs/<run_id>/test-results.md`,
     dogfooding result, retrospective excerpt.
   - Target: `main`.
4. Print the PR URL.

The user reviews the PR in the morning and merges (or comments back
with adjustments).

## Restart recovery

Same model as `PLAN-PACKAGE.md`. On restart:

1. Read `runs/<run_id>/state.json`.
2. Identify the earliest incomplete phase.
3. For Phase 4 and Phase 5 (the long parallel ones), per-scenario
   sub-state lives in `harness/runs/<run_id>/<scenario_id>/state.json`.
   Resume per scenario based on its sub-state.

## Anti-patterns (this plan-specific)

- **Don't** create real GitHub repos outside the test harness's
  temporary-repo namespace. Production-like repos belong to the user.
- **Don't** run live scenarios in parallel waves bigger than the
  agent's GitHub rate limit allows. Default wave size 4 is
  conservative; raise only after observing slack.
- **Don't** leave failed scenarios' temporary repos around silently —
  link them in the run report.
- **Don't** skip the dogfood phase (Phase 7) — it's the single most
  valuable test in this plan.
- **Don't** modify any bootstrap-installed file as part of this plan
  without explicit user approval. If a bug requires a fix, the fix
  belongs in the source POC + a re-build of the bundle.

## Plan output

When the plan completes, `pipeline-ai-sandbox` contains:

```
pipeline-ai-sandbox/
  README.md                    (Phase 1)
  AGENTS.md, CLAUDE.md         (Phase 1)
  .gitignore, pytest.ini, …    (Phase 1)
  .agent/                      (Phase 2 — self-install)
  .github/workflows/           (Phase 2 + Phase 1 CI)
  .claude/skills/              (from bootstrap, unchanged)
  test-harness/
    archetypes/                (validated in Phase 3)
    scenarios/                 (unchanged)
    runners/                   (NEW — Phase 4)
    runs/<run_id>/             (Phase 5)
  retrospective/<date>/        (Phase 8)
  runs/<run_id>/
    state.json
    test-results.md
    report.md
  docs/                        (from bootstrap, unchanged)
```

And one PR opened against `main` with the run report and
retrospective.

## What happens after this plan succeeds

The new repo is the home for ongoing skill maintenance:

- New scenarios are added under `test-harness/scenarios/`.
- New archetypes for newly-observed real-world setups go under `test-harness/archetypes/`.
- Skill changes go through the protocol they implement: open an `agent-task` issue, invoke `orchestrate-issue`, review the PR.
- Periodic retrospectives harvest reusable lessons.
- When a release is ready, a separate "build distribution" workflow
  produces a refreshed `pipeline-skills-package.tar.gz` (only the
  user-facing 5 skills — not the test harness).

The POC repo (`poc-github-ai-sandbox`) is no longer modified. It
remains as a historical reference.
