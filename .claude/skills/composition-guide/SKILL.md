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

# composition-guide

> I'm a reference skill; I don't install anything. If you want the
> protocol installed, invoke `batch-job`, `task-dag`,
> `orchestrate-issue`, or `onboarding`.

This skill documents how to **compose** the agent-job protocol
primitives (`batch-job`, `task-dag`) into custom primary-agent loops
for users who want finer control than the bundled `orchestrate-issue`
skill offers. It is documentation only: there are no templates, no
install logic, and no side effects.

Patterns described here mirror what `orchestrate-issue` does
internally, but exposed as building blocks you can reorder, omit, or
specialise. If you simply want the default end-to-end loop, invoke
`orchestrate-issue` instead.

## 1. When to use each skill

The agent-job package exposes four implementation skills plus this
reference. Pick the one that matches your level of involvement:

| Skill | Use when |
|---|---|
| `batch-job` | You need to dispatch a single workflow command (tests, build, deploy) against an existing branch + commit and wait for terminal status. One-shot. No issue claim, no PR, no merge. |
| `task-dag` | You own an issue end-to-end as a DAG node: claim it, plan subagents, merge their branches in plan order, schedule successors. Does **not** dispatch batch jobs itself. |
| `orchestrate-issue` | You want the entire primary-agent loop in one invocation: claim → plan → fan out → batch-job per subagent → merge → PR. Highest abstraction; least customisable. |
| `onboarding` | You want a guided interview to discover how the protocol should integrate with the target repo's existing workflow. Produces a recommendations doc; can optionally apply edits. |
| `composition-guide` (this) | You want the **primitives**, not the orchestrator. Read this to learn how to wire `batch-job` + `task-dag` yourself. |

### Decision tree

```
Do you have one issue to ship end-to-end with parallel subagents?
├── Yes → use orchestrate-issue
└── No
    ├── Do you have one branch+command to run? → use batch-job
    ├── Do you need to claim an issue but drive the loop yourself? → use task-dag
    ├── Are you onboarding a new repo to the protocol? → use onboarding
    └── Are you composing several primitives in a custom shape? → read this guide
```

### What this guide does NOT cover

- The protocol envelope schemas. See POC `SPEC.md` §9 (batch-job) and
  §10 (task-dag) for canonical wire-format detail.
- Installing templates. See each implementation skill's SKILL.md for
  self-install behavior.
- General Claude Code subagent dispatch. See the
  `parallel-subagent-fanout` skill in `software-factory` for the
  generic version of the fanout pattern below.

## 2. Pattern — single-subagent linear loop

The simplest composition. One primary agent, one issue, one branch,
one or more sequential batch-jobs. No fanout. No subagents.

### Shape

```
claim (task-dag)
  └── plan (task-dag)         # but you ignore subagent_layout
       └── for each step:
              edit code        # locally
              commit + push    # to feature branch
              batch-job        # run the relevant command
              ack received
       └── merge nothing       # there are no sub-branches
       └── open PR             # manually via mcp__github__create_pull_request
       └── (optional) schedule successors (task-dag)
```

### When to use

- The task is small enough that splitting into subagents would add
  more orchestration cost than it saves.
- The work is inherently serial (each step depends on the last).
- You want maximum visibility into each batch-job, one at a time.
- You're prototyping a new command and want to drive each invocation
  by hand.

### When NOT to use

- Tasks where files-touched are disjoint and could run in parallel.
- Long-running e2e suites where waiting serially burns wall clock.

### Variant: linear loop with multiple commands

You can dispatch successive batch-jobs against the same branch as
long as each step's commit_sha is the HEAD of the branch when the job
runs. Typical sequence: `lint` → `test` → `build` → `deploy`.

## 3. Pattern — parallel-subagent fanout

The pattern that `orchestrate-issue` implements internally. One
primary agent dispatches N subagents in parallel; each subagent owns
one sub-branch and runs its own batch-job; the primary collects,
merges in plan order, and opens the PR.

### Shape

```
claim (task-dag)
  └── plan (task-dag) → subagent_layout with N subtasks
       └── write .agent/runs/<run_id>/state.json
       └── create sub-branches: <feature>--sub-01, --sub-02, ...
       └── dispatch N subagents in a SINGLE message
             ├── each subagent gets isolation: "worktree"
             ├── each subagent invokes batch-job on its sub-branch
             └── each subagent reports back to the primary
       └── collect results, update state.json
       └── merge sub-branches into feature branch in PLAN ORDER
       └── open PR via mcp__github__create_pull_request
       └── (optional) schedule successors
```

