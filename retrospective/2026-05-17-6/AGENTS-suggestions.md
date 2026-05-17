# AGENTS.md suggestions — 2026-05-17-6

These are proposed additions to the project's agents file (typically
`AGENTS.md` at the repo root). Each section contains:

1. **Proposed addition** — the exact text to paste.
2. **Why this earns its place in your agents file** — the argument for
   doing it, grounded in something that happened (or nearly happened).

Decide each on its own merits. Skip ones that don't apply to your
operating posture; copy-paste the ones that do.

---

## Suggestion 1: Re-run the FULL lint command immediately before committing

### Proposed addition

> **Re-run the full lint command immediately before committing — not
> the partial / scoped lint command you happened to run earlier.**
> Scoped commands (e.g. `ruff check test-harness/lib test-harness/tests`)
> exclude files added after the last invocation. CI runs the full
> `ruff check .`; your local pre-commit check must do the same. If you
> want a faster inner loop, scope freely while iterating, but immediately
> before `git commit` run the unscoped command.
>
> *Grounded in: PR #5 first push failed both py3.11 and py3.12 CI legs
> with 3 F401 unused imports in `test_runner_batch_job_happy_path.py`.
> The file had been added AFTER an earlier `ruff check test-harness/lib
> test-harness/tests test-harness/runners` had passed. Local re-lint
> with `ruff check .` immediately before commit would have caught it
> in 2 seconds; the actual cost was one round of CI + a follow-up
> commit + a webhook investigation.*

### Why this earns its place in your agents file

This pattern bit a session that was otherwise running cleanly. The fix
is trivial — replace whatever scoped lint command you ran most recently
with the unscoped one before `git add`. The cost is two seconds of CPU.
The asymmetry is huge: you either catch the issue now or eat a 3-minute
CI cycle + a webhook + a follow-up commit. Over a session of N PRs the
N-times-3-minute drag adds up; the rule has zero ongoing cost.

The scoped lint command is fine while you're iterating on a directory.
The rule applies only at the moment of `git commit` — at that point,
you don't know what files outside your current focus might have drifted.

---

## Suggestion 2: Distinguish "tool can't do X" from "policy layer denies X"

### Proposed addition

> **When reasoning about MCP / sandbox / scope restrictions, distinguish
> "the underlying tool can't do X" from "a policy layer in this
> environment denies X". MCP servers typically take `owner` + `repo`
> as parameters and support cross-repo operation at the protocol level;
> what restricts them is usually a session-policy wrapper (Repository
> Scope in Claude Code on the Web, environment variables, OAuth scopes).
> Naming the wrong layer leads to wrong-shaped fixes — e.g., "redesign
> the test harness for single-repo operation" instead of "widen the
> session's scope policy". When in doubt, read the system prompt's
> environment block and the tool's actual parameter schema before
> generalising about what's possible.**
>
> *Grounded in: the prior retro misdiagnosed "MCP can't create labels"
> when in fact the workflow applies the label and MCP-side label
> creation is unnecessary. This session repeated the pattern: I claimed
> "MCP scope is a hard floor on what live-new-repo can do here" when
> the actual floor is the dispatcher's policy gate in the session's
> system prompt — the MCP server itself is multi-repo by design.*

### Why this earns its place in your agents file

Two retrospectives in a row caught the same mis-framing in different
guises. That's a pattern worth codifying. The cost of the rule is one
extra layer of inspection ("is this the tool or the wrapper?"); the
cost of getting it wrong is shipping designs that work around an
imaginary constraint.

In this specific repo, the distinction directly affects whether Phase 5
of `NEW-REPO-PLAN.md` requires a synthetic-only ADR or just a
broader-scope dispatcher.

---

## Suggestion 3: Reproduce CI failures in a fresh per-Python-version venv before guessing

### Proposed addition

