# SPEC — test-harness (development-only)

Status: design-stage
Audience: implementers of the test harness in the new `pipeline-ai-sandbox` repo

This document specifies the **test harness skill** that lives in the
bootstrap bundle and the new `pipeline-ai-sandbox` repo. It is **not
part of the end-user distribution**. Its sole purpose is to validate
the 5 distributable skills before they ship.

## Purpose

Drive the 5 distributable skills (`batch-job`, `task-dag`,
`orchestrate-issue`, `onboarding`, `composition-guide`) against
synthetic repo archetypes — and against the new repo itself — using
real GitHub access via the running agent's MCP credentials.

The harness is **stepwise** — every test scenario can be paused,
inspected, and resumed via named keyword commands. It is **scenario-
based** — each archetype + skill combination is a discrete scenario
spec. And it is **agent-driven** — runs in a Claude Code sandbox (or
equivalent) using `mcp__github__*` tools, not a separate test account.

## Trigger conditions

The skill matches when:

- "Run the test harness scenario `<id>`"
- "Test the onboarding skill against archetype `<name>`"
- "Drive an end-to-end orchestrate-issue against the test harness"
- "/test-harness setup", "/test-harness step", "/test-harness reset"
- "Run all test harness scenarios"

## Inputs

| Field | Type | Required | Notes |
|---|---|---|---|
| `command` | enum | yes | `setup`, `step`, `inspect`, `reset`, `run-all`, `report` |
| `scenario_id` | string | for setup | e.g. `onboarding-blank-repo`, `orchestrate-multi-subagent` |
| `archetype` | string | for setup | e.g. `python-gha-with-agents-md`, `node-circleci-no-agents-md` |
| `target` | enum | no | `synthetic-fixture` (default) or `live-new-repo` |
| `phase_filter` | string | no | Run only phase(s) matching this name |

## Outputs

- `harness/runs/<run_id>/state.json` — per-scenario run state (restart-safe)
- `harness/runs/<run_id>/report.md` — final scenario report
- `harness/runs/<run_id>/diagnostics/` — captured artifacts (logs, branch SHAs, comment ids)
- Console output formatted with state blocks at every step

## Archetypes

