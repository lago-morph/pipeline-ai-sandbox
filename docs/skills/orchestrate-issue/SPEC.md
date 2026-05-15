# SPEC — orchestrate-issue skill

Status: design-stage
Audience: implementers of the skill in the new `pipeline-ai-sandbox` repo

## Purpose

Drive the **end-to-end primary-agent loop** for one issue:

1. Claim the issue (via `task-dag.claim`)
2. Plan subagents (via `task-dag.plan`)
3. Fan out parallel subagents — each owning one sub-branch
4. Each subagent runs `batch-job` against its branch
5. Merge subagent branches into the feature branch in plan order
6. Open the PR with run report
7. Optionally schedule successors

This is the "heavy adoption" skill: one invocation runs the whole
primary-agent's lifecycle for a single issue. Users who prefer the
primitives compose `task-dag` + `batch-job` themselves (see
`composition-guide`).

The skill implements the parallel-subagent-fanout pattern from
`software-factory/.claude/skills/parallel-subagent-fanout/SKILL.md`,
specialised to the agent-job protocol's branching and acking model.

## Trigger conditions

The skill matches when an agent is asked to:

- "Take this issue and finish it end-to-end"
- "Orchestrate the work on issue N"
- "Pick up the next unclaimed issue and ship it"
- "Run the full primary-agent loop"
- "Use the orchestrate-issue skill"

## Inputs

| Field | Type | Required | Notes |
|---|---|---|---|
| `issue_number` | int | no | If omitted, the skill scans for an unclaimed or stale issue |
| `agent_id` | string | no | Defaults to a generated UUID |
| `agent_login` | string | no | Resolved via `mcp__github__get_me` if omitted |
| `max_parallel` | int | no | Default 4. Cap on concurrent subagents per wave |
| `conflict_strategy` | enum | no | `fail` (default), `ours`, `theirs`, `manual` |
| `subagent_type` | string | no | Default `general-purpose`. Per the harness's Agent tool |
| `dry_run` | bool | no | Default False. If True, run through plan + brief generation and stop before dispatching |

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

## Procedure

### Phase 0 — pre-flight

- Self-install protocol templates if missing (delegates to install
  logic shared with `batch-job` and `task-dag`).
- Resolve `agent_login` via `mcp__github__get_me` if not provided.
- Generate `run_id` as `YYYYMMDD-HHMMSS` UTC.

### Phase 1 — claim

Delegate to `task-dag.claim`. If no claimable issue is available and
`issue_number` was not provided, exit with `{"reason": "no_work"}`.

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
overlap, the skill re-prompts for refinement.

### Phase 3 — write state.json

Write `.agent/runs/<run_id>/state.json`:

```json
{
  "run_id": "<run_id>",
  "issue_number": <n>,
  "feature_branch": "<>",
  "subtasks": [
    {
      "id": "sub-01",
      "title": "...",
      "branch": "...--sub-01",
      "status": "pending",
      "request_comment_id": null,
      "ack_comment_id": null,
      "subagent_pr": null,
      "tests_delta": null
    }
  ]
}
```

Commit and push the state file on the feature branch.

### Phase 4 — create sub-branches

For each subtask, create `<feature_branch>--sub-<id>` from the current
feature-branch tip. Double-dash separator (POC SPEC §6).

### Phase 5 — fanout (parallel)

Dispatch all subagents **in a single dispatcher message** using
multiple Agent tool calls. Wave-limit by `max_parallel`:

- Wave 1: subagents `sub-01` … `sub-<max_parallel>`
- Wait for all of wave 1 to complete
- Wave 2: next batch
- Continue until all dispatched

Each Agent call uses `isolation: "worktree"` (critical — without it,
parallel subagents race on `git checkout` and contaminate each other's
branches).

Each subagent's brief follows the subagent-prompting 9-section
template, specialised for the agent-job protocol:

1. **Identity + goal** — "You are sub-<id> for issue <n>. Your task: <description>."
2. **Context** — the issue's body, the spec path, the run_id.
3. **Repo and branch** — explicit "commit to <feature_branch>--sub-<id> ONLY".
4. **What to build** — 3-7 specific bullets derived from the subtask.
5. **Protocol contract** — "When done, invoke the `batch-job` skill with command `<>`, args `<>`, branch `<feature_branch>--sub-<id>`, commit_sha `<HEAD>`. Wait for terminal ack. Report back."
6. **Don'ts** — do not merge, do not switch branches, do not touch files outside your `files_touched` list.
7. **Validation** — assert local git state matches expected before reporting.
8. **Deliverable shape** — exact report format (sub-branch, batch-job comment id, batch-job summary, tests delta, issues).
9. **Traps** — double-dash separator, MCP comment-trailer tolerance, etc.

