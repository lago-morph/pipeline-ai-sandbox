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

# task-dag

Manage the lifecycle of one agent-task GitHub issue as a DAG node.
The skill exposes four primitives — **claim**, **plan**, **merge**, and
**schedule_successors** — plus a `heartbeat()` helper for the polling
loop. It is the agent-side primitive for issue ownership. It does
**not** dispatch batch jobs (that is the `batch-job` skill) and does
**not** spawn subagents (the calling harness or `orchestrate-issue`
handles that).

The full design contract lives in `SPEC.md` next to this file; the
canonical protocol behind both lives at POC `SPEC.md` §4.1 (state
machine), §6 (branching model), and §10 (task-dag skill).

## When to use this skill

This skill matches when an agent is asked to:

- "Claim an issue and start working on it"
- "Find an unclaimed agent-task issue"
- "Plan subagents for issue N"
- "Merge subagent branches into the feature branch"
- "Schedule follow-up issues for this DAG node"
- "Use the task-dag skill"

It does **not** match generic GitHub issue work outside the agent-job
protocol — there is no `agent-task` label, no `agent-meta` block in
the issue body, no `_agent_runs` branch.

## Operations

### `claim` — take ownership of an issue

| Input | Type | Notes |
|---|---|---|
| `agent_id` | string | UUID-recommended; this process's identity |
| `agent_login` | string | The bot account login (sourced via `mcp__github__get_me` if not provided) |
| `candidate_issues` | list[int] | Optional; if omitted, scan open issues with `agent-task` label |

Output: `{issue, meta, agent_id, session_id}` if claimed, else `None`.

Implementation: `lib/claim.py`.

### `plan` — produce the work brief

| Input | Type | Notes |
|---|---|---|
| `issue_number` | int | Required |
| `agent_login` | string | Used to filter comments |

Output: `{brief, source, subagent_layout}` where `source` is `inline`
or the resolved `instructions_path`.

Implementation: `lib/plan.py`.

### `merge_subagent_branches` — overlay sub-branches into the feature branch

| Input | Type | Notes |
|---|---|---|
| `feature_branch` | string | Required |
| `subagent_branches` | list[string] | Required, in plan order |
| `conflict_strategy` | enum | `fail` (default), `ours`, `theirs`, `manual` |

Output: `{merged: [...], conflicts: [...], skipped: [...]}`.

Implementation: `lib/merge.py`. **Branches merge in plan order, not in
completion order.** The default conflict strategy is `fail`; silent
auto-merges mask integration bugs.

### `schedule_successors` — open follow-up issues

| Input | Type | Notes |
|---|---|---|
| `successors` | list[dict] | Each dict has `title`, `body`, `depends_on_prs`, `parent_issue` |
| `base_branch` | string | Default branch the successors fork from |

Output: list of created issue numbers.

Implementation: `lib/schedule_successors.py`. Successors are created
with `status: null` so any qualifying agent — this one or a later one
— can claim them.

## Procedure

These behaviours map directly onto POC `SPEC.md` §4.1, §6, and §10.

### Claim handshake (CAS-by-re-read)

1. Scan candidates (provided list, or open issues with the
   `agent-task` label).
2. Filter to those whose `status` is `null` or `status == "working"`
   with `status_ts` older than `issue.stale_seconds` (default 7200).
3. For the first eligible issue, write `agent_id` (your own) and a
   fresh `status_ts` into the `agent-meta` block via
   `mcp__github__issue_write`.
4. Sleep 5 seconds.
5. Re-read the issue. If `agent_id` is still ours, the claim
   succeeded — return `{issue, meta, agent_id, session_id}`. If a
   different `agent_id` is in the body, **self-abandon silently** and
   return `None`. The losing party never rewrites the body.

### Heartbeat

`task-dag` exposes a `heartbeat()` helper called inside every
polling cycle (typically by the `batch-job` skill while it polls a
comment to terminal status). It:

1. Re-reads the issue body.
2. Asserts `agent_id` matches the running process. On mismatch, the
   primary self-abandons.
3. Writes a fresh `status_ts`.

Throttled to at most one write per `issue.heartbeat_min_interval_seconds`
(default 60) to avoid issue-edit rate limits during long batch jobs.

### Merge order

Subagent branches **must** be merged in the order the plan declared,
not in the order their batch jobs returned. Completion-order merges
silently reorder commits and hide subtle integration bugs. The
`conflict_strategy` parameter controls behaviour on conflict:

| value | effect |
|---|---|
| `fail` (default) | abort the merge run; surface the conflicting branch and paths to the caller |
| `ours` | resolve via `git merge -X ours`; record the override in the result |
| `theirs` | resolve via `git merge -X theirs`; record the override |
| `manual` | leave the conflict markers in place and yield to the caller |

### Successors

`schedule_successors` creates new issues with `status: null` and
the same `agent-task` label. Successor issues:

- Carry `parent_issue` set to the originating issue's number.
- Carry `depends_on_prs` listing PR numbers that must be merged
  before the successor begins.
