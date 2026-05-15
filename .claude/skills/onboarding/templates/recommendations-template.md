# Onboarding recommendations — <repo>

<!--
This file is the agent's proposed integration of the agent-job
dispatch protocol into this repo. It is generated from the dialog
file by `lib/recommendations.py::render_recommendations`. The user
walks through each section in Phase 5 and approves or skips each
proposed change file-by-file.
-->

## Statement of intent

<!-- From the interview category `intent`. One paragraph + bullets. -->

- Purpose: `<from intent.purpose>`
- Audience: `<from intent.audience>`
- 1-3 month goal: `<from intent.goal>`

## Problems addressed

<!-- From the interview category `problems`. -->

- Friction addressed: `<from problems.friction>`
- Pain points captured: `<from problems.freeform>`

## Files to add (no edits to existing files)

<!-- The protocol skills install these themselves on first invocation.
     This list is informational so the user knows what the install
     footprint looks like. -->

- `.agent/config.json` (from batch-job/task-dag template)
- `.agent/scripts/...` (full inventory)
- `.github/workflows/lock-and-sweep.yml`
- `.github/workflows/batch-job-handler.yml`
- `.github/workflows/close-on-merge.yml`
- `.agent/schemas/...`

## Files proposed for additive edits (pointer-only)

<!-- The ONLY legal edit to AGENTS.md / CLAUDE.md is a single pointer
     line. Even this requires explicit per-file approval in Phase 5. -->

- `AGENTS.md`: add one line under a new "Agent-job protocol" section:
  > See `.agent/onboarding/recommendations.md` for protocol conventions.
- `CLAUDE.md`: identical pointer line.

## Files proposed for non-pointer edits

<!-- Only present if discovery found files that should be substantively
     modified — typically SPEC, README, PLAN, HANDOFF, ROADMAP, TODO.
     AGENTS.md and CLAUDE.md NEVER appear here.

     For each file: show the proposed diff and a one-sentence rationale. -->

- `<path>` — `<rationale>`
  - Diff preview: `<placeholder>`

## Before/after workflow

<!-- Two short paragraphs. -->

- **Today:** `<agent's summary of current dispatch model>`
- **After:** `<how the protocol changes dispatch>`

## Next steps if accepted

1. The onboarding skill will apply the proposed edits with your
   explicit per-file approval.
2. Run `/orchestrate-issue` on any unclaimed agent-task issue to
   exercise the new flow.
3. Re-run `/onboarding` later to revise integration choices.
