# SPEC — composition-guide skill

Status: design-stage
Audience: implementers of the skill in the new `pipeline-ai-sandbox` repo

## Purpose

Reference skill that documents how to **compose** `batch-job`,
`task-dag`, and `orchestrate-issue` for users who prefer the
primitives over the all-in-one orchestrator. The skill carries no
templates and no install logic — it is **documentation only**.

It exists because users who want fine control should be able to
discover composition patterns via the same skill-tool mechanism they
use for everything else.

## Trigger conditions

The skill matches when:

- "How do I compose the agent-job skills?"
- "Show me how to wire batch-job + task-dag manually"
- "I want to drive the primary loop myself without orchestrate-issue"
- "/composition-guide"

## Inputs

None. The skill renders documentation.

## Outputs

The skill's response is the entire content of `SKILL.md` rendered as
guidance. There are no file outputs.

## Procedure

The skill's SKILL.md contains the following sections:

1. **When to use each skill**
   - `batch-job` for one-shot job submission
   - `task-dag` for issue-as-DAG-node ownership
   - `orchestrate-issue` for end-to-end primary loop
   - `composition-guide` (this skill) for when you want the primitives

2. **Pattern: single-subagent linear loop**
   - Claim → plan → loop: edit code → commit → batch-job → ack → repeat → merge → PR
   - When to use: small tasks, single agent, no parallelism

3. **Pattern: parallel-subagent fanout**
   - Claim → plan → branch out → dispatch N subagents → each runs batch-job on its sub-branch → collect → merge in plan order → PR
   - When to use: independent subtasks, files-touched don't overlap
   - Mirrors the parallel-subagent-fanout pattern from
     `software-factory/.claude/skills/parallel-subagent-fanout/SKILL.md`,
     specialised to the agent-job protocol.

4. **Pattern: pipelined long-running work**
   - Dispatch many batch-jobs concurrently across one or more issues
   - Periodic heartbeats; reconcile results as they come in
   - When to use: e2e test suites, parallel deploys

5. **State management**
   - Where state lives (`.agent/runs/<run_id>/state.json` for fanout, agent-meta for issue state, comment envelopes for job state)
   - Restart recovery: re-read state, resume from earliest incomplete phase
   - Heartbeat throttling

6. **Common pitfalls**
   - Don't merge in completion order
   - Use double-dash branch separator
   - Always isolation=worktree when dispatching parallel subagents
   - MCP comment trailer tolerance (use `raw_decode`, not strict parse)

7. **Code snippets**
   - 3-5 short Python or pseudocode examples showing each pattern.

8. **Cross-references**
   - Link to each other skill's SKILL.md.
   - Link to POC's `SPEC.md` (§9 batch-job, §10 task-dag) for protocol-level detail.

## SKILL.md frontmatter

```yaml
---
name: composition-guide
description: |
  Reference guide for composing batch-job, task-dag, and
  orchestrate-issue without using the all-in-one orchestrator. Use
  when you want to wire the agent-job protocol primitives manually,
  drive a custom primary-agent loop, or understand the patterns
  available. Documentation only — no install actions.
allowed-tools:
  - Read
---
```

## Self-install logic

None. The skill has no installable artifacts.

It does emit a one-time message on first invocation: "I'm a reference
skill; I don't install anything. If you want the protocol installed,
invoke `batch-job`, `task-dag`, `orchestrate-issue`, or `onboarding`."

## Bundled templates

None. The skill is SKILL.md-only.

## Failure modes

The skill cannot fail beyond render errors — it only reads and emits
documentation.

## Tests

### In this POC

- Lint the rendered SKILL.md for broken cross-references (links to other skills must resolve to siblings in the package).

### In the new repo

- Verify each documented pattern is exercised by at least one test harness scenario.

## Anti-patterns

- **Do not** add install logic to this skill. It is a pure reference.
- **Do not** duplicate content that lives in other skills' SPECs — link instead.
- **Do not** silently update `composition-guide` content when other skills change; treat patterns as a stable contract.

## Dependencies

- No runtime dependencies.
- Conceptually depends on `batch-job`, `task-dag`, and
  `orchestrate-issue` existing in the same package.
