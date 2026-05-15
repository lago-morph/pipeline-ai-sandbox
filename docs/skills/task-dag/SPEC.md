# SPEC — task-dag skill

Status: design-stage
Audience: implementers of the skill in the new `pipeline-ai-sandbox` repo

## Purpose

Manage the lifecycle of one agent-task issue as a DAG node:

- **claim** — pick an unclaimed or stale issue and take ownership via CAS-by-re-read
- **plan** — produce a work brief from `instructions_inline` or `instructions_path`
- **merge** — overlay subagent branches onto the feature branch
- **schedule_successors** — open follow-up issues with `status: null`

The skill is the agent-side primitive for issue ownership. It does
**not** dispatch batch jobs (that is `batch-job`) and does **not**
spawn subagents (that is the calling agent's harness-specific job, or
`orchestrate-issue`'s).

## Trigger conditions

The skill matches when an agent is asked to:

- "Claim an issue and start working on it"
- "Find an unclaimed agent-task issue"
- "Plan subagents for issue N"
- "Merge subagent branches into the feature branch"
- "Schedule follow-up issues for this DAG node"
- "Use the task-dag skill"

It does **not** match generic GitHub issue work outside the
agent-job protocol.

## Inputs and outputs

### claim

| Input | Type | Notes |
|---|---|---|
| `agent_id` | string | UUID-recommended; this process's identity |
| `agent_login` | string | The bot account login (sourced via `mcp__github__get_me` if not provided) |
| `candidate_issues` | list[int] | Optional; if omitted, scan open issues with `agent-task` label |

Output: `{issue, meta, agent_id, session_id}` if claimed, else `None`.

### plan

| Input | Type | Notes |
|---|---|---|
| `issue_number` | int | Required |
| `agent_login` | string | Used to filter comments |

Output: `{brief, source, subagent_layout}` where `source` is `inline`
or the resolved `instructions_path`.

### merge_subagent_branches

| Input | Type | Notes |
|---|---|---|
| `feature_branch` | string | Required |
| `subagent_branches` | list[string] | Required, in plan order |
| `conflict_strategy` | enum | `fail` (default), `ours`, `theirs`, `manual` |

Output: `{merged: [...], conflicts: [...], skipped: [...]}`.

### schedule_successors

| Input | Type | Notes |
|---|---|---|
| `successors` | list[dict] | Each dict has `title`, `body`, `depends_on_prs`, `parent_issue` |
| `base_branch` | string | Default branch the successors fork from |

Output: list of created issue numbers.

## Procedure

The procedures map directly onto SPEC §4.1 (state machine), §10 (skill
spec), and §6 (branching model) in the POC. Highlights:

- **Claim handshake**: CAS-by-re-read. Write `agent_id` + `status_ts`.
  Wait 5 seconds. Re-read. If `agent_id` is still ours, claim succeeded;
  otherwise self-abandon quietly.
- **Heartbeat**: `task-dag` exposes a `heartbeat()` helper. It re-reads
  the issue, asserts `agent_id` matches, refreshes `status_ts`.
  Throttled to `heartbeat_min_interval_seconds`.
- **Merge order**: subagent branches merge in **plan order**, not
  completion order. The conflict strategy is configurable but the
  default is `fail` — silent merges hide integration bugs.
- **Successors**: `status: null` issues are created so any qualifying
  agent (this one or a successor) can pick them up later.

## Self-install logic

Same template inventory as `batch-job`, plus:

| File or path | Action if missing |
|---|---|
| `.agent/scripts/lock_and_sweep.py` | Copy from `templates/agent/scripts/` |
| `.agent/scripts/close_on_merge.py` | Copy from `templates/agent/scripts/` |
| `.github/workflows/lock-and-sweep.yml` | Copy from `templates/github/workflows/` |
| `.github/workflows/close-on-merge.yml` | Copy from `templates/github/workflows/` |
| `_agent_runs` orphan branch | Create empty orphan branch if missing |

The `_agent_runs` branch must exist before any batch-job-handler can
write logs. The skill creates it on install via a sequence of
`mcp__github__create_branch` + an initial empty commit.

If templates from `batch-job` are already in place (skill was
installed by `batch-job` earlier), no-op. Skills are idempotent in
their install actions.

## Bundled templates

Superset of `batch-job`'s templates, plus:

```
templates/
  agent/
    scripts/
      lock_and_sweep.py
      close_on_merge.py
  github/
    workflows/
      lock-and-sweep.yml
      close-on-merge.yml
```

Contract-tested for byte-equivalence with the POC source.

## SKILL.md frontmatter

```yaml
---
name: task-dag
description: |
  Manage one agent-task GitHub issue as a DAG node: claim it, plan
  subagents, merge subagent branches, and schedule follow-up issues.
  Self-installs the protocol's workflow + script templates on first
  invocation. Use when an agent is taking ownership of a multi-step
  task represented by a GitHub issue.
allowed-tools:
  - Bash
  - Read
  - Write
  - Edit
  - mcp__github__issue_read
  - mcp__github__issue_write
  - mcp__github__add_issue_comment
  - mcp__github__create_branch
  - mcp__github__list_issues
  - mcp__github__list_branches
  - mcp__github__create_or_update_file
---
```

## Failure modes

| Failure | Detection | Handling |
|---|---|---|
| No candidate issues | Empty list after filtering | Return `None`; caller decides |
| Claim race lost | Re-read shows different `agent_id` | Self-abandon; return `None` |
| Instructions resolution fails | `instructions_path` 404 | Raise `InstructionsNotFoundError` |
| Merge conflict | git returns non-zero | Apply `conflict_strategy`; surface to caller if `fail` |
| `_agent_runs` already exists with conflicting content | Branch listing | Refuse to overwrite; surface to user |
| Successor creation hits rate limit | MCP error | Retry with backoff |

## Tests

### In this POC

- Contract test for template parity.
- Schema validity for any new schemas.
- Dry-run claim against a mock GitHub client; assert handshake works.

### In the new repo

- Reuse the POC's `tests/unit/test_skill_task_dag.py` baseline (claim, plan, merge, schedule_successors).
- Real-GitHub e2e: drive a claim → plan → batch-job → merge → schedule loop against the new repo itself.
- Restart-recovery test: kill the agent mid-claim; verify a new agent picks up correctly per SPEC §10.4.

## Anti-patterns

- **Do not** lock issues at creation. The `lock_and_sweep` template
  intentionally does not lock. Locking is at issue-close only.
- **Do not** use single-slash branch separators (`feature/sub-01`).
  Always double-dash (`feature--sub-01`).
- **Do not** merge in completion order. Always plan order.
- **Do not** create successor issues with `status` set to anything
  other than `null`. Successors are unclaimed by definition.

## Dependencies

- None at skill level. Self-installs.
- At runtime, depends on a GitHub MCP server and a writable
  `_agent_runs` branch (which it creates if missing).
- Composable with `batch-job` — the `orchestrate-issue` skill wires
  them together; users can also wire them manually following
  `composition-guide`.
