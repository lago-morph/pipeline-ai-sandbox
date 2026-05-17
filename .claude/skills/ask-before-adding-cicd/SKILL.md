---
name: ask-before-adding-cicd
description: Never add CI/CD configuration (GitHub Actions workflows, status-check steps, branch protection rules, pre-commit hooks, scheduled jobs, lint/test plumbing that runs on PRs or pushes) without explicit user approval — even when the addition seems like obvious best practice. Triggers proactively whenever you're about to create or modify a file under `.github/workflows/`, `.circleci/`, `.gitlab-ci.yml`, `.pre-commit-config.yaml`, `.husky/`, `lefthook.yml`, or any equivalent CI/CD config that the user did not explicitly request. Also triggers when you've just added a test suite, lint config, or build script and are tempted to wire CI for it — pause and ask first. Negative trigger: the user has explicitly named the CI addition with specific scope, in which case the work was already approved.
---

# Skill: ask-before-adding-cicd

Never add CI/CD configuration without **explicit user approval first**, even
when the addition seems like obvious best practice.

CI/CD is opinionated infrastructure. What looks like a freebie ("of course
we should run lint on PRs") quickly becomes:

- Wasted compute on PRs the workflow shouldn't touch (docs, retros, config).
- Noise in the PR status UI when checks run but don't apply.
- Scope creep — workflows accumulate steps, each of which has to be
  reasoned about every time you touch the file.
- A new place for the user to discover surprise behaviour ("why is this
  running on a doc-only PR?").

This skill is a hard rule against adding CI/CD without asking. It is
adjacent to `tightly-scope-github-actions` (which constrains workflows
*after* you've been approved to add or modify one); this skill is the gate
before that.

---

## Trigger phrases

Apply this skill when any of these is true:

### Direct triggers (user asked for CI)
- "Add CI for X."
- "Wire CI to run my new tests / my new lint / my new build."
- "Add a status check that..."

In these cases, the user has approved CI in principle; jump straight to
`tightly-scope-github-actions` for the implementation.

### Proactive triggers (you're tempted to add CI without being asked)
- You're about to create or modify a file under `.github/workflows/`,
  `.circleci/`, `.gitlab-ci.yml`, `.pre-commit-config.yaml`, `.husky/`,
  `lefthook.yml`, or any equivalent — and the user did **not** explicitly
  request that addition.
- You just added a test suite, lint config, or build script and are
  tempted to "wire CI for it". **Stop and ask first.**
- You're following a tutorial / cargo-cult pattern that assumes "always
  wire CI". Recognise the cargo-cult and ask.
- You're about to add a step to an existing workflow that wasn't
  explicitly requested.

### Negative triggers (don't apply this skill)
- The user explicitly asked for CI wiring with specific scope ("add a CI
  job that runs `pytest tests/`"). The work is already approved; just do
  it (with `tightly-scope-github-actions`).
- You're *removing* CI/CD. Deletions don't need this gate.
- You're modifying a workflow file the user just asked you to edit.

---

## Workflow

1. **Detect** that you're about to add or extend CI/CD.
2. **Inventory** existing CI/CD. Read all `.github/workflows/*.yml` (and
   equivalents). Note their triggers and scope.
3. **Articulate** what you'd add: file path, `on:` triggers, per-step
   coverage. One paragraph maximum.
4. **Articulate** the cost: when it'll run, how often, what shows up in
   the PR status UI.
5. **Ask the user.** Format:
   > "I'd add `<path>` triggered on `<event>` running `<steps>`. It would
   > fire roughly `<rate>`. Want me to add it, or skip?"
6. **Wait for approval.** Don't assume silence is consent. Don't bundle
   the addition with other work and hope it slips through.
7. **If approved**: apply `tightly-scope-github-actions` when writing it.
8. **If declined**: do not retry. Do not propose a "lighter" variant
   later in the same session unless the user reopens the topic.

---

## Concrete examples

### Example 1 — the violation that motivated this skill

**Setting**: PR #5 of `lago-morph/pipeline-ai-sandbox` added 144 unit
tests in `test-harness/tests/`. The user had asked for "lots of unit
tests if that makes sense" — tests, not CI wiring.

**Wrong (what was done)**: appended a "Unit tests" step to
`test-harness-ci.yml` so CI would run `pytest test-harness/tests -ra -q`
on every PR. Treated "write tests" and "wire CI to run them" as one task.

**Right**: write the tests. Then ask:
> "I'd add a pytest step to `test-harness-ci.yml` that runs on every PR
> — about a 30-second job per PR. Or I can leave that out and you wire
> CI on your schedule. Which?"

**Cost of the violation**: PR #7 (a doc-only retro PR) ran pytest + ruff
+ py_compile + YAML parse + JSON parse + SKILL.md frontmatter + scenario
cross-reference for zero benefit. The user noticed, pushed back twice,
and PR #8 had to delete the whole file.

### Example 2 — declining the cargo cult

**Setting**: A user asks you to add a Python script that fetches data
from an API.

**Wrong**: "I'll add the script + a pre-commit hook that runs ruff + mypy
+ a GitHub Action that lints on PR + a daily cron that re-runs the
fetch."

**Right**: write the script. Then ask only what's relevant:
> "The script lives at `scripts/fetch.py`. Want me to wire any CI around
> it (lint, scheduled re-runs), or just leave it as a script?"

If the user says "just leave it", that's the end. Don't add a hook later
under "while I'm here I noticed...".

### Example 3 — modifying an existing workflow

**Setting**: User asks you to fix a flake in an existing pytest job.

**In scope**: the fix to the test or the job step that was flaking.

**Out of scope unless asked**: adding new steps ("while I'm here I'll
also add a coverage report step"); changing the trigger ("I'll change
this from `push` to also include `pull_request`"); adding a matrix axis
("I'll parameterise over Python versions"). Each of those needs its own
ask.

---

## Anti-patterns

- **Adding CI silently as part of "wiring up" a feature.** "I added the
  test; the CI step that runs it is implied." It isn't. Ask.
- **Bundling CI changes inside a PR whose stated purpose is something
  else.** The user reviews the PR for the stated change; CI plumbing
  slips through and lives forever.
- **Cargo-culting from tutorials / project templates.** Many template
  repos add CI by default. This project may not want CI by default.
  Default is "ask".
- **Proposing CI as a follow-up "if requested"** ("I left the CI wiring
  out — let me know if you want it"). Still adds context the user has
  to spend attention on. Ask once, up front, not as a soft-pitch
  dangling at the end.
- **Adding `paths-ignore` or `paths` filters to fix overreach** when the
  workflow shouldn't exist at all. Scope is a separate skill; this one
  says "first ask if it should exist".
- **Asking too late.** "I added CI for this; you can revert if you don't
  want it." The cost of revert is non-zero (read PR, decide, click
  revert) and the user shouldn't have to spend it.

---

## Acceptance criteria

1. Zero CI/CD config added or modified without an explicit user ask that
   named the addition.
2. Every CI/CD ask names: file path, trigger, steps, expected fire rate.
3. Every CI/CD ask offers a "no" / "skip" path explicitly.
4. Declined asks are not retried in the same session.
5. CI/CD changes that are approved go through
   `tightly-scope-github-actions` on the way in.

---

## See also

- `tightly-scope-github-actions` — the companion skill that constrains
  workflows once they're approved to exist.