- Are never given `status: "working"` at creation — successors are
  unclaimed by definition. Any qualifying agent (including this one
  later) may claim them.

## Self-install logic

On first invocation in a target repo, the skill checks for each of
the following files and installs anything missing from this skill's
`templates/` directory. Skills are idempotent — re-running the
install on an already-installed repo is a no-op.

This skill's template inventory is the **superset of `batch-job`'s
templates plus the DAG-orchestration extras**:

| File or path (in target repo) | Source in this skill |
|---|---|
| `.agent/config.json` | `templates/agent/config.json` |
| `.agent/scripts/common.py` | `templates/agent/scripts/common.py` |
| `.agent/scripts/rest_client.py` | `templates/agent/scripts/rest_client.py` |
| `.agent/scripts/handler.py` | `templates/agent/scripts/handler.py` |
| `.agent/scripts/requirements.txt` | `templates/agent/scripts/requirements.txt` |
| `.agent/scripts/lock_and_sweep.py` | `templates/agent/scripts/lock_and_sweep.py` |
| `.agent/scripts/close_on_merge.py` | `templates/agent/scripts/close_on_merge.py` |
| `.agent/scripts/agent_lib/__init__.py` | `templates/agent/scripts/agent_lib/__init__.py` |
| `.agent/scripts/agent_lib/__main__.py` | `templates/agent/scripts/agent_lib/__main__.py` |
| `.agent/scripts/agent_lib/_common_loader.py` | `templates/agent/scripts/agent_lib/_common_loader.py` |
| `.agent/scripts/agent_lib/cli.py` | `templates/agent/scripts/agent_lib/cli.py` |
| `.agent/scripts/agent_lib/envelope.py` | `templates/agent/scripts/agent_lib/envelope.py` |
| `.agent/scripts/agent_lib/meta.py` | `templates/agent/scripts/agent_lib/meta.py` |
| `.agent/scripts/agent_lib/poll.py` | `templates/agent/scripts/agent_lib/poll.py` |
| `.agent/schemas/comment-envelope.schema.json` | `templates/agent/schemas/comment-envelope.schema.json` |
| `.agent/schemas/comment-ack-envelope.schema.json` | `templates/agent/schemas/comment-ack-envelope.schema.json` |
| `.agent/schemas/log-manifest.schema.json` | `templates/agent/schemas/log-manifest.schema.json` |
| `.agent/schemas/issue-body.schema.json` | `templates/agent/schemas/issue-body.schema.json` |
| `.agent/schemas/commands/bad-summary.schema.json` | `templates/agent/schemas/commands/bad-summary.schema.json` |
| `.agent/schemas/commands/build.schema.json` | `templates/agent/schemas/commands/build.schema.json` |
| `.agent/schemas/commands/chatty.schema.json` | `templates/agent/schemas/commands/chatty.schema.json` |
| `.agent/schemas/commands/echo.schema.json` | `templates/agent/schemas/commands/echo.schema.json` |
| `.agent/schemas/commands/run-tests.schema.json` | `templates/agent/schemas/commands/run-tests.schema.json` |
| `.agent/commands/__init__.py` | `templates/agent/commands/__init__.py` |
| `.agent/commands/bad_summary.py` | `templates/agent/commands/bad_summary.py` |
| `.agent/commands/build.py` | `templates/agent/commands/build.py` |
| `.agent/commands/chatty.py` | `templates/agent/commands/chatty.py` |
| `.agent/commands/echo.py` | `templates/agent/commands/echo.py` |
| `.agent/commands/run_tests.py` | `templates/agent/commands/run_tests.py` |
| `.github/workflows/batch-job-handler.yml` | `templates/github/workflows/batch-job-handler.yml` |
| `.github/workflows/lock-and-sweep.yml` | `templates/github/workflows/lock-and-sweep.yml` |
| `.github/workflows/close-on-merge.yml` | `templates/github/workflows/close-on-merge.yml` |
| `_agent_runs` orphan branch | Created empty if missing (see below) |

### Install procedure

For each path above:

1. If the target file is absent, write the bundled template via
   `mcp__github__create_or_update_file`.
2. If the target file is present and byte-identical to the bundled
   template, no-op.
3. If the target file is present but content differs, diff against
   the bundled template and ask the user: overwrite, skip, or write
   to `<path>.new` for manual merge. Record the user's choice in
   `.agent/installs/task-dag.log`.

The skill considers the protocol "installed" once `.agent/config.json`
exists. The install marker is checked on every invocation.

### `_agent_runs` orphan branch

The batch-job-handler writes log manifests, chunks, and `summary.json`
to a dedicated branch named `_agent_runs`. The branch holds no source
tree — it is an audit log only. The skill creates this branch if
missing as part of its self-install sequence:

1. Use `mcp__github__list_branches` to check whether `_agent_runs`
   exists.
