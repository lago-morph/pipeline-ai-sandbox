# AGENTS.md suggestions — 2026-05-16-2

These are proposed additions to the project's agents file (typically
`AGENTS.md` at the repo root). Each section contains:

1. **Proposed addition** — the exact text to paste.
2. **Why this earns its place in your agents file** — the argument
   for doing it, grounded in something that happened (or nearly
   happened) in PR #2.

Decide each on its own merits. Skip ones that don't apply to your
operating posture; copy-paste the ones that do.

---

## Suggestion 1: Lint vendored paths via `extend-exclude`, not `continue-on-error`

### Proposed addition

> **Lint vendored paths via config-level exclusion, not via CI-level bypass.** When the repo contains vendored / bootstrap-installed code (e.g., `.claude/skills/*/templates/`, `.agent/`, `vendor/`, `third_party/`), exclude those paths from lint/format/typecheck in `pyproject.toml` (`[tool.ruff].extend-exclude`, `[tool.mypy].exclude`, etc.) or in `.eslintignore` / `.flake8`. Do **not** add `continue-on-error: true`, `--exit-zero`, or `|| true` to lint steps. CI-level bypasses make the workflow report "Success" while annotations show `exit code 1`, hiding real signal in non-vendored code.
>
> *Grounded in: PR #2 first landed with `continue-on-error: true` on the ruff step. The workflow reported "Success" while showing two red `exit code 1` annotations per matrix leg, hiding 27 ruff hits in vendored code plus 2 real hits in this repo's `test-harness/lib/`.*

### Why this earns its place in your agents file

The CI episode took the user pointing at a screenshot to surface — the MCP `get_check_runs` truthfully reported `conclusion: success` because the bypass was at the step level. The cost of the bypass: 29 silenced hits, of which 2 (`F401 unused import` in `test-harness/lib/state.py` and `synthetic_observe.py`) were real lint problems in code authored in this session. The marginal cost of the right pattern is one `extend-exclude` block in `pyproject.toml` — a 5-line addition. The asymmetry is huge: bypass-by-CI hides real signal under a green banner forever; config-level exclusion surfaces real hits at every push.

---

## Suggestion 2: Never `git clean -fdx` while you have uncommitted work

### Proposed addition

> **Never run `git clean -fdx` while the working tree has uncommitted work (staged or untracked).** `git clean -fdx` deletes untracked files from the filesystem. When combined with `git checkout --orphan` (which preserves the working tree on switch), it can silently destroy uncommitted work, and `git status` after the round-trip will report a clean tree because the tracked files are restored. For orphan-branch creation alongside an active working tree, use `git worktree add --detach <path>` and do the orphan work in the separate worktree, or `git stash --include-untracked` before cleaning. The skill's documented procedure in `.claude/skills/orchestrate-issue/SKILL.md` includes this footgun — copy carefully.
>
> *Grounded in: the `_agent_runs` orphan-branch creation in Phase 2 of run Vs1aL wiped `.agent/` and three workflow files that had been copied from the bundle but not yet staged. Caught by an explicit `ls .agent/` after the round-trip; not by `git status`.*

### Why this earns its place in your agents file

`git status` after the orphan round-trip showed a clean tree — exactly what you'd expect to see if everything worked. The actual filesystem state was the opposite. Without an explicit "did the files I copied still exist?" check, the dispatcher would have committed nothing and continued to Phase 3 silently. Recovery cost: redo the copies (~30 seconds). Detection cost without the check: arbitrary; could have shipped a PR with no `.agent/` directory. Marginal cost of the rule: choose `git worktree add --detach` over the un-safe sequence — same number of commands, zero risk of clobber.

---

## Suggestion 3: Synthetic-mode test results report tri-state, not binary

### Proposed addition

