# pipeline-ai-sandbox

## What this repo is

This is the maintenance project for a set of distributable Claude Code
skills that implement an **agent-job dispatch protocol** on top of
GitHub Actions. The protocol lets AI agents claim issues, plan and
fan out subagent work, and run workflow commands (tests, builds,
deploys) inside GitHub Actions runners using only GitHub MCP transport
and the agent's own credentials. This repo is where those 5 skills are
developed, tested end-to-end, and packaged for distribution.

## The 5 skills

The skills live under `.claude/skills/<name>/` and are each
self-contained Claude Code skill packages with bundled templates and
self-install logic.

- **`batch-job`** — Submit one batch job from an active GitHub issue
  using the agent-job protocol; poll for terminal status; ack the
  result. Self-installs templates on first invocation if
  `.agent/config.json` is missing.
- **`task-dag`** — Manage one agent-task GitHub issue as a DAG node:
  claim it, plan subagents, merge subagent branches, and schedule
  follow-up issues. Self-installs the protocol's workflow + script
  templates on first invocation.
- **`orchestrate-issue`** — End-to-end primary-agent loop for one
  GitHub issue: claim, plan, fan out parallel subagents, run batch
  jobs, merge, open PR. Self-installs the agent-job protocol templates
  on first invocation.
- **`onboarding`** — Interview-based onboarding for adopting the
  agent-job dispatch protocol in an existing repo. Detects existing
  workflow conventions, asks about intent and integration preferences,
  produces a recommendations document, and optionally applies the
  proposed changes. Interruptible and resumable.
- **`composition-guide`** — Reference guide for composing `batch-job`,
  `task-dag`, and `orchestrate-issue` without using the all-in-one
  orchestrator. Documentation only — no install actions.

A separate development-only `test-harness` skill drives the 5 skills
above against synthetic repo archetypes and live GitHub repos. It is
bundled with this repo but is never shipped to end users.

## Repo layout

```
pipeline-ai-sandbox/
  .claude/skills/              # the 5 distributable skills
    batch-job/
    task-dag/
    orchestrate-issue/
    onboarding/
    composition-guide/
  test-harness/                # development-only validation skill
    SKILL.md
    SPEC.md
    archetypes/                # synthetic repo fixtures
    scenarios/                 # per-scenario YAML specs
    lib/                       # Python helpers
  docs/                        # OVERVIEW, SPEC-PACKAGE, per-skill SPECs
    OVERVIEW.md
    SPEC-PACKAGE.md
    skills/<name>/SPEC.md
    test-harness/SPEC.md
  .agent/                      # protocol config + scripts (populated
                               # when the protocol is installed in this
                               # repo)
  .github/workflows/           # CI + agent-job runner workflows
  bootstrap/                   # bootstrap recipe + install.md kept
                               # for reference
  runs/                        # state.json + diagnostics from harness
                               # and orchestration runs
```

## Running the test harness

The test harness is invoked through Claude Code. It is **stepwise** and
**scenario-based**: each scenario can be set up, stepped through,
inspected, reset, or run to completion, and state is persisted under
`harness/runs/<run_id>/state.json` after every phase so runs are
restart-safe. Live scenarios spin up a fresh temporary GitHub repo
under the agent's account using the agent's own GitHub MCP credentials
— no separate test account, no PAT setup.

To invoke, ask Claude Code:

> Run the test harness scenario `<id>`

Other entry points include `/test-harness setup`, `/test-harness step`,
`/test-harness inspect`, `/test-harness reset`, `/test-harness run-all`,
and `/test-harness report`. See `test-harness/SKILL.md` and
`test-harness/SPEC.md` for the catalog of archetypes, scenarios, and
commands.

## Developing

Project conventions and per-agent guidance live in `AGENTS.md` and
`CLAUDE.md` at the repo root. Read those before making changes. The
authoritative design documents are in `docs/`: start with
`docs/OVERVIEW.md`, then `docs/SPEC-PACKAGE.md`, then the per-skill
specs under `docs/skills/<name>/SPEC.md` and `docs/test-harness/SPEC.md`.

## Releases

A separate build workflow produces a refreshed
`pipeline-skills-package.tar.gz` containing only the 5 user-facing
skills (the `test-harness` is explicitly excluded) when a release is
cut.

## Status

**Design-stage / bootstrap-complete.** This is the maintenance project
being stood up from the bootstrap bundle. The file tree is in place;
the test harness, CI, and dogfooding scenarios are being populated by
the new-repo execution plan (`NEW-REPO-PLAN.md`).
