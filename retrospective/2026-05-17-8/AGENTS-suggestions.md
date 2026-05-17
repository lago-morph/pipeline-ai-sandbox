# AGENTS.md suggestions — 2026-05-17-8

These are proposed additions to the project's agents file (typically
`AGENTS.md` at the repo root). Each section contains:

1. **Proposed addition** — the exact text to paste.
2. **Why this earns its place in your agents file** — the argument
   for doing it, grounded in something that happened.

Decide each on its own merits. Skip ones that don't apply to your
operating posture; copy-paste the ones that do.

---

## Suggestion 1: Never add CI/CD without explicit user approval

### Proposed addition

> **Never add CI/CD configuration without explicit user approval.**
> This includes GitHub Actions workflows, status-check steps, branch
> protection rules, pre-commit hooks, scheduled jobs, and lint /
> test plumbing that runs on PRs or pushes. Even when the addition
> seems like obvious best practice (lint-on-PR, test-on-PR, daily
> cron), do not add it as part of a different feature, do not bundle
> it into a PR whose stated purpose is something else, and do not
> propose it as a "if you want it later" follow-up. Ask up front
> with the file path, trigger, steps, and expected fire rate; offer
> an explicit "or skip" path; and wait for approval.
>
> *Grounded in: PR #5 added `pytest test-harness/tests` as a CI step
> in `test-harness-ci.yml` as part of "lots of unit tests if that
> makes sense" — tests were asked for, the CI wiring wasn't. PR #7
> (doc-only retrospective) then ran 8 static-validation steps for
> zero benefit. PR #8 deleted the entire workflow.*

### Why this earns its place in your agents file

CI/CD additions look free at the moment of addition and reveal their
real cost later — on a PR that touched none of the workflow's
target files but still pays its full compute and PR-status cost. The
user noticed (correctly) and pushed back hard ("for fucks sake don't
add stuff on your own. Suggest it first dammit"). The rule is cheap:
one extra sentence in your reply describing what you'd add. The cost
without the rule is workflows like the deleted `test-harness-ci.yml`
that run on every PR for years before someone audits them.

The rule applies to test plumbing especially. "I added the test
suite + wired CI to run it" is two decisions, not one. The first is
usually what was asked for; the second needs its own ask.

---

## Suggestion 2: Tightly scope every GitHub Actions workflow

### Proposed addition

> **Every GitHub Actions workflow must be tightly scoped on three
> dimensions: triggers, paths filter, and per-step coverage.**
> Triggers: enumerate `on:` events explicitly — never accept the
> default expansion of `pull_request:` (no filter), `push:` (any
> branch), `schedule:` (any cron). Paths filter: prefer `paths:`
> (positive list) over `paths-ignore:` so new directories default
> to "not run". Per-step coverage: every step must validate
> content that is **actually editable in this repo** — steps that
> validate bootstrap / vendored / read-only content belong in the
> upstream repo where the content is authored, not here. A cold
> re-read of the workflow YAML should find zero lines whose
> presence isn't justified.
>
> *Grounded in: `test-harness-ci.yml` ran 8 static-validation steps
> on every PR, 4 of which validated bootstrap-installed content
> this repo isn't allowed to edit (per AGENTS.md §2). The fix
> wasn't tightening — it was deletion. But the tightening audit
> is what surfaced the deletion. `contract-tests.yml` had a correct
> paths filter but the wrong purpose (validated read-only schemas);
> same outcome.*

### Why this earns its place in your agents file

This pairs with Suggestion 1. Once a workflow is approved to exist,
this rule constrains what it does. The audit pattern — "for each
step, does this validate content that's editable here?" — is the
cheapest way to find scope creep. In this repo, the audit
specifically uses `AGENTS.md` §2's "Never modify bootstrap-installed
files" rule as the editable-surface boundary; in any maintenance
repo, the equivalent boundary exists somewhere.

Marginal cost of the rule: 5 minutes per workflow at author time.
Marginal benefit: workflows that don't fire on doc-only PRs, don't
validate read-only files, don't accumulate kitchen-sink steps.

---

## Suggestion 3: PR-by-default for every change

### Proposed addition

> **Open a draft PR for every change by default. Direct-push to a
> branch without opening a PR is reserved for narrow exceptions
> that the user has explicitly approved in advance** (e.g.,
> retrospective branches the user has agreed to merge directly; PR
> noise reduction during a known-batched cleanup). When in doubt:
> open the PR. The user can merge it immediately if they don't
> need review; the cost of an extra PR is much lower than the cost
> of a change that needed review and didn't get it.
>
> *Grounded in: after PR #7 was opened, the user said "I want to
> keep everything but very specific exceptions in PRs." Immediately
> before that, I had pushed the deletion of `contract-tests.yml`
> and `test-harness-ci.yml` to a branch without opening a PR,
> offering to PR "if requested" — wrong default, the user
> escalated.*

### Why this earns its place in your agents file

The user explicitly stated this preference. The rule is mechanical:
push → PR, every time, unless the user has named the exception in
advance. Marginal cost: one extra MCP call per PR. Marginal benefit:
explicit gate per change; the user sees every change before it lands.

The wrong default is "push, then ask if they want a PR" — that
makes the user spend attention deciding for each change. PR-by-default
moves the attention spend to the rare exception case.

---

## Suggestion 4: Question bootstrap defaults before assuming they're load-bearing

### Proposed addition

> **In a bootstrapped or scaffolded repo, treat every default as
> a question, not as a fact.** Bootstrap installers are opinionated;
> their defaults may match their template's assumptions, not your
> project's actual needs. At the start of substantive work in such
> a repo, inventory the defaults (workflows, hooks, configs, default
> branch protection, default labels) and surface a list of "what is
> this for? do we want it?" questions to the user. Don't silently
> preserve scaffolding cruft because "the bootstrap put it there".
>
> *Grounded in: `contract-tests.yml` and `test-harness-ci.yml` were
> both installed by the Phase 1 bootstrap of this repo. Neither
> served the agent-job protocol the repo was built to maintain.
> Both lived for ~3 PRs before the user asked "what is this for?",
> at which point the answer was "nothing — delete it".*

### Why this earns its place in your agents file

The pattern generalises beyond CI/CD. Default labels, default
issue templates, default `.gitignore` patterns, default
`.editorconfig` rules, default GitHub repo settings (auto-delete
merged branches, allow squash-only, etc.) — bootstrap installers
set all of these opinionatedly. Most are fine; some are wrong for
the project. The rule is: at the start of substantive work, audit
once. Marginal cost: 10-15 minutes of reading. Marginal benefit:
catch the wrong defaults before they accumulate dependency.

In this repo specifically: AGENTS.md §2 already encodes the
"bootstrap-installed files are read-only" rule. That rule's
shadow side — "bootstrap-installed *behaviour* should also be
audited" — is what this suggestion makes explicit.