> **Test runners that may degrade from a "live" to a "synthetic" target must report a tri-state per phase: `done`, `skipped`, or `failed`. A `skipped` phase is not a failure; treat it separately in the aggregator. Skipped runs must include a diagnostic key (`degraded_reason`, `requires-live-skill-execution`, or equivalent) naming exactly what couldn't be answered.** Skip is honest; pretending a skipped test passed is a lie that scales; pretending it failed pollutes the failure signal until reviewers learn to ignore failures. The exit code reflects only `failed`, not `skipped`.
>
> *Grounded in: 13 of 18 scenarios in PR #2 ran with `target: live-new-repo` against an MCP scope that could not create test repos. All 18 exited 0; the report distinguishes 1 full-pass / 4 partial-pass / 13 fully-skipped / 0 failed.*

### Why this earns its place in your agents file

The bootstrap plan targeted "~80% of scenarios green end-to-end." The honest report shows 8% phase-pass-rate, with 0 failures and 66 skips. Without the tri-state, the same data point would have been either "92% failure rate" (alarming, would have triggered triage) or "100% pass via mock" (deceiving, would have hidden the structural gap). The tri-state cost: one extra enum value and one extra column in the report. The benefit: zero false signals.

---

## Suggestion 4: Don't trust a workflow's "Success" status when its annotations show `exit code 1`

### Proposed addition

> **When checking CI on a PR via `mcp__github__pull_request_read` (or `gh pr checks`), if the workflow reports `conclusion: success` but the run page shows step-level `Process completed with exit code 1` annotations, treat it as a real failure being masked.** Almost always the cause is `continue-on-error: true`, `--exit-zero`, or `|| true` on a step. Fix the bypass; don't fix the dashboard.
>
> *Grounded in: PR #2's first CI run was reported by both the GitHub UI and the MCP as Success, while showing two red `exit code 1` annotations. The bypass was `continue-on-error: true` on the ruff step. User pointed it out; dispatcher did not catch it automatically.*

### Why this earns its place in your agents file

