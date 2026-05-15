# Onboarding dialog

<!--
This file is the persistent record of one onboarding interview.
The onboarding skill writes here after every answered question
(atomic write + commit + push to the well-known branch
`agent-job-protocol/onboarding`). The file is the single source of
truth for resuming an interrupted onboarding session.

Schema version: 1
-->

- run_id: `<fill-in-on-create>`
- started_at: `<fill-in-on-create>`
- last_updated: `<fill-in-on-each-write>`
- protocol_version: 1
- questions_schema_version: 1

## Statement of intent

<!-- Category id: intent. One bullet per question, in stable id order. -->

- **intent.purpose** — _What does this repo do, in one sentence?_
  - Answer: `<placeholder>`
- **intent.audience** — _Who works on it (humans only / agents only / both)?_
  - Answer: `<placeholder>`
- **intent.goal** — _What is the goal for the next 1-3 months?_
  - Answer: `<placeholder>`

## Problems to solve

<!-- Category id: problems. -->

- **problems.friction** — _What current friction do you want the protocol to address?_
  - Answer: `<placeholder>`
- **problems.freeform** — _Any existing pain points to capture?_
  - Answer: `<placeholder>`

## Current workflow playback

<!-- Category id: current_workflow. The agent fills in its summary above
     the answer line; the user accepts or revises. -->

- **current_workflow.summary_accurate** — _Based on what we found, your current workflow looks like ... Is this accurate?_
  - Agent summary: `<placeholder>`
  - Answer (yes / revise + revisions): `<placeholder>`
- **current_workflow.revisions** — _If not accurate, what should we revise in the summary?_
  - Answer: `<placeholder>`

## Integration preferences

<!-- Category id: integration. -->

- **integration.depth** — _Adoption depth?_
  - Answer: `<placeholder>`
- **integration.branch_naming** — _Branch naming overrides? (default agent/<issue>-<slug>)_
  - Answer: `<placeholder>`
- **integration.commands** — _Which commands to enable at start?_
  - Answer: `<placeholder>`
- **integration.fanout** — _Enable orchestrate-issue for parallel work?_
  - Answer: `<placeholder>`

## Sensitive files

<!-- Category id: sensitive_files. -->

- **sensitive_files.list** — _Are there docs that should not be modified (besides AGENTS.md/CLAUDE.md)?_
  - Answer: `<placeholder>`
- **sensitive_files.confirm_added** — _Confirm the do-not-edit list above is complete?_
  - Answer (yes / revise + revisions): `<placeholder>`

## Confirmation

<!-- Category id: confirmation. -->

- **confirmation.recap_ok** — _Recap of answers; revise any?_
  - Answer (yes / revise + revisions): `<placeholder>`

## Status

<!-- Phase completion checklist. The onboarding skill updates this as
     phases complete. Used by Phase 0 detection on re-invocation. -->

- [ ] Phase 0 — detect prior state
- [ ] Phase 1 — permission granted
- [ ] Phase 2 — discovery scan complete
- [ ] Phase 3 — interview complete
- [ ] Phase 4 — recommendations written
- [ ] Phase 5 — walkthrough and apply complete
- [ ] Phase 6 — finalised (merged to default)
