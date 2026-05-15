---
name: orchestrate-issue
description: |
  End-to-end primary-agent loop for one GitHub issue: claim, plan,
  fan out parallel subagents, run batch jobs, merge, open PR. Use
  when an agent needs to take a single issue from unclaimed to merged
  PR with parallel subagent execution. Self-installs the agent-job
  protocol templates on first invocation.
allowed-tools:
  - Bash
  - Read
  - Write
  - Edit
  - Agent
  - mcp__github__*
---

# orchestrate-issue

End-to-end primary-agent loop for the agent-job protocol. This skill
takes a single GitHub issue from `status: null` (unclaimed) all the
way to a merged PR with a run report. It composes the `task-dag` and
`batch-job` primitives plus a parallel-subagent fanout pattern.

This is the **heavy adoption** skill. Users who prefer to compose the
primitives themselves should consult `composition-guide` and call
`task-dag` and `batch-job` directly.

The skill follows the parallel-subagent-fanout pattern from
software-factory, specialised to the agent-job protocol's branching
and acking model. Software-factory's skill is a reference pattern,
not an install-time dependency.

## Triggers

The skill matches when an agent is asked to:

- "Take this issue and finish it end-to-end"
- "Orchestrate the work on issue N"
- "Pick up the next unclaimed issue and ship it"
- "Run the full primary-agent loop"
- "Use the orchestrate-issue skill"

It does **not** match general "run tests" requests outside the
agent-job protocol — those route to `batch-job` directly.

## Inputs

| Field | Type | Required | Notes |
|---|---|---|---|
| `issue_number` | int | no | If omitted, the skill scans for an unclaimed or stale issue |
| `agent_id` | string | no | Defaults to a generated UUID |
| `agent_login` | string | no | Resolved via `mcp__github__get_me` if omitted |
| `max_parallel` | int | no | Default 4. Cap on concurrent subagents per wave |
| `conflict_strategy` | enum | no | `fail` (default), `ours`, `theirs`, `manual` |
| `subagent_type` | string | no | Default `general-purpose`. Per the harness's Agent tool |
| `dry_run` | bool | no | Default False. Run Phases 0-3, stop before dispatch |

## Outputs

```json
{
  "issue_number": 42,
  "feature_branch": "agent/42-...",
  "subagent_branches": ["agent/42-...--sub-01", "..."],
  "pr_number": 123,
  "pr_url": "https://github.com/.../pull/123",
  "tests_delta": "+12",
  "run_report_path": ".agent/runs/<run_id>/report.md",
  "successors_scheduled": [],
  "elapsed_seconds": 1843
}
```

## Procedure (10 phases)

### Phase 0 — pre-flight

- Self-install protocol templates if missing (superset of `batch-job`
  + `task-dag` install logic; idempotent).
- Resolve `agent_login` via `mcp__github__get_me` if not provided.
- Generate `run_id` as `YYYYMMDD-HHMMSS` UTC.
- Detect any in-progress run for the same agent on the same feature
  branch — if found, jump to Phase Restart-Recovery.

### Phase 1 — claim