This bit even a dispatcher actively monitoring the PR via webhook. The MCP API tells the literal truth (the workflow's `conclusion` field IS `success`); the UI shows the same status; the real signal is two lines further down in step annotations. A 30-second screen-glance by the user caught it; a passive subscription via `subscribe_pr_activity` would have ignored it because the conclusion was `success`. The rule prevents reflexively merging on the first "Success" notification.

---

## Suggestion 5: `gitignore` virtualenv patterns get a leading slash in fresh repos

### Proposed addition

> **In a fresh repo, tighten the upstream-template `.gitignore` patterns `lib/` and `lib64/` to `/lib/` and `/lib64/` before checking in any new code.** Without the leading slash, gitignore matches at any directory depth — meaning `test-harness/lib/`, `vendor/foo/lib/`, etc., get silently excluded. The pattern is meant to exclude top-level virtualenv directories only.
>
> *Grounded in: PR #2 Phase 4 wrote `test-harness/lib/{state,assertions,scenario_runner,...}.py`. The bootstrap-shipped `.gitignore` had a `lib/` line (no leading slash) that silently excluded the entire directory from `git status`. The 18 runners appeared in `git status`; the lib did not. Caught only by counting (3 files seen, 7 expected).*

### Why this earns its place in your agents file

The cost of catching this late is a PR that compiles in CI (because the lib was present in the dispatcher's working tree) but fails for everyone else (because git never tracked the files). Zero-cost rule: one search-and-replace at repo init. Permanent benefit.

---

## Suggestion 6: Generate N artifacts; don't handcraft them

### Proposed addition

> **When a task asks for N near-identical artifacts derived from a canonical source (N scenarios → N runners; N tables → N migrations; N endpoints → N handlers), write a generator script + commit the outputs. Don't dispatch N subagents and don't handcraft N files.** Add a top-of-file `# Generated by ./scripts/<name>.py; re-run after editing <source>` marker on each output. Add a CI guard that runs the generator and `git diff --exit-code` to keep outputs synced with the source.
>
> *Grounded in: the NEW-REPO-PLAN called for 5 waves of 4 subagents to write 18 scenario runners. PR #2 instead wrote a 30-line generator script. Result: 18 uniform runners, easier maintenance, much less wall time.*

### Why this earns its place in your agents file

The original plan would have burned ~20 subagent dispatches' worth of context budget on artifacts that diverged. The generator was 30 lines of Python and one minute of work, produced 18 byte-identical-shape runners, and is now the canonical update path. Marginal cost: 30 lines and a CI guard. Marginal benefit: no drift, no per-file lint inconsistencies, no per-file copy-paste errors.

---

## Suggestion 7: Commit dispatcher run-state; gitignore per-scenario run-state

### Proposed addition

> **Distinguish "dispatcher run-state" from "per-scenario state". Dispatcher state (e.g., `runs/<run_id>/state.json`, `report.md`, `test-results.md`) IS the audit trail — commit it. Per-scenario harness state (e.g., `harness/runs/<run_id>/<scenario_id>/state.json`) is reproducible from the runners — gitignore it via `harness/runs/*/` (with a `.gitkeep`).**
>
> *Grounded in: PR #2 found `.gitignore` shipping `test-harness/runs/*/` but not `harness/runs/*/`. The scenario runner writes to `harness/runs/` per the SPEC. Without the gitignore line, 18 per-scenario state.json files would have been committed and re-committed on every re-run.*

### Why this earns its place in your agents file

Committing per-scenario state turns every test re-run into a merge conflict. Committing zero state loses the dispatcher's audit trail. Splitting the two preserves auditability without the conflict tax.

---

## Suggestion 8: Open PRs as draft; promote when CI is genuinely green

### Proposed addition

> **All PRs open as drafts. Promote to "ready for review" only when CI is genuinely green — both the workflow conclusion AND the annotations.** A draft PR signals "work in progress; reviewers wait." A ready PR signals "this is reviewable now."
>
> *Grounded in: PR #2 was opened as draft per the existing CLAUDE.md convention; CI initially landed with a green workflow but red annotations; the convention prevented an early promotion that would have asked for review of a CI-mismatched state.*

### Why this earns its place in your agents file

The promote-when-green discipline is a 5-second tool call (`update_pull_request --draft false`) that gates wasted review attention. The marginal cost is one extra MCP call per PR; the saving is dispense-with-review when CI is actually broken.

---

## Suggestion 9: For parallel subagent fanout with disjoint paths, skip worktree isolation

### Proposed addition

> **Parallel subagents writing to disjoint paths do not need `isolation: "worktree"`. Use it when subagents might re-touch the same paths; skip it when the path partition is obviously safe. Worktree isolation costs setup + a per-agent branch + a merge step; it earns its keep only when needed.**
>
> *Grounded in: PR #2 Phase 1 ran 4 parallel subagents (README; AGENTS+CLAUDE; project tooling; CI workflows) with no worktree isolation. They shared a working tree; nothing collided; the dispatcher committed a merged result as one Phase 1 commit. Worktree isolation would have added a merge step for zero benefit.*

### Why this earns its place in your agents file

The plan said "Use `isolation: 'worktree'`" everywhere; pragmatic reading saved 4 worktree-add/remove cycles + 4 merge operations. The rule isn't "never use worktree" — it's "use it when scopes might collide, skip it when they obviously don't."

---

## Suggestion 10: Always include a "branch + push + PR" verification before declaring complete

### Proposed addition

> **Before declaring any task complete, verify every piece of work is committed AND pushed AND covered by an open or merged PR. The remote git state — not the local working tree — is the source of truth. Files written to the working tree but not pushed will be lost when the session ends.**
>
> *Grounded in: PR #2's Phase 2 self-install copies were lost mid-run by `git clean -fdx`; the only way the work survived was via the subsequent commit + push. The `always-commit-skill-to-repo` skill (added post-merge in commit `8663100`) makes this rule canonical.*

### Why this earns its place in your agents file

The orphan-branch mishap (Suggestion 2) is one example of work that nearly escaped commit + push. The general rule generalizes the lesson: the sandbox filesystem is ephemeral; only `git push origin <branch>` makes work durable. The `always-commit-skill-to-repo` skill encodes this canonically — adopting its rule into `AGENTS.md` ensures every agent in this repo respects it.
