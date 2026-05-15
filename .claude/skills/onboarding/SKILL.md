---
name: onboarding
description: |
  Interview-based onboarding for adopting the agent-job dispatch
  protocol in an existing repo. Detects existing workflow conventions,
  asks the user about intent and integration preferences, produces a
  recommendations document, walks the user through proposed changes,
  and optionally applies them. Use when adopting the protocol in a
  new repo, or when revising integration choices in a repo that has
  already adopted it. Interruptible and resumable. On first
  invocation this skill self-installs by creating the
  `.agent/onboarding/` directory and the well-known branch
  `agent-job-protocol/onboarding`; it does not install protocol
  templates (those are the other skills' jobs).
allowed-tools:
  - Bash
  - Read
  - Write
  - Edit
  - AskUserQuestion
  - mcp__github__*
---

# onboarding

Interview-driven adoption of the **agent-job dispatch protocol**.
This skill is the *guidance* layer — it neither installs nor runs the
protocol itself; it figures out how the protocol should fit into the
target repo's existing workflow and (optionally) applies the
agreed-upon edits.

## When this skill runs

This skill matches when **either** of the following is true:

- The user explicitly invokes it: "onboard this repo to the
  agent-job protocol", "set up the dispatch protocol here", "run the
  onboarding skill", or `/onboarding`.
- Another protocol skill (`batch-job`, `task-dag`, or
  `orchestrate-issue`) **AND** detects on its own invocation that
  the dialog file at `.agent/onboarding/dialog.md` is missing on the
  well-known branch `agent-job-protocol/onboarding` **AND** the user
  has not previously declined onboarding in the current session.

Under the second condition, the other skill *offers* onboarding via a
one-time message; this skill is not invoked without explicit user
consent.

## Inputs

| Field | Type | Required | Default | Notes |
|---|---|---|---|---|
| `mode` | enum | no | `"interactive"` | `"interactive"` or `"resume"` |
| `branch_name` | string | no | `agent-job-protocol/onboarding` | Well-known branch for onboarding artifacts |
| `dialog_path` | string | no | `.agent/onboarding/dialog.md` | Dialog file path on the well-known branch |
| `recommendations_path` | string | no | `.agent/onboarding/recommendations.md` | Recommendations doc path on the well-known branch |

## Outputs

- A committed **dialog file** at `dialog_path` on `branch_name`, written
  atomically after each answered question (interruptible, resumable).
- A committed **recommendations document** at `recommendations_path`
  on `branch_name`, generated from the dialog.
- Optionally, a set of **applied edits** to the repo on a separate
  branch, gated by explicit per-file user approval.
- A final **summary** to the user with onboarding state, what was
  applied, what was skipped, and how to re-invoke this skill or any
  of the protocol skills.

## Procedure

The skill runs in 7 phases (0 through 6). Every user-facing message
emitted while running carries a state block; see "State-clarity
discipline" below.

### Phase 0 — detect prior state

Check, on the current default branch:

1. Does `.agent/config.json` exist? → protocol is **installed**.
2. Does the branch `agent-job-protocol/onboarding` exist on origin? → onboarding has been **started** at some point.
3. On that branch, does `.agent/onboarding/dialog.md` exist? → onboarding **has run**.
4. On that branch, does `.agent/onboarding/recommendations.md` exist? → recommendations have been **produced**.
5. On the default branch, is a pointer line to the recommendations doc present in `AGENTS.md` or `CLAUDE.md`? → recommendations have been **applied**.

Report state to the user explicitly:

```
Onboarding status
  Protocol installed:      yes / no
  Onboarding started:      yes / no  (branch agent-job-protocol/onboarding)
  Dialog file present:     yes / no  (.agent/onboarding/dialog.md)
  Recommendations doc:     yes / no  (.agent/onboarding/recommendations.md)
  Recommendations applied: yes / no  (pointer line on default branch)
```

If a dialog file is found, jump to the resume model (see
"Resume model" below).

### Phase 1 — ask permission

Ask the user whether to onboard:

> "Would you like to onboard this repo to the agent-job dispatch
> protocol? You can decline; the protocol skills (`batch-job`,
> `task-dag`, `orchestrate-issue`) work standalone. Onboarding only
> helps tune how they fit your existing workflow."

If declined, write a session-transcript note ("onboarding declined;
user can re-invoke later") and exit cleanly. **No state is written
to the repo on decline.**

### Phase 2 — discovery scan

Scan the repo read-only for the following paths and patterns. Follow
one level of indirection for files referenced by `AGENTS.md` or
`CLAUDE.md`.

| Path / pattern | What we extract |
|---|---|
| `AGENTS.md`, `CLAUDE.md` | Existing conventions, referenced files |
| Files referenced by the above | One level of indirection |
| `README*` | Project purpose, audience |
| `SPEC*`, `PLAN*`, `HANDOFF*`, `ROADMAP*`, `TODO*` | Current direction |
| `.github/workflows/*.yml`, `*.yaml` | Existing GitHub Actions workflows |
| `.gitlab-ci.yml`, `.gitlab/*.yml` | GitLab CI |
| `.circleci/config.yml` | CircleCI |
| `Jenkinsfile` | Jenkins |
| `bitbucket-pipelines.yml` | Bitbucket Pipelines |
| `azure-pipelines.yml`, `.azure-pipelines.yml` | Azure Pipelines |
| `.claude/skills/*/SKILL.md` | Existing skills in the repo |

Summarise findings in 5-15 bullet points and show the summary to the
user before starting the interview.

### Phase 3 — interview

The interview is a tree of questions in **6 categories**, defined in
`templates/interview-questions.yml`. Answers persist to the dialog
file (atomic write + commit + push to the well-known branch) after
every answer. Re-invocation reads the dialog file and resumes from
the next unanswered question.

The six categories are:

1. **Statement of intent** — purpose, audience, near-term goal.
2. **Problems to solve** — what friction the protocol should address.
3. **Current workflow playback** — the agent's summary of the
   existing workflow, presented for the user to confirm or revise.
4. **Integration preferences** — adoption depth, branch naming,
   command registry, parallel fanout.
5. **Sensitive files** — docs other than `AGENTS.md`/`CLAUDE.md` that
   should not be modified.
6. **Confirmation** — recap of answers; user may revise any.

Do not suppress questions because they seem obvious. User answers
drive the recommendations.

### Phase 4 — write recommendations

Generate `recommendations.md` on the well-known branch from the
dialog file. Structure:

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

Use `lib/recommendations.py` (function `render_recommendations`) to
serialise the structure from the dialog data.

### Phase 5 — walkthrough and apply

For each proposed change in `recommendations.md`:

- Display a before/after diff (side-by-side or unified — agent's
  choice).
- Ask: "Apply this change? [yes / no / skip-all-AGENTS-edits / skip-all]"
- For `AGENTS.md` and `CLAUDE.md`: the **only** allowed edit is
  adding a single pointer line. The skill never proposes anything
  else here. Even the pointer-line edit requires explicit per-file
  approval.
- For `SPEC*`/`README*`/`PLAN*`/`HANDOFF*`/`ROADMAP*`/`TODO*`:
  substantive edits require walkthrough plus explicit approval.
- Apply approved changes one file at a time. After each apply, show
  the resulting file's relevant section.

Maintain a visible state block at every step (see "State-clarity
discipline" below).

### Phase 6 — finalise

- Merge the well-known branch's onboarding artifacts into the
  default branch via a PR (or commit directly if the user prefers
  and has permission).
- Post a final summary message: onboarding state, what was applied,
  what was skipped, how to re-invoke onboarding, and how to invoke
  each of the protocol skills.
- Done.

## Interview question categories

The canonical question tree lives in
`templates/interview-questions.yml` (machine-readable schema). The
six categories mirror Phase 3:

1. **Statement of intent** (`intent`) — purpose, audience, goal.
2. **Problems to solve** (`problems`) — friction inventory plus
   freeform pain points.
3. **Current workflow playback** (`current_workflow`) — playback
   accuracy check.
4. **Integration preferences** (`integration`) — depth, branch
   naming, commands, fanout.
5. **Sensitive files** (`sensitive_files`) — do-not-edit list.
6. **Confirmation** (`confirmation`) — final recap.

Question IDs are stable across versions so partial dialog files
remain resumable after schema additions. Adding a new question to
a category is backward-compatible; renaming an existing question ID
is a breaking change and requires bumping the YAML's `version` field.

## Well-known branch and dialog file conventions

- **Branch.** `agent-job-protocol/onboarding`. Created from the
  default branch if missing. Never deleted.
- **Dialog file.** `.agent/onboarding/dialog.md` on that branch.
- **Recommendations file.** `.agent/onboarding/recommendations.md`
  on that branch.

After Phase 6, the dialog file and recommendations file also exist
on the default branch under `.agent/onboarding/`. The well-known
branch is kept as a historical record (not deleted) so future
re-invocations can find the prior dialog and offer to revise.

## Resume model

When this skill is re-invoked and a dialog file already exists, it
presents the resume menu:

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

The dialog file is the single source of truth for resumption state.
`lib/dialog.py` parses it back into structured Q/A pairs.

## Self-install logic

This skill is the **guidance** layer, not the protocol layer. It
**does not install protocol templates** — the protocol skills
(`batch-job`, `task-dag`, `orchestrate-issue`) install themselves on
first invocation.

What this skill installs:

| Target | Action if missing |
|---|---|
| `.agent/onboarding/` directory (on the well-known branch) | Create |
| Branch `agent-job-protocol/onboarding` | Create from default branch |

That is the entire self-install footprint. No workflow YAMLs, no
`.agent/config.json`, no scripts. The protocol skills handle their
own templates.

## State-clarity discipline

**Every user-facing message includes a state block.** This is
non-negotiable. The user must never have to ask "where are we?"

Example during the interview:

```
[onboarding • phase 3/6 • interview]
You said the repo's intent is to be a maintenance project for the
agent-job protocol skills. Next question: Who works on it (humans
only / agents only / both)?
```

Example during the apply phase:

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

The skill always restates the current phase, what just happened, and
what is happening next — even when the user is a returning operator
on a session-resumed run.

## Failure modes

| Failure | Detection | Handling |
|---|---|---|
| User declines onboarding | Phase 1 | Exit cleanly; no state written |
| Discovery scan times out (very large repo) | Phase 2 | Show partial findings; ask user to continue |
| Network drops mid-interview | Phase 3 | Dialog file commit fails; surface to user; resume on next invocation |
| User rejects all edits | Phase 5 | Write recommendations only; report state; exit |
| Conflict applying pointer to `AGENTS.md` | Phase 5 | Show diff; ask user to resolve manually |
| Stale dialog from a prior protocol version | Phase 0 | Offer "revise integration" with prior answers as defaults |

## Anti-patterns

- **Do not** edit `AGENTS.md` or `CLAUDE.md` with anything other than
  a single pointer line. These files are sacred (cross-project
  conventions); the only legal additive edit is the pointer line, and
  even that requires explicit per-file approval.
- **Do not** apply edits without explicit per-file approval.
- **Do not** delete the dialog file between sessions.
- **Do not** assume the user remembers a prior session — always
  restate the current state at the top of every message.
- **Do not** suppress questions in the interview because they "seem
  obvious." User answers drive recommendations.
- **Do not** install protocol templates from within this skill —
  that is the job of `batch-job`, `task-dag`, and `orchestrate-issue`.

## Python entry points

The skill's runtime logic lives in `lib/`:

| Module | Purpose |
|---|---|
| `lib/detect.py` | `detect_state(repo_root)` — Phase 0 detection (5 booleans) |
| `lib/discovery.py` | `scan_repo(repo_root)` — Phase 2 discovery scan |
| `lib/dialog.py` | `load_dialog(path)` / `save_dialog(path, data)` — round-trip the dialog file |
| `lib/recommendations.py` | `render_recommendations(dialog)` — produce the recommendations.md content |

The interactive question-asking and per-file approval loops are
driven by the agent's tool calls (`AskUserQuestion`, `Read`, `Edit`,
`Write`), not by the Python helpers. The helpers are pure functions
over the dialog and discovery state.

## Templates bundled with this skill

```
templates/
  dialog-template.md           # blank dialog skeleton with section headers
  recommendations-template.md  # blank recommendations skeleton
  interview-questions.yml      # canonical question tree (stable schema)
```

The `interview-questions.yml` schema is stable so a future agent can
machine-read partial dialog files and resume them.

## Dependencies

- **Install time:** none.
- **Runtime:** a GitHub MCP server for branch and file operations.
- **Recommended (not required):** `batch-job`, `task-dag`,
  `orchestrate-issue` skills. The onboarding skill recommends but
  does not require them.

---
Version: 1.0.0
Protocol-version: 1
Last-synced-from-POC: 2026-05-14
---