Delegate to `task-dag.claim` (Python helper at
`.agent/scripts/agent_lib/` plus the `task-dag` skill's `lib/`).
If no claimable issue is available and `issue_number` was not
provided, exit cleanly with `{"reason": "no_work"}`.

### Phase 2 — plan

Delegate to `task-dag.plan`. Convert the brief into a subagent layout:

```yaml
run_id: <run_id>
issue: <issue_number>
feature_branch: <feature_branch from agent-meta>
subtasks:
  - id: sub-01
    title: <short name>
    description: <one-sentence>
    files_touched: [<paths>]
    branch: <feature_branch>--sub-01
    command: <command to run via batch-job>
    args: { ... }
```

Subtasks must touch disjoint file paths. If the plan output suggests
overlap, the skill re-prompts for refinement. If refinement is
unavailable (unattended mode), fall back to serial single-subagent
execution.

### Phase 3 — write state.json

Write `.agent/runs/<run_id>/state.json`:

```json
{
  "run_id": "<run_id>",
  "issue_number": 42,
  "feature_branch": "agent/42-...",
  "subtasks": [
    {
      "id": "sub-01",
      "title": "...",
      "branch": "agent/42-...--sub-01",
      "status": "pending",
      "request_comment_id": null,
      "ack_comment_id": null,
      "subagent_pr": null,
      "tests_delta": null
    }
  ]
}
```

Commit and push `state.json` on the feature branch. This file is the
durability anchor for restart recovery.

### Phase 4 — create sub-branches

For each subtask, create `<feature_branch>--sub-<id>` from the current
feature-branch tip. Always use the **double-dash separator** (POC
SPEC §6). Never single-slash (`feature/sub-01`).

### Phase 5 — fanout (parallel)

Dispatch all subagents **in a single dispatcher message** using
multiple Agent tool calls. The harness only parallelises within one
message — splitting across messages serialises them.

Wave-limit by `max_parallel`:

- Wave 1: subagents `sub-01` … `sub-<max_parallel>`.
- Wait for all of wave 1 to complete.
- Wave 2: next batch.
- Continue until all dispatched.

Each Agent call uses `isolation: "worktree"` (critical — without it,
parallel subagents race on `git checkout` and contaminate each
other's branches).

Generate each subagent's brief from `templates/brief-template.md`
(this skill's internal template, not a target-repo template). The
brief is the 9-section subagent-prompting template, specialised for
the agent-job protocol. See `templates/brief-template.md` for the
exact section list and placeholder tokens.

### Phase 6 — collect

For each subagent's terminal report:

- Parse the deliverable (the subagent must include the structured
  fields enumerated in section 8 of the brief).
- Update `state.json`: set `status` to `dispatched_ok` or `failed`.
- Persist after each update (restart-safe).

If any subtask failed, the skill stops before merge and surfaces a
choice to the user: skip, retry, or abort. If running unattended
(overnight), the default is to **skip failed subtasks** and continue
with merge; the failures land in the run report.

### Phase 7 — merge in plan order

For each subtask with `status == dispatched_ok`, in plan order
(not completion order):

```bash
git checkout <feature_branch>
git merge --no-ff <feature_branch>--sub-<id>
```

Apply `conflict_strategy` on conflicts:

- `fail` (default) — surface to caller, halt merge phase.
- `ours` — keep the feature-branch side; record in run report.
- `theirs` — keep the subagent side; record in run report.
- `manual` — pause for user intervention.

Push the feature branch after each successful merge. Update
`state.json` to `merged` or `conflict` per subtask.

### Phase 8 — open PR

Open a PR from the feature branch to `base_branch` (read from
`agent-meta`). PR body includes:

- Run report summary table (one row per subtask)
- The `run_id`
- Links to all `batch-job` ack comments
- Any failed subtasks called out explicitly

On persistent PR-creation failure, write `.PENDING_PR.md` at the
feature-branch root with diagnostics, and exit with a typed error so
a human can recover.

### Phase 9 — finalise issue

Write `status: finished` into the issue's `agent-meta` block. Post a
final summary comment. Close the issue. The `close-on-merge.yml`
workflow then locks the issue when the PR merges (locking is
post-close, not at creation — POC SPEC §10.5).

### Phase 10 — schedule successors (optional)

If the plan or instructions defined successors, delegate to
`task-dag.schedule_successors`. Each successor is created with
`status: null` so any qualifying agent can claim it.

## Self-install

Superset of `batch-job` and `task-dag` install logic. Idempotent.
On invocation, the skill checks for the presence of:

| File or path | Action if missing |
|---|---|
| `.agent/config.json` | Copy from `templates/agent/config.json` |
| `.agent/scripts/common.py` | Copy from `templates/agent/scripts/common.py` |
| `.agent/scripts/rest_client.py` | Copy from `templates/agent/scripts/rest_client.py` |
| `.agent/scripts/handler.py` | Copy from `templates/agent/scripts/handler.py` |
| `.agent/scripts/requirements.txt` | Copy from `templates/agent/scripts/requirements.txt` |
| `.agent/scripts/lock_and_sweep.py` | Copy from `templates/agent/scripts/lock_and_sweep.py` |
| `.agent/scripts/close_on_merge.py` | Copy from `templates/agent/scripts/close_on_merge.py` |
| `.agent/scripts/agent_lib/` (directory) | Copy entire directory |
| `.agent/schemas/comment-envelope.schema.json` | Copy from `templates/agent/schemas/` |
| `.agent/schemas/comment-ack-envelope.schema.json` | Copy from `templates/agent/schemas/` |
| `.agent/schemas/log-manifest.schema.json` | Copy from `templates/agent/schemas/` |
| `.agent/schemas/issue-body.schema.json` | Copy from `templates/agent/schemas/` |
| `.agent/schemas/commands/` (directory) | Copy entire directory |
| `.agent/commands/` (directory) | Copy entire directory |
| `.github/workflows/batch-job-handler.yml` | Copy from `templates/github/workflows/` |
| `.github/workflows/lock-and-sweep.yml` | Copy from `templates/github/workflows/` |
| `.github/workflows/close-on-merge.yml` | Copy from `templates/github/workflows/` |
| `agent-task` label on the GitHub repo | Create via MCP (no schema match — REST POST) |
| `_agent_runs` orphan branch | Create empty orphan branch if missing |

Conflict handling on install:

1. If the target file is byte-identical to the bundled template — no-op.
2. If content differs — diff to the user, ask overwrite/skip/`.new`.
3. Skips are recorded in `.agent/installs/orchestrate-issue.log`.

`AGENTS.md` and `CLAUDE.md` are **never** in the installable file
list. Pointer-line edits to those files are the `onboarding` skill's
job, with explicit per-file user approval.

After install, the skill advertises the `onboarding` skill if the
well-known branch `agent-job-protocol/onboarding` does not exist.
Decline is fine — this skill works standalone.

## Failure modes

| Failure | Detection | Handling |
|---|---|---|
| No claimable issue | Phase 1 returns None | Exit cleanly with `{"reason": "no_work"}` |
| Plan produces overlapping subtasks | Phase 2 validation | Re-prompt; if unattended, fall back to serial single-subagent execution |
| Subagent fails | Phase 6 | Update state; skip in plan-order merge; record in run report |
| Merge conflict with strategy `fail` | Phase 7 | Stop; surface to user |
| PR creation fails | Phase 8 | Retry with backoff; on persistent failure write `.PENDING_PR.md` and exit with diagnostic |
| Restart mid-run | Restart detection in Phase 0 | Read `state.json`; resume from earliest incomplete phase |
| Heartbeat lost (parent issue stale) | `task-dag.heartbeat` raises | Surface immediately — claim has likely been swept |

## Restart recovery

The skill is restart-safe via `state.json`. On invocation, if a
`state.json` exists for an in-progress run on the feature branch and
the issue is still `working` under this `agent_id`:

- Resume from the earliest phase with incomplete state.
- Skip already-merged sub-branches.
- Skip already-acked `batch-job` comments.
- Re-collect subagent reports if their `request_comment_id` exists
  but `ack_comment_id` is null and the request comment is in terminal
  state.
- Continue Phase 5 only for subtasks whose `status` is still
  `pending` — never re-dispatch a subagent that already produced an
  ack.

## Anti-patterns

- **Do not** dispatch subagents across multiple messages. The harness
  only parallelises within a single message.
- **Do not** dispatch without `isolation: "worktree"`. Concurrent
  worktree-less subagents corrupt each other's branches.
- **Do not** merge in completion order. Always plan order.
- **Do not** open the PR before all in-plan-order merges succeed.
- **Do not** silently force-merge a conflict.
- **Do not** write `status: finished` to `agent-meta` until the PR
  is open.
- **Do not** invoke `batch-job` or `task-dag` via the Skill tool from
  inside this skill — call into their Python helpers instead (v1
  contract — too easy to recurse otherwise).
- **Do not** lock issues at creation; locking is post-close only.
- **Do not** use single-slash branch separators (`feature/sub-01`).
  Always double-dash (`feature--sub-01`).

## Dependencies

- Self-installs the protocol templates (superset of `batch-job` +
  `task-dag`).
- Internally calls into `batch-job` and `task-dag` logic (those
  skills' Python helpers, importable as a library — not Skill-tool
  invocations).
- Requires the harness's `Agent` tool for subagent dispatch.
- Requires a GitHub MCP server.

---
Version: 1.0.0
Protocol-version: 1
Last-synced-from-POC: 2026-05-14
---