### Critical rules

- **Single message dispatch.** The Claude Code harness only
  parallelises Agent calls made within one message. Spread the calls
  across messages and they will run serially.
- **Worktree isolation.** Pass `isolation: "worktree"` on every Agent
  call. Without it, concurrent subagents race on `git checkout` and
  contaminate each other's working trees.
- **Double-dash branch separator.** Use `feature--sub-01`, not
  `feature/sub-01`. Single slash collides with refspec parsing in
  some downstream tools (see POC SPEC.md §6).
- **Plan-order merge.** Merge in the order subtasks were planned,
  never in completion order. Completion order hides integration bugs
  whose surface is sensitive to merge sequence.
- **Disjoint files_touched.** The plan must guarantee subagents
  touch disjoint file paths. Overlap causes spurious merge conflicts
  and silently lost work.

### When to use

- N independent subtasks whose files_touched are disjoint.
- Wall-clock matters: parallelism cuts elapsed time by ~N.
- You can afford the dispatch overhead (Agent fanout has fixed cost).

### Wave limiting

If N is large, cap concurrency with `max_parallel` (typically 4). The
primary dispatches waves of `max_parallel` subagents, waits for the
wave to complete, then dispatches the next. See `orchestrate-issue`
Phase 5.

## 4. Pattern — pipelined long-running work

Many concurrent batch-jobs against one or more issues, with periodic
heartbeats and result reconciliation as jobs finish. Suitable for
e2e test suites, parallel deploys to multiple environments, or
fan-out builds across many platforms.

### Shape

```
for each environment / platform / target:
   dispatch batch-job (do NOT wait inline)
       └── record { comment_id, target } in a pending-jobs table
loop:
   for each pending job:
       poll its request comment
       if terminal:
            validate summary
            ack
            mark complete in pending-jobs
            record outcome
   call heartbeat() on the parent issue            # throttled
   sleep poll_interval
exit when pending-jobs is empty
```

### When to use

- Many independent jobs that all need to finish before the primary
  agent can proceed.
- Wall-clock dominates over per-job orchestration cost.
- Each job's outcome is independent — no inter-job dependencies.

### Critical rules

- **Heartbeat throttling.** Call `task-dag.heartbeat()` once per poll
  cycle, but the helper itself enforces `heartbeat_min_interval_seconds`.
  Don't write your own loop that pounds the API.
- **Tolerate trailers.** When re-reading comment bodies, use
  `json.JSONDecoder().raw_decode` rather than strict `json.loads` so
  the Claude Code MCP comment trailer doesn't cause spurious parse
  failures.
- **Restart safety.** Persist the pending-jobs table to
  `.agent/runs/<run_id>/state.json` after every state change. A
  restart should resume polling from the saved table, not redispatch.

### Variant: cross-issue pipeline

You can pipeline jobs across multiple issues by keeping per-issue
state in `.agent/runs/<run_id>/issues/<n>/state.json`. The
heartbeat call must target the specific issue that owns each job.

## 5. State management

Three layers of state live in the protocol; know which layer carries
which fact so you don't duplicate or contradict.

### Layer 1 — issue body (`agent-meta`)

Per-issue state owned by `task-dag`:

- `status` — `null` | `working` | `finished` | `abandoned`
- `agent_id` — current owner's identity
- `status_ts` — last heartbeat
- `feature_branch` — the branch this DAG node owns
- `instructions_inline` / `instructions_path` — work brief

Mutate via `mcp__github__issue_write`. Never mutate from inside
`batch-job` — that's `task-dag`'s job.

### Layer 2 — comment envelopes

Per-job state owned by `batch-job`:

- Request envelope (initial comment body): command, args, branch,
  commit_sha, subagent_id.
- Terminal state written by the runner (when the runner edits the
  comment): `run_status`, `summary`, `error_kind`.
- Ack envelope: `kind: "agent-ack"` follow-up comment OR inline edit
  to `agent_ack: "finished"`.

These envelopes form an append-only audit trail. Don't mutate the
comment body after ack.

### Layer 3 — run state (`.agent/runs/<run_id>/state.json`)

Per-run state for fanout / pipelined patterns. Owned by the primary
agent; not part of the wire protocol. Schema is flexible but commonly
includes:

```json
{
  "run_id": "20260514-055717",
  "issue_number": 42,
  "feature_branch": "agent/42-foo",
  "subtasks": [
    {"id": "sub-01", "branch": "agent/42-foo--sub-01",
     "status": "pending|dispatched|merged|failed",
     "request_comment_id": null, "ack_comment_id": null}
  ]
}
```

