# Spec: `ask-before-adding-cicd`

## Intent

Never add CI/CD configuration (GitHub Actions workflows, CircleCI jobs,
pre-commit hooks, lint-on-PR plumbing, test-on-PR plumbing, status
checks, branch protection rules, scheduled jobs) without **explicit
user approval first**, even when the addition seems like obvious best
practice.

CI/CD is opinionated infrastructure. What looks like a freebie ("of
course we should run lint on PRs") quickly becomes:

- Wasted compute on PRs the workflow shouldn't touch (docs, retros,
  config).
- Noise in the PR status UI when checks run but don't apply.
- Scope creep — workflows accumulate steps, each of which has to be
  reasoned about every time you touch the file.
- A new place for the user to discover surprise behaviour ("why is
  this running on a doc-only PR?").

This skill is a hard rule against adding CI/CD without asking. It is
adjacent to `tightly-scope-github-actions` (which constrains workflows
*after* you've been approved to add or modify one); this skill is the
gate before that.

## Trigger

### Direct triggers
- "Add CI for X."
- "Wire CI to run my new tests / my new lint config / my new build."
- "Add a status check that..."

### Proactive triggers
- You're about to create or modify a file under `.github/workflows/`,
  `.circleci/`, `.gitlab-ci.yml`, `.pre-commit-config.yaml`, or any
  equivalent CI/CD config file, AND the user did not explicitly
  request that addition.
- You just added a test suite, a lint config, or a build script and
  are tempted to wire CI to run it. **Stop and ask first.**
- You're following a tutorial / cargo-cult pattern that assumes
  "always wire CI" — recognise the cargo-cult and ask.
- You're about to add a step to an existing workflow that wasn't
  explicitly requested.

### Negative triggers
- The user explicitly asked for CI wiring with specific scope ("add a
  CI job that runs `pytest tests/`"). Then it's requested work; no
  meta-ask needed.
- You're *removing* CI/CD (deletions don't need this gate — they need
  the `tightly-scope` skill applied to the survivors).
- You're modifying a workflow file the user just asked you to edit
  in a specific way.

## Inputs

- The proposed CI/CD change (workflow YAML, hook config, etc.).
- The user's recent explicit asks — was CI wiring part of them?
- The repo's existing CI/CD inventory (so the ask can include "you
  already have X, this would add Y on top").

## Outputs

- A user-directed question that:
  1. Names exactly what would be added (file path + trigger + steps).
  2. Surfaces what it costs (compute, status-check noise, blast
     radius).
  3. Explicitly offers "or do nothing".
- If approved: minimal, tightly-scoped CI/CD addition (apply
  `tightly-scope-github-actions`).
- If declined: stop. Don't ask again next turn; don't add a "softer"
  variant unprompted.

## Workflow

1. **Detect** that you're about to add or extend CI/CD.
2. **Inventory** what already exists. Read all
   `.github/workflows/*.yml`. Note triggers and scope.
3. **Articulate** what you'd add: file path, `on:` triggers,
   per-step coverage. One paragraph maximum.
4. **Articulate** the cost: when it'll run, how often, what compute
   pattern, what shows up in the PR status UI.
5. **Ask the user.** Format: "I'd add `<path>` triggered on `<event>`
   running `<steps>`. It would fire on roughly `<rate>`. Want me to
   add it, or skip?"
6. **Wait for approval.** Don't assume silence is consent. Don't
   bundle the addition with other work and hope it slips through.
7. **If approved**: apply `tightly-scope-github-actions` (the
   companion skill) when writing it.
8. **If declined**: do not retry. Do not propose a "lighter" variant
   later in the same session unless the user reopens the topic.

## Concrete examples

### Example 1 — "wire pytest into CI" — the violation that triggered this skill

**Setting**: PR #5 of `lago-morph/pipeline-ai-sandbox` added 144 unit
tests in `test-harness/tests/`. The user had asked for "lots of unit
tests if that makes sense" — tests, not CI wiring.

**What I did (wrong)**: appended a "Unit tests" step to
`test-harness-ci.yml` so CI would run `pytest test-harness/tests -ra -q`
on every PR. I treated "write tests" and "wire CI to run them" as one
task.

**What I should have done**: write the tests. Then ask: "I'd add a
pytest step to `test-harness-ci.yml` that runs on every PR — about a
30-second job per PR. Or I can leave that out and you wire CI on your
schedule. Which?"

**Cost of the violation**: PR #7 (a doc-only retro PR) ran pytest +
ruff + py_compile + YAML parse + JSON parse + SKILL.md frontmatter +
scenario cross-reference for zero benefit. The user noticed, pushed
back twice, and PR #8 had to delete the whole file.

### Example 2 — declining the cargo cult

**Setting**: A user asks you to add a Python script that fetches data
from an API.

**Wrong**: "I'll add the script + a pre-commit hook that runs ruff +
mypy + a GitHub Action that lints on PR + a daily cron that re-runs
the fetch."

**Right**: write the script. Then ask only what's relevant: "The
script lives at `scripts/fetch.py`. Want me to wire any CI around it
(lint, scheduled re-runs), or just leave it as a script?"

If the user says "just leave it", that's the end. Don't add a hook
later under "while I'm here I noticed...".

### Example 3 — modifying an existing workflow

**Setting**: User asks you to fix a flake in an existing pytest job.

**In scope**: the fix to the test or the job step that was flaking.

**Out of scope unless asked**: adding new steps ("while I'm here I'll
also add a coverage report step"); changing the trigger ("I'll change
this from `push` to also include `pull_request`"); adding a matrix
("I'll parameterise over Python versions"). Each of those needs its
own ask.

## Anti-patterns

- **Adding CI silently as part of "wiring up" a feature.** "I added
  the test; the CI step that runs it is implied." It isn't. Ask.
- **Bundling CI changes inside a PR whose stated purpose is
  something else.** The user reviews the PR for the stated change;
  CI plumbing slips through and lives forever.
- **Cargo-culting from tutorials / project templates.** Many template
  repos add CI by default. This project may not want CI by default.
  Default is "ask".
- **Proposing CI as a follow-up "if requested"** ("I left the CI
  wiring out — let me know if you want it"). That's still adding
  context the user has to spend attention on. The right move is
  "should I wire CI for this?" before doing the work — once, up
  front, not as a soft-pitch dangling at the end.
- **Adding `paths-ignore` or `paths` filters to fix overreach** when
  the workflow shouldn't exist at all. Scope is a separate skill;
  this one says "first ask if it should exist".
- **Asking too late.** "I added CI for this; you can revert if you
  don't want it." The cost of revert is non-zero (read PR, decide,
  click revert) and the user shouldn't have to spend it.

## Acceptance criteria

1. Zero CI/CD config added or modified without an explicit user ask
   that named the addition.
2. Every CI/CD ask names: file path, trigger, steps, expected fire
   rate.
3. Every CI/CD ask offers a "no" / "skip" path explicitly.
4. Declined asks are not retried in the same session.
5. CI/CD changes that are approved go through the
   `tightly-scope-github-actions` skill on the way in.

## Files this skill creates / modifies

This skill is a behavioural gate; it doesn't directly create files.

- **Prevents creating**: any file under `.github/workflows/`,
  `.circleci/`, `.gitlab-ci.yml`, `.pre-commit-config.yaml`,
  `.husky/`, `lefthook.yml`, or equivalent — unless the user has
  explicitly asked for that exact addition.
- **Prevents modifying**: existing files under those paths beyond
  what was explicitly requested.