2. If absent, use `mcp__github__create_branch` from the repo's empty
   tree (an initial commit on an orphan branch). Some MCP servers do
   not expose orphan-branch creation directly — in that case, fall
   back to a Bash invocation in a clean checkout:

   ```bash
   git checkout --orphan _agent_runs
   git rm -rf .
   git commit --allow-empty -m "Initialize _agent_runs audit branch"
   git push origin _agent_runs
   ```

3. If the branch already exists but its tree is non-empty and the
   contents look like a regular source branch, **refuse to overwrite**;
   surface to the user with a clear message naming the conflicting
   files and the suspected accidental push.

The branch must exist before any batch-job-handler workflow can write
logs. The skill creates it once and never touches it again.

### Composition with `batch-job`

If `batch-job`'s templates are already present (it was installed
first), all overlapping files no-op. If `task-dag` installs first,
later invocation of `batch-job` finds them present and no-ops. The
two skills share the same template surface for their overlap; the
contract test asserts byte-equivalence across the shared paths.

### Onboarding hint

When `task-dag` self-installs into a repo whose
`agent-job-protocol/onboarding` branch is absent, it emits a one-time
message:

> Protocol installed. Onboarding has not been run in this repo. Run
> `/onboarding` for guided integration with your existing workflow,
> or skip — the skills work standalone.

The hint is recorded in `.agent/installs/task-dag.log` so it appears
only once per session.

## Crash recovery

A new agent process invoking `claim` will discover stale issues
(those whose `status_ts` is older than `issue.stale_seconds`) and
adopt them via the same handshake used for fresh claims. After
takeover the agent:

1. Reads the issue body and all comments.
2. Classifies each comment as in-flight (`run_status` non-terminal),
   terminal-unacked (`run_status` terminal, `agent_ack` null), or
   terminal-acked.
3. For terminal-unacked, reads the summary, integrates the outcome,
   then acks via the `batch-job` skill.
4. For in-flight, waits for terminal status subject to the runner-
   pickup and running deadlines; converts to abandoned if those
   deadlines have already elapsed.
5. If subagent branches exist but the feature-branch merge is
   partial, restarts from `merge_subagent_branches` (the implementation
   is idempotent — already-merged branches are skipped).

All recovery state lives on GitHub. No local agent state is required
for resumption; an empty workspace is sufficient. See POC `SPEC.md`
§10.4 for the canonical recovery contract.

## Failure modes

| Failure | Detection | Handling |
|---|---|---|
| No candidate issues | Empty list after filtering | Return `None`; caller decides next action |
| Claim race lost | Re-read shows different `agent_id` | Self-abandon silently; return `None` |
| Stale takeover collides | Two successors both wrote `agent_id` | Loser self-abandons on re-read |
| Instructions resolution fails | `instructions_path` returns 404 | Raise `InstructionsNotFoundError` to caller |
| Merge conflict | `git merge` returns non-zero | Apply `conflict_strategy`; surface to caller when `fail` |
| `_agent_runs` exists with non-audit content | `list_branches` + tree check | Refuse to overwrite; surface to user |
| Successor creation hits rate limit | MCP returns 403/429 | Retry with exponential backoff |
| Heartbeat finds `agent_id` mismatch | Re-read inside `heartbeat()` | Self-abandon; raise `LostOwnershipError` to the polling loop |
| Missing `agent-meta` in body | Parse fails after fetch | Treat as a non-protocol issue; skip during claim, raise during `plan` |

## Anti-patterns

- **Do not** lock issues at creation. `lock_and_sweep` applies the
  `agent-task` label only; locking happens at issue-close in
  `close_on_merge`. Locking earlier breaks the batch-job-handler's
  ability to write terminal envelopes.
- **Do not** use single-slash branch separators for subagent branches
  (`feature/sub-01`). Always double-dash: `feature--sub-01`. Single
  slashes collide with the ref namespace because the parent ref
  becomes a directory the moment a child ref exists.
- **Do not** merge in completion order. Always plan order. The plan
  is the source of truth for cross-subagent dependencies.
- **Do not** create successor issues with `status` set to anything
  other than `null`. Successors are unclaimed by definition; any
  qualifying agent may pick them up.
- **Do not** invoke the `batch-job` skill via the Skill tool from
  inside `task-dag`. Call into the Python helpers under
  `.agent/scripts/agent_lib/` instead. Cross-skill Skill-tool
  invocation is not supported in v1 (too easy to recurse).
- **Do not** rewrite the issue body after losing the claim race. The
  losing agent's only correct action is to walk away silently.

## Dependencies

- None at the skill level. Self-installs on first invocation.
- At runtime: a GitHub MCP server and a writable `_agent_runs`
  branch. Both are bootstrapped by the install procedure above.
- Composable with `batch-job` — `orchestrate-issue` wires them
  together; users can also wire them manually following the
  `composition-guide` skill.

---
Version: 1.0.0
Protocol-version: 1
Last-synced-from-POC: 2026-05-14
---