Commit and push state.json on the feature branch after each update so
a restart picks up exactly where you left off.

### Restart recovery

On restart:

1. Read `state.json` for the run.
2. For each subtask with `request_comment_id != null` and
   `ack_comment_id == null`, re-fetch the comment; if terminal, ack
   and update state.
3. For each subtask with `status == pending`, redispatch.
4. Resume the loop from the earliest incomplete phase.

Never assume a phase succeeded just because the last log line
mentions it. Always reconcile against the on-disk + on-GitHub state.

## 6. Common pitfalls

These are the failure modes seen most often when composing the
primitives. The orchestrator skill internalises avoidance of all of
them; if you compose by hand, watch for each.

| Pitfall | Symptom | Fix |
|---|---|---|
| Merging in completion order | Integration bugs that only appear when sub-02 lands before sub-01 | Always merge in plan order. Persist plan-order in state.json. |
| Single-slash branch separator | Refspec ambiguity, some tools strip the prefix | Use `feature--sub-01`, double-dash. See POC SPEC §6. |
| Dispatching subagents without `isolation: "worktree"` | Concurrent subagents corrupt each other's branches via shared CWD | Always pass `isolation: "worktree"` on Agent calls in fanout |
| Strict JSON parse on comment bodies | Spurious `ParseError` when the MCP trailer is appended | Use `json.JSONDecoder().raw_decode` to tolerate trailing prose |
| Dispatching subagents across multiple messages | Subagents run serially instead of in parallel | Place all Agent calls in **one** message |
| Forgetting to push state.json | Restart starts from scratch instead of resuming | Commit + push state.json after every meaningful state change |
| Calling `heartbeat()` from a hot poll loop | Rate-limit collisions | Use the throttled helper; let it skip if interval not elapsed |
| Writing `status: finished` before the PR opens | Issue closed without a real PR; lock-on-close runs prematurely | Only finalise `agent-meta` after `mcp__github__create_pull_request` returns success |
| Silent merge with `theirs` strategy | Lost edits from earlier subagents | Default `conflict_strategy: "fail"` and surface conflicts to the user |
| Re-using a subagent's branch across runs | Stale commits leak into a new run | Always create sub-branches fresh from the feature-branch tip per run |

## 7. Code snippets

The snippets below are illustrative, not runnable. They use a
pseudo-Python API that matches the shape of the skills' helpers; the
real call signatures are in each skill's SKILL.md.

### 7.1 Linear loop (Pattern 2)

```python
from agent_job import task_dag, batch_job

claimed = task_dag.claim(agent_id=AGENT_ID, agent_login=ME)
if not claimed:
    return {"reason": "no_work"}

issue, meta = claimed["issue"], claimed["meta"]
plan = task_dag.plan(issue_number=issue["number"], agent_login=ME)
brief = plan["brief"]

# Drive the work serially.
for step in derive_steps_from(brief):
    edit_files(step.files)
    sha = git_commit_and_push(meta["feature_branch"])
    result = batch_job.run(
        issue_number=issue["number"],
        command=step.command,
        args=step.args,
        branch=meta["feature_branch"],
        commit_sha=sha,
        subagent_id="primary",
        agent_id=AGENT_ID,
        heartbeat=task_dag.heartbeat_for(issue["number"]),
    )
    assert result["summary"]["status"] == "ok"

pr = mcp_github.create_pull_request(
    base=meta["base_branch"],
    head=meta["feature_branch"],
    title=f"#{issue['number']}: {issue['title']}",
    body=build_pr_body(results),
)
task_dag.finalise(issue["number"], status="finished")
```

### 7.2 Parallel fanout (Pattern 3)

```python
from agent_job import task_dag

claimed = task_dag.claim(agent_id=AGENT_ID, agent_login=ME)
plan = task_dag.plan(issue_number=claimed["issue"]["number"], agent_login=ME)
layout = plan["subagent_layout"]  # list of subtasks with disjoint files_touched

run_id = utc_now_compact()
state = init_state_json(run_id, claimed, layout)
write_and_push_state(state)

# Create sub-branches.
for sub in layout:
    git_create_branch(sub["branch"], from_ref=claimed["meta"]["feature_branch"])

# Dispatch ALL subagents in ONE message; each gets isolation: "worktree".
agent_calls = [
    AgentCall(
        subagent_type="general-purpose",
        isolation="worktree",
        prompt=render_brief(sub, run_id=run_id),
    )
    for sub in layout
]
results = dispatch_in_single_message(agent_calls)   # critical: one message

# Collect, persist, then merge in PLAN order (not completion order).
for sub, result in zip(layout, results):
    update_state(state, sub["id"], result)
write_and_push_state(state)

for sub in layout:                                  # plan order
    if state["subtasks"][sub["id"]]["status"] == "dispatched_ok":
        git_merge(into=claimed["meta"]["feature_branch"],
                  from_=sub["branch"], strategy="fail-on-conflict")
        git_push(claimed["meta"]["feature_branch"])

open_pr_and_finalise(claimed, state)
```

