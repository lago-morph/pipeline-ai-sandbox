# SPEC — onboarding skill

Status: design-stage
Audience: implementers of the skill in the new `pipeline-ai-sandbox` repo

## Purpose

Onboard a repo into the agent-job protocol via a **structured
interview**. The skill:

1. Detects whether the protocol has been adopted (`.agent/config.json` present?) and whether onboarding has been completed (dialog file present on the well-known branch?).
2. Reads the repo's existing workflow context: other skills, `AGENTS.md`/`CLAUDE.md` and any files they reference, `README*`, `SPEC*`, `PLAN*`, `HANDOFF*`, and CI/CD config (GitHub Actions, GitLab CI, CircleCI, Jenkinsfile, Bitbucket Pipelines, Azure Pipelines).
3. Asks the user whether to onboard. Accepts a decline.
4. If accepted, runs a structured interview persisted to a dialog file so a different agent session can resume.
5. Produces a **recommendations document** describing what to change in the repo.
6. Walks the user through suggested changes with before/after comparison.
7. **Offers to apply the changes itself**, respecting AGENTS.md/CLAUDE.md sacredness.
8. Reports state clearly at every step.

## Trigger conditions

The skill matches when:

- The user says: "onboard this repo to the agent-job protocol", "set up the dispatch protocol here", "run the onboarding skill", "/onboarding".
- Another protocol skill detects on its own invocation that the dialog file is missing on the well-known branch AND the user has not explicitly declined onboarding in this session. In that case the other skill offers onboarding but does not run it without user consent.

## Inputs

| Field | Type | Required | Notes |
|---|---|---|---|
| `mode` | enum | no | `"interactive"` (default) or `"resume"` |
| `branch_name` | string | no | Defaults to `agent-job-protocol/onboarding` |
| `dialog_path` | string | no | Defaults to `.agent/onboarding/dialog.md` |
| `recommendations_path` | string | no | Defaults to `.agent/onboarding/recommendations.md` |

## Outputs

- A committed dialog file at `dialog_path` on `branch_name`.
- A committed recommendations document at `recommendations_path` on `branch_name`.
- Optionally, a set of applied edits to the repo (only with explicit per-file approval).
- A final summary to the user with state, what changed, and what is next.

## Procedure

### Phase 0 — detect prior state

Check (on the current default branch):

1. `.agent/config.json` exists? → protocol is **installed**.
2. Branch `agent-job-protocol/onboarding` exists on origin? → onboarding has been **started** at some point.
3. On that branch, does the dialog file exist? → onboarding **has run**.
4. On that branch, is the recommendations doc applied to default? → onboarding is **complete**.

Report state to the user explicitly:

```
Onboarding status
  Protocol installed:    yes / no
  Onboarding started:    yes / no  (branch agent-job-protocol/onboarding)
  Dialog file present:   yes / no  (.agent/onboarding/dialog.md)
  Recommendations doc:   yes / no  (.agent/onboarding/recommendations.md)
  Recommendations applied: yes / no  (presence of pointer in target docs)
```

### Phase 1 — ask permission

"Would you like to onboard this repo to the agent-job dispatch
protocol? You can decline; the protocol skills (`batch-job`,
`task-dag`, `orchestrate-issue`) work standalone. Onboarding only
helps tune how they fit your existing workflow."

If the user declines, exit cleanly. Write a small note to the
session transcript ("onboarding declined; user can re-invoke later").

### Phase 2 — discovery scan

If the user accepts, scan the repo (read-only) for:

| Path / pattern | What we extract |
|---|---|
| `AGENTS.md`, `CLAUDE.md` | Existing conventions, referenced files |
| Any file referenced by the above | Follow one level of indirection |
| `README*` | Project purpose, audience |
| `SPEC*`, `PLAN*`, `HANDOFF*`, `ROADMAP*`, `TODO*` | Current direction |
| `.github/workflows/*.yml`, `.github/workflows/*.yaml` | Existing GHA workflows |
| `.gitlab-ci.yml`, `.gitlab/*.yml` | GitLab CI |
| `.circleci/config.yml` | CircleCI |
| `Jenkinsfile` | Jenkins |
| `bitbucket-pipelines.yml` | Bitbucket Pipelines |
| `azure-pipelines.yml`, `.azure-pipelines.yml` | Azure |
| `.claude/skills/*/SKILL.md` | Existing skills in the repo |

The skill summarises what it found in 5-15 bullet points and shows the
summary to the user before starting the interview.

### Phase 3 — interview