### Phase 6 — collect

For each subagent's report:

- Parse the deliverable.
- Update `state.json`: set `status` to `dispatched_ok` or `failed`.
- Persist after each update (restart-safe).

If any subtask failed, the skill stops before merge and surfaces a
choice to the user: skip, retry, or abort. If the skill is running
unattended (overnight), the default is to **skip failed subtasks**
and continue with merge; the failures land in the run report.

### Phase 7 — merge in plan order

For each subtask in plan order with `status == dispatched_ok`:

```bash
git checkout <feature_branch>
git merge --no-ff <feature_branch>--sub-<id>
```

Apply `conflict_strategy` on conflicts. Push the feature branch after
each successful merge. Update `state.json` to `merged` or `conflict`.

### Phase 8 — open PR

Open a PR from the feature branch to `base_branch` (read from
`agent-meta`). PR body includes:

- Run report summary table (one row per subtask)
- The run_id
- Links to all batch-job ack comments
- Any failed subtasks called out

### Phase 9 — finalise issue

Write `status: finished` into the `agent-meta` block. Post a final
comment summarising the work. Close the issue. (The
`close-on-merge.yml` workflow handles the lock when the PR merges.)

### Phase 10 — schedule successors (optional)

If the plan or instructions defined successors, create them via
`task-dag.schedule_successors`.

## Self-install logic

Superset of `batch-job` and `task-dag` install logic. Idempotent.
After install, advertises the onboarding skill if not yet run.

## Bundled templates

Same as `task-dag` (which is a superset of `batch-job`). No new
templates unique to this skill — it composes the others'.

The skill does carry one new file inside its own directory (not a
target-repo template):

```
templates/
  brief-template.md     # the 9-section subagent brief template
```

Used internally during Phase 5 to generate briefs.

## SKILL.md frontmatter

```yaml
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
```

## Failure modes

| Failure | Detection | Handling |
|---|---|---|
| No claimable issue | Phase 1 returns None | Exit cleanly with `{"reason": "no_work"}` |
| Plan produces overlapping subtasks | Phase 2 validation | Re-prompt; if user-driven mode unavailable, fall back to serial single-subagent execution |
| Subagent fails | Phase 6 | Update state; skip in plan-order merge; record in run report |
| Merge conflict with strategy `fail` | Phase 7 | Stop; surface to user |
| PR creation fails | Phase 8 | Retry with backoff; on persistent failure write a `.PENDING_PR.md` and exit with diagnostic |
| Restart mid-run | Restart detection | Read `state.json`; resume from earliest incomplete phase |

## Restart recovery

The skill is restart-safe via `state.json`. On invocation, if a
`state.json` exists for an in-progress run on the feature branch and
the issue is still `working` under this `agent_id`:

- Resume from the earliest phase with incomplete state.
- Skip already-merged sub-branches.
- Skip already-acked batch-job comments.
- Re-collect subagent reports if their `request_comment_id` exists but `ack_comment_id` is null and the request comment is in terminal state.

## Tests

### In this POC

- Contract test (templates are byte-equivalent).
- Dry-run mode: run Phases 0-3 against a mock GitHub client, verify state.json is correctly shaped.
- Subagent brief generator: assert generated briefs follow the 9-section template against a fixture plan.

### In the new repo

- Full e2e: drive an orchestrate-issue invocation against a synthetic archetype in the test harness. Verify PR opens, all sub-branches merge, all batch-jobs complete, run report is written.
- Conflict-injection: deliberately create overlapping subtasks; assert the conflict_strategy options each produce the expected outcome.
- Restart test: kill the orchestrator mid-fanout; restart; verify completion.
- Wave-limit test: dispatch 9 subagents with max_parallel=4; assert two waves of 4 + one wave of 1.

## Anti-patterns

- **Do not** dispatch subagents across multiple messages. The harness only parallelises within a single message.
- **Do not** dispatch without `isolation: "worktree"`. Concurrent worktree-less subagents corrupt each other's branches.
- **Do not** merge in completion order. Always plan order.
- **Do not** open the PR before all in-plan-order merges succeed.
- **Do not** silently force-merge a conflict.
- **Do not** write `status: finished` to `agent-meta` until the PR is open.

## Dependencies

- Self-installs the protocol templates (superset of `batch-job` + `task-dag`).
- Internally calls into `batch-job` and `task-dag` logic (those skills' Python helpers, importable as a library).
- Requires the harness's `Agent` tool for subagent dispatch.
- Requires a GitHub MCP server.