### 7.3 Pipelined long-running jobs (Pattern 4)

```python
from agent_job import task_dag, batch_job

# Fire off all jobs concurrently; do NOT wait inline.
pending = []
for target in TARGETS:
    comment_id = batch_job.submit_only(
        issue_number=ISSUE_N,
        command="deploy",
        args={"target": target},
        branch=BRANCH, commit_sha=SHA,
        subagent_id="primary", agent_id=AGENT_ID,
    )
    pending.append({"comment_id": comment_id, "target": target,
                    "status": "submitted"})

write_state({"run_id": RUN_ID, "pending": pending})

heartbeat = task_dag.heartbeat_for(ISSUE_N)         # throttled internally

while any(p["status"] == "submitted" for p in pending):
    for job in pending:
        if job["status"] != "submitted":
            continue
        envelope = batch_job.peek(job["comment_id"])
        if envelope["run_status"] in TERMINAL_STATES:
            batch_job.validate_and_ack(envelope)
            job["status"] = "complete"
            job["summary"] = envelope["summary"]
    write_state({"run_id": RUN_ID, "pending": pending})
    heartbeat()                                     # throttled
    sleep(POLL_INTERVAL)

reconcile_outcomes(pending)
```

### 7.4 Restart-safe resume (any pattern)

```python
state = read_state_or_none(RUN_ID)
if state is None:
    state = bootstrap_fresh_state()
    write_and_push_state(state)
else:
    # Reconcile: any subtask with request_comment_id but no
    # ack_comment_id may have completed while we were down.
    for sub in state["subtasks"]:
        if sub["request_comment_id"] and not sub["ack_comment_id"]:
            envelope = batch_job.peek(sub["request_comment_id"])
            if envelope["run_status"] in TERMINAL_STATES:
                batch_job.validate_and_ack(envelope)
                sub["ack_comment_id"] = envelope["ack_comment_id"]
                sub["status"] = "dispatched_ok"
    write_and_push_state(state)

# Continue from the earliest incomplete phase.
resume_from_state(state)
```

### 7.5 Tolerant comment-envelope parse

```python
import json

def parse_envelope(body: str) -> dict:
    """Parse a batch-job comment body, tolerating MCP trailer prose."""
    decoder = json.JSONDecoder()
    try:
        obj, _idx = decoder.raw_decode(body.lstrip())
    except json.JSONDecodeError as e:
        raise ParseErrorTerminal(
            f"could not decode envelope prefix: {e}"
        ) from e
    return obj
```

## 8. Cross-references

### Sibling skills in this package

- [`batch-job`](../batch-job/SKILL.md) — one-shot batch-job submission,
  poll, ack. The execution primitive used by Patterns 2-4.
- [`task-dag`](../task-dag/SKILL.md) — claim, plan, merge, schedule
  successors. The ownership primitive used by Patterns 2-3.
- [`orchestrate-issue`](../orchestrate-issue/SKILL.md) — end-to-end
  primary loop. Implements Pattern 3 (parallel fanout) as a single
  invocation.
- [`onboarding`](../onboarding/SKILL.md) — interview-based discovery of
  an existing repo's workflow; recommends how to integrate the
  protocol.

### Protocol-level references

- POC `SPEC.md` §9 — canonical batch-job wire protocol: request
  envelope, terminal states, ack modes, schemas.
- POC `SPEC.md` §10 — canonical task-dag skill spec: claim handshake,
  plan output, merge order, schedule_successors.
- POC `SPEC.md` §6 — branching model and double-dash separator
  convention.
- POC `SPEC.md` §4.1 — issue state machine.
- POC `SPEC.md` §10.4 — restart recovery semantics.

### External patterns

- `software-factory/.claude/skills/parallel-subagent-fanout/SKILL.md` —
  the generic parallel-subagent-fanout pattern. Pattern 3 above is the
  agent-job-protocol-specialised version.
- `software-factory/.claude/skills/subagent-prompting/SKILL.md` —
  9-section subagent brief template used in Phase 5 of fanout.

---

Version: 1.0.0
Protocol-version: 1
Last-synced-from-POC: 2026-05-14