A catalog of synthetic repo states the harness can stand up before
running a scenario. Implemented as fixture directories that the
harness copies into a temporary location and initialises as a git
repo (and, for live-target scenarios, pushes to a fresh GitHub repo
under the agent's account).

| Archetype | Description |
|---|---|
| `blank-repo` | Empty repo; no AGENTS.md, no CI, no README beyond placeholder. Tests onboarding on a clean slate. |
| `python-gha-with-agents-md` | Python project; existing AGENTS.md and CLAUDE.md; GitHub Actions workflows; pytest. The "ideal adoption target" archetype. |
| `node-circleci-no-agents-md` | Node.js project; CircleCI config; no AGENTS.md. Tests discovery of non-GHA CI. |
| `monorepo-multi-language` | Multiple sub-projects; both GHA and a `Jenkinsfile`. Tests heterogeneous CI discovery. |
| `existing-skills-conflict` | Has a `.claude/skills/batch-job/` directory with a conflicting older version. Tests conflict-resolution prompts in skill self-install. |
| `partial-protocol` | Has `.agent/config.json` but no workflows. Tests skills that detect partial install. |
| `protocol-installed-not-onboarded` | Full protocol install, but no dialog file on well-known branch. Tests the "installed but not onboarded" detection. |
| `gitlab-only` | GitLab CI config; no GitHub Actions. Tests discovery + onboarding's recognition that GHA is required. |

Archetypes live at `test-harness/archetypes/<name>/` as a snapshot
tree. Each has a `manifest.json` listing files, expected discovery
outputs, and any baseline state.

## Scenarios

A scenario is a YAML spec at `test-harness/scenarios/<id>.yml`. Each
specifies:

- `archetype` — which archetype to start from
- `skill_under_test` — which of the 5 distributable skills to drive
- `phases` — ordered list of named phases, each with:
  - `name` — e.g. `setup`, `invoke`, `verify`
  - `inputs` — what the harness passes to the skill
  - `expected` — assertions to make after the phase completes

Example (`onboarding-blank-repo.yml`):

```yaml
scenario_id: onboarding-blank-repo
archetype: blank-repo
skill_under_test: onboarding
phases:
  - name: detect
    expected:
      protocol_installed: false
      onboarding_started: false
  - name: interview
    inputs:
      scripted_answers:
        intent: "tests the onboarding skill"
        problems: "validation"
        adoption: "full"
    expected:
      dialog_file_present: true
      questions_answered: 22
  - name: recommend
    expected:
      recommendations_file_present: true
      no_agents_md_edits_proposed: true
  - name: apply
    inputs:
      approve_all: true
    expected:
      pointer_added_to_agents_md: true
      protocol_templates_installed: true
```

Scenarios live at `test-harness/scenarios/<id>.yml`.

## Stepwise commands

The harness exposes these named commands. Each is an entry point in
the skill's SKILL.md.

| Command | Effect |
|---|---|
| `setup <scenario_id>` | Materialise the archetype; initialise state; report phase 1 ready |
| `step` | Run the next phase; report state |
| `inspect` | Show current state, last phase output, next phase plan |
| `reset` | Tear down current scenario (delete fixture, archive run logs); ready for next |
| `run-all` | Run every phase sequentially; report at end |
| `report` | Print the run report to console |

Every command output includes a state block:

```
[test-harness • scenario: onboarding-blank-repo • phase 2/4 (interview)]
  Setup:    done    (archetype materialised at /tmp/harness/<run_id>/)
  Interview: ready  (22 questions queued; scripted answers loaded)
  Recommend: pending
  Apply:     pending
Next: invoke onboarding skill in interview mode with scripted answers
```

## Real-GitHub interaction model

The harness uses the running agent's own GitHub MCP credentials.
**No separate test account.** No secrets configuration. No PAT setup.

For scenarios with `target: live-new-repo`:

1. The harness creates a temporary GitHub repo under the agent's
   account (via `mcp__github__create_repository`) with a deterministic
   name like `<run_id>-<scenario_id>`. Naming is unique per run so
   parallel scenarios don't collide.
2. The archetype's files are pushed to that repo.
3. The scenario runs against the live repo.
4. After the scenario, the harness optionally deletes the repo (or
   archives it under a `harness-runs` GitHub org/user prefix for
   forensic preservation if the scenario failed).

For scenarios with `target: synthetic-fixture`:

1. The harness initialises a local-only git repo with the archetype.
2. Skills that require GitHub interaction (`mcp__github__*`) use an
   in-process mock client (the POC's `InMemoryGitHubClient` adapted
   for the new repo).

The default for skill validation is `target: live-new-repo`. Some
unit-style scenarios (e.g. testing the onboarding interview state
machine) use `synthetic-fixture` for speed.

## State and restart safety

Every scenario writes state after every phase:

```json
{
  "run_id": "20260514-051200",
  "scenario_id": "orchestrate-multi-subagent",
  "archetype": "python-gha-with-agents-md",
  "target": "live-new-repo",
  "github_repo": "jonathanmanton/20260514-051200-orchestrate-multi-subagent",
  "phases": [
    {"name": "setup", "status": "done", "elapsed": 23},
    {"name": "invoke", "status": "in_progress", "started_at": "..."},
    {"name": "verify", "status": "pending"}
  ],
  "diagnostics": {
    "issue_numbers": [1],
    "pr_numbers": [],
    "branches_created": ["agent/1-..."]
  }
}
```

If interrupted, `step` re-reads state and resumes from the
`in_progress` or first `pending` phase.

## Scenario catalog (initial)

At least one scenario per (archetype, skill) combination plus
edge-case scenarios. Initial catalog:

1. `batch-job-happy-path` — submit echo command, get terminal ack
2. `batch-job-parse-error` — submit malformed envelope, get parse_error
3. `batch-job-branch-sha-mismatch` — submit with stale SHA, get error
4. `batch-job-runner-pickup-timeout` — submit against non-existent command
5. `task-dag-claim-and-plan` — claim an issue, generate a brief
6. `task-dag-stale-takeover` — second agent takes over an abandoned issue
7. `task-dag-merge-conflicts` — merge subagent branches with conflicts
8. `orchestrate-issue-single-subagent` — minimal orchestrate-issue run
9. `orchestrate-issue-parallel-fanout` — 3 parallel subagents merge in plan order
10. `orchestrate-issue-restart-recovery` — kill mid-fanout, restart
11. `onboarding-blank-repo` — full onboarding on an empty repo
12. `onboarding-existing-agents-md` — onboarding does NOT modify AGENTS.md beyond pointer
13. `onboarding-resume-mid-interview` — partial dialog file, resume from question 14
14. `onboarding-decline` — user declines; verify no state written
15. `onboarding-revise` — re-invoke after completion to change integration choices
16. `composition-guide-render` — verify SKILL.md renders cleanly with no broken links
17. `multi-scenario-soak` — drive 3 orchestrate-issue runs in parallel against 3 issues; verify no cross-contamination
18. `protocol-installed-not-onboarded` — verify each skill detects this state correctly

The full catalog grows in the new repo as scenarios are added.

## SKILL.md frontmatter

```yaml
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
```

## Self-install logic

The harness has no in-repo template install (it lives entirely under
`test-harness/` in the new repo). On first invocation it does verify:

- The 5 distributable skills are present at `.claude/skills/<name>/`.
- The `harness/runs/` directory exists (creates if not).
- The agent's `mcp__github__get_me` returns a usable login.

If any of these fail, the harness aborts with a clear error.

## Bundled artifacts (inside the bootstrap bundle)

```
test-harness/
  SKILL.md
  SPEC.md                       (this file)
  archetypes/
    blank-repo/
      manifest.json
      <archetype files>
    python-gha-with-agents-md/
      ...
    [other archetypes]
  scenarios/
    onboarding-blank-repo.yml
    [other scenarios]
  lib/
    archetype_loader.py
    scenario_runner.py
    assertions.py
    state.py
  runs/.gitkeep
```

## Failure modes

| Failure | Detection | Handling |
|---|---|---|
| Archetype not found | Setup phase | Abort with list of valid archetypes |
| Scenario YAML invalid | Setup phase | Abort with schema error |
| GitHub repo creation rate-limited | Live target setup | Backoff + retry; abort after 3 |
| Skill under test not installed | Invoke phase | Surface as "missing dependency"; abort |
| Phase assertion fails | Verify phase | Record failure in state; continue or abort per scenario config |
| Live GitHub cleanup fails | Reset phase | Log warning, leave artifacts for forensics |

## Tests of the harness itself

- Unit test each archetype's `manifest.json` against a schema.
- Unit test the scenario YAML schema.
- Lint check: every scenario references a valid archetype + skill.

## Anti-patterns

- **Do not** ship this skill in the end-user distribution. It exists for development only.
- **Do not** run live scenarios against the user's production repo by accident — `target: live-new-repo` always creates a fresh temporary repo.
- **Do not** silently delete archetype fixtures; the harness should keep them for re-runs.
- **Do not** assume scenarios are independent unless explicitly marked — parallel-soak scenarios test for non-independence.

## Dependencies

- The 5 distributable skills (the things being tested).
- A GitHub MCP server with `create_repository` permission (the
  default for a personal-account agent).
- Python 3.12 for the harness's `lib/` helpers.