> **When a CI check fails and you can't read the workflow logs (MCP
> restrictions, slow log endpoints, deep job histories), reproduce the
> failure locally in a fresh venv matching the CI runner's Python
> version, then run the exact failing command from the workflow YAML.
> Do not paraphrase the command; copy it verbatim. Keep the venv
> outside the repo tree (e.g. `/tmp/.venv-ci`).**
>
> *Grounded in: PR #5 CI failed on both py3.11 and py3.12 legs. With no
> workflow log access, I built a fresh py3.12 venv at `/tmp/.venv-ci`,
> installed `requirements-dev.txt`, ran the exact `ruff check .` line
> from the workflow YAML, and reproduced 3 F401 errors immediately.
> Total wall time from webhook to push: ~3 minutes.*

### Why this earns its place in your agents file

This is the difference between a 3-minute fix cycle and a guess-and-push
loop that can burn an hour. The rule scales: the same pattern works for
pytest failures, mypy failures, compile errors, package-build failures.
Marginal cost: 30 seconds to spin up the venv + the time to install
deps. Marginal benefit: real error text instead of webhook tea-leaves.

The full skill spec is at
[`./reproduce-ci-locally-spec.md`](./reproduce-ci-locally-spec.md).

---

## Suggestion 4: When a forward-looking plan doc has diverged from reality, status-banner-first reframe

### Proposed addition

> **When updating a forward-looking plan / roadmap / spec document that
> has diverged from reality, lead with a status banner + per-phase
> status table at the top. Do NOT rewrite the original plan body —
> annotate it. Add per-section status notes inline ("**Status: done**
> (PR #N, commit `<sha>`)"), preserve the original intent prose, and
> append a "What's left" section with PR-sized backlog items ordered
> by leverage. The original plan IS the historical record; the status
> annotations are the current truth.**
>
> *Grounded in: PR #6 updated `NEW-REPO-PLAN.md` from "design-stage,
> overnight, unattended" framing to "in progress, post-bootstrap"
> framing. Added a Current Status section near the top with a row per
> phase + Phase 5 breakdown table; annotated each phase section with
> a one-paragraph status note; appended a What's Left section with 11
> PR-sized items. Did not delete or rewrite the original plan body.*

### Why this earns its place in your agents file

Plan docs go stale faster than any other artifact. The temptation when
they diverge is to rewrite, which destroys the historical signal
("this is what we thought we were going to do"). The
annotate-not-rewrite pattern preserves both. Marginal cost: 5-10
minutes of editing. Marginal benefit: future readers can see both the
original intent AND the actual state without having to dig through git
history.

The status-banner-first ordering means a reader can know in 10 seconds
whether the doc is current or stale, before committing to reading more.

---

## Suggestion 5: When status-reading a project, distinguish "shipped" from "original goal achieved"

### Proposed addition

> **When summarising a project's state, distinguish "shipped" (PRs
> merged, commits landed) from "original goal achieved" (the plan's
> success criteria met). Retrospectives and PR streams tell you what
> shipped; comparing against the plan / spec tells you whether the
> goal was met. Phase-by-phase status that conflates the two — "Phase
> 5 done because PR #2 merged" — hides structural incompleteness. If
> a phase shipped with major work bypassed or degraded, mark it
> partial / structurally-bypassed and surface what's still owed.**
>
> *Grounded in: first answer to "what's next?" in this session listed
> four follow-up items and treated the project as broadly done. User
> pushed back: "Aren't we still implementing and testing this?". On
> re-read, Phase 5 of NEW-REPO-PLAN targeted "~80% scenarios green";
> actual result was 1 full / 4 partial / 13 skipped (8%). The retro
> had documented this candidly but I'd absorbed the framing not the
> state.*

### Why this earns its place in your agents file

This bit a session that started with what looked like routine
status-reading. The rule is cheap (one extra read of the original
plan's success criteria); the failure mode without it is presenting
"done" status when the underlying work is structurally incomplete,
which then has to be unwound when the user (correctly) pushes back.

The general pattern: "shipped" is a strict subset of "goal achieved".
Never report the former as the latter.