The interview is a tree of questions. Answers persist to the dialog
file after every answer (atomic write + commit + push to the
well-known branch). Re-invocation reads the file and resumes.

Question categories:

1. **Statement of intent**
   - What does this repo do, in one sentence?
   - Who works on it (humans only / agents only / both)?
   - What is the goal for the next 1-3 months?

2. **Problems to solve**
   - What current friction does the user want the protocol to address?
     - Subagent coordination?
     - Secrets handling?
     - Parallel work fanout?
     - Long-running jobs?
   - Free-form: any existing pain points the user wants captured?

3. **Current workflow playback**
   - "Based on what we found, your current workflow looks like
     [agent's summary, 5-10 bullets]. Is this accurate?"
   - User can correct.

4. **Integration preferences**
   - Adoption depth: full (all 3 protocol skills + onboarding pointer in AGENTS.md) / partial (batch-job only) / spec-only (no install yet)?
   - Branch naming overrides? (default `agent/<issue>-<slug>`)
   - Command registry: which of `run-tests`, `build`, `deploy-staging`, etc., do they want enabled at start?
   - Subagent fanout: enable `orchestrate-issue` for parallel work, or stick to single-subagent loops?

5. **Sensitive files**
   - "Are there docs in the repo that are copied across projects and
     should not be modified by this onboarding (besides AGENTS.md and
     CLAUDE.md which are already protected)?" Add to a do-not-edit list.

6. **Confirmation**
   - Recap of answers; user can revise any.

### Phase 4 — write recommendations

Generate `recommendations.md` on the well-known branch. Structure:

```markdown
# Onboarding recommendations — <repo>

## Statement of intent
<from interview>

## Problems addressed
<from interview>

## Files to add (no edits to existing files)
- .agent/config.json (from batch-job/task-dag template)
- .agent/scripts/... (full inventory)
- .github/workflows/lock-and-sweep.yml
- .github/workflows/batch-job-handler.yml
- .github/workflows/close-on-merge.yml
- .agent/schemas/...

## Files proposed for additive edits (pointer-only)
- AGENTS.md: add one line under a new "Agent-job protocol" section:
    > See .agent/onboarding/recommendations.md for protocol conventions.
- CLAUDE.md: identical pointer line.

## Files proposed for non-pointer edits
<list with diff preview for each; only present if discovery found
files that should be substantively modified — typically SPEC, README,
PLAN, HANDOFF. AGENTS.md/CLAUDE.md NEVER appear here.>

## Before/after workflow
- Today: <agent's summary of current dispatch model>
- After: <how the protocol changes dispatch>

## Next steps if accepted
1. The onboarding skill will apply the proposed edits with your
   explicit per-file approval.
2. Run `/orchestrate-issue` on any unclaimed agent-task issue to
   exercise the new flow.
3. Re-run `/onboarding` later to revise integration choices.
```

### Phase 5 — walkthrough and apply

For each proposed change in `recommendations.md`:

- Display before/after side-by-side. (Use diff-style text output.)
- Ask: "Apply this change? [yes/no/skip-all-AGENTS-edits/skip-all]"
- For `AGENTS.md` and `CLAUDE.md`: the **only** allowed edit is adding
  a pointer line. The skill never proposes anything else here. Even
  the pointer-line edit requires explicit per-file approval.
- For SPEC/README/PLAN/HANDOFF/ROADMAP/TODO: substantive edits require
  walkthrough + explicit approval before applying.
- Apply approved changes one file at a time. After each apply, show
  the user the resulting file's relevant section.

The skill maintains a state block visible to the user at every step:

```
Onboarding progress
  Phase: 5 of 6 (apply edits)
  Files approved + applied: 4
  Files pending decision: 2
  Files skipped: 1
  Next action: review proposed edit to .agent/onboarding/recommendations.md
```

### Phase 6 — finalise

- Merge the well-known branch's onboarding artifacts into the default
  branch via a PR (or commit directly to default if the user has
  permission and prefers).
- Post a summary message: state, what was applied, what was skipped,
  how to re-invoke onboarding, how to invoke the other skills.
- Done.

## Well-known branch and dialog file

- Branch: `agent-job-protocol/onboarding` (configurable via input).
- Dialog file: `.agent/onboarding/dialog.md` on that branch.
- Recommendations: `.agent/onboarding/recommendations.md` on that branch.
- After Phase 6, recommendations and dialog also live on default
  branch under `.agent/onboarding/`. The well-known branch is kept as
  a historical record (not deleted).

If a future re-invocation detects an old dialog file and a previous
recommendations doc on the well-known branch, Phase 0 reports
"Recommendations applied" and offers two options: "Revise the
integration" (restart from Phase 3 with prior answers as defaults) or
"Exit".

## Resume model

When re-invoked and the dialog file already exists:

```
A prior onboarding session left a dialog file with 14/22 questions
answered. Last answer: "Branch naming overrides? — keep defaults"
on 2026-05-13.

Options:
  1. Continue from the next unanswered question
  2. Restart from the beginning (prior answers used as defaults)
  3. Show me the dialog file and let me edit it manually
  4. Abandon this onboarding run

What would you like to do?
```

## Self-install logic

This skill does **not** install protocol templates itself. It is the
**guidance** layer, not the protocol layer. The skills it recommends
(`batch-job`, `task-dag`, `orchestrate-issue`) install themselves on
first invocation.

What this skill does install:

| File or path | Action if missing |
|---|---|
| `.agent/onboarding/` directory | Create on the well-known branch |
| Branch `agent-job-protocol/onboarding` | Create from default branch |

## Bundled templates

```
templates/
  dialog-template.md           # blank dialog skeleton with section headers
  recommendations-template.md  # blank recommendations skeleton
  interview-questions.yml      # canonical question tree
```

The interview-questions.yml has a stable schema so a future agent can
machine-read partial dialog files and continue.

## SKILL.md frontmatter

```yaml
---
name: onboarding
description: |
  Interview-based onboarding for adopting the agent-job dispatch
  protocol in an existing repo. Detects existing workflow conventions,
  asks the user about intent and integration preferences, produces a
  recommendations document, walks the user through proposed changes,
  and optionally applies them. Use when adopting the protocol in a
  new repo, or when revising integration choices in a repo that has
  already adopted it. Interruptible and resumable.
allowed-tools:
  - Bash
  - Read
  - Write
  - Edit
  - AskUserQuestion
  - mcp__github__*
---
```

## Failure modes

| Failure | Detection | Handling |
|---|---|---|
| User declines onboarding | Phase 1 | Exit cleanly; no state written |
| Discovery scan times out (huge repo) | Phase 2 | Show partial findings; ask user to continue |
| Network drops mid-interview | Phase 3 | Dialog file commit fails; surface to user; resume on next invocation |
| User rejects all edits | Phase 5 | Write recommendations only; report state; exit |
| Conflict applying pointer to AGENTS.md | Phase 5 | Show diff, ask user to resolve manually |

## State-clarity discipline

**Every user-facing message includes a state block.** Example:

```
[onboarding • phase 3/6 • interview]
You said the repo's intent is to be a maintenance project for the
agent-job protocol skills. Next question: Who works on it? …
```

When applying edits:

```
[onboarding • phase 5/6 • apply]
Files queue:
  [done]    1/6: .agent/config.json (created)
  [done]    2/6: .agent/scripts/common.py (created)
  [pending] 3/6: AGENTS.md (proposed: add pointer line) ← awaiting your decision
  [queued]  4/6: README.md (proposed: add 1-paragraph section)
  [queued]  5/6: CLAUDE.md (proposed: add pointer line)
  [queued]  6/6: SPEC.md (proposed: add reference to .agent/onboarding/recommendations.md)
```

## Tests

### In this POC

- Schema validity of `interview-questions.yml`.
- Dialog-file round-trip: write a fixture, parse it back, verify all answers preserved.
- Discovery scan against fixture repos: assert the skill finds the right files.
- "Recommended edits" generation against fixtures: assert AGENTS.md is never proposed for non-pointer edits.

### In the new repo

- Drive a full interview via the test harness with scripted answers; verify dialog and recommendations docs are correctly written.
- Resume test: write a partial dialog; invoke onboarding; verify it picks up at the right question.
- Apply test: accept all edits; verify pointer lines are added correctly and substantive edits respect approval boundaries.

## Anti-patterns

- **Do not** edit AGENTS.md or CLAUDE.md with anything other than a single pointer line.
- **Do not** apply edits without explicit per-file approval.
- **Do not** delete the dialog file between sessions.
- **Do not** assume the user remembers the prior session — always restate state.
- **Do not** suppress questions in the interview because they "seem obvious." User answers drive recommendations.

## Dependencies

- None at install time.
- At runtime, depends on a GitHub MCP server for branch creation.
- Recommends `batch-job`, `task-dag`, `orchestrate-issue` skills but
  does not require them to be present.
