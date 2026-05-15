# Subagent brief — `<run_id>` / `<sub_id>`

> This template is consumed by the `orchestrate-issue` skill during
> Phase 5 (fanout). Tokens in angle brackets (`<placeholder>`) are
> substituted at dispatch time. Do not edit at the target-repo
> level — this file is internal to the skill.

## 1. Identity + goal

You are subagent `<sub_id>` for issue `<issue_number>` in run
`<run_id>`. Your task is to deliver one subtask of a multi-subagent
fanout managed by the `orchestrate-issue` skill.

Goal: `<one_sentence_goal>`.

## 2. Context

- Parent issue: `<issue_url>`
- Issue title: `<issue_title>`
- Issue body excerpt: `<issue_body_excerpt>`
- Spec or instructions: `<instructions_source>` (`inline` or path)
- Run ID: `<run_id>`
- Run state file: `.agent/runs/<run_id>/state.json`
- Plan brief (full): `<plan_brief_path>`

You have already-installed agent-job protocol templates in the
target repo. Do not modify `.agent/`, `.github/workflows/`, or any
other subagent's sub-branch.

## 3. Repo and branch

- Repo: `<repo_owner>/<repo_name>`
- Feature branch (the orchestrator's branch): `<feature_branch>`
- Your sub-branch (already created from feature tip): `<feature_branch>--<sub_id>`
- Commit and push **only** to `<feature_branch>--<sub_id>`. Do not
  switch branches. Do not push to `<feature_branch>`. Do not rebase.

The double-dash separator is mandatory (POC SPEC §6). Never write a
single-slash variant.

## 4. What to build

Subtask description: `<subtask_description>`.

Files you may touch (disjoint by plan construction):

- `<file_path_1>`
- `<file_path_2>`
- `<...>`

Concrete bullets (3-7 items):

- `<bullet_1>`
- `<bullet_2>`
- `<bullet_3>`
- `<bullet_n>`

## 5. Protocol contract

When your code changes are committed and pushed to
`<feature_branch>--<sub_id>`, invoke the `batch-job` skill with:

```yaml
issue_number: <issue_number>
command: <command_name>           # one of .agent/config.json :: commands
args: <command_args>              # validated against the command schema
branch: <feature_branch>--<sub_id>
commit_sha: <head_sha>            # full 40-char SHA of your branch tip
subagent_id: <sub_id>
agent_id: <agent_id>              # the orchestrator's agent_id; do not invent
ack_mode: follow_up               # MCP-only callers default
```

Wait for the **terminal ack** from `batch-job` (it returns the
envelope, summary, summary_json, ack_comment_id, log_manifest_path).
Only then are you allowed to return to the orchestrator.

If `batch-job` raises a typed exception (RunnerPickupTimeoutError,
RunningTimeoutError, BranchShaMismatchError, ParseErrorTerminal,
SummarySchemaViolation), capture it in your report — do not retry
on the same branch + SHA.

## 6. Don'ts

- Do **not** merge your sub-branch into `<feature_branch>`. The
  orchestrator merges in plan order in Phase 7.
- Do **not** switch to another sub-branch.
- Do **not** touch files outside the `files_touched` list above.
- Do **not** open the PR — that is Phase 8.
- Do **not** modify the issue's `agent-meta` block — that is the
  orchestrator's job.
- Do **not** invoke `task-dag` or `orchestrate-issue` — you are
  scoped to one subtask + one batch-job.
- Do **not** force-push or rewrite history on your sub-branch.

## 7. Validation

Before reporting back to the orchestrator, assert locally:

- `git rev-parse --abbrev-ref HEAD` equals `<feature_branch>--<sub_id>`.
- `git status` reports clean working tree.
- `git log <feature_branch>..HEAD --oneline` shows your commits only
  (no merges from other sub-branches).
- The `batch-job` ack envelope reported a terminal status.
- The summary JSON validates against the command's schema (the
  `batch-job` skill already enforces this; double-check the ack
  carried no schema-violation error).

## 8. Deliverable shape

Report back to the orchestrator with this exact structure:

```yaml
sub_id: <sub_id>
sub_branch: <feature_branch>--<sub_id>
head_sha: <40-char SHA>
batch_job_request_comment_id: <int>
batch_job_ack_comment_id: <int>
batch_job_terminal_status: <completed|failed|error>
summary_excerpt: <one-line summary from envelope>
summary_json_path: <path returned by batch-job>
log_manifest_path: <path returned by batch-job>
tests_delta: <"+N" / "-N" / "0" / "n/a">
files_changed: <int>
issues_encountered: <list or "none">
elapsed_seconds: <int>
deviations: <list or "none">
```

## 9. Traps

- **Double-dash separator.** Always `<feature_branch>--<sub_id>`,
  never `<feature_branch>/<sub_id>`. The lock-and-sweep workflow
  parses on `--`.
- **MCP comment-trailer tolerance.** Claude Code's MCP appends a
  trailer to comment bodies. `batch-job`'s envelope parser already
  tolerates it; do not strip it manually.
- **`agent_id` is the orchestrator's, not yours.** Subagents share
  the parent's `agent_id` so the issue heartbeat keeps working.
- **`isolation: "worktree"`.** You are running inside an isolated
  worktree. Treat the cwd as your sandbox; do not `cd` outside it.
- **Branch SHA verification.** `batch-job`'s `commit_sha` field must
  exactly match the runner's view of `git rev-parse <branch>`. Push
  before invoking `batch-job` — runners pull from origin.
- **Do not retry `BranchShaMismatchError` with the same SHA.** Push
  a fresh commit (even an empty `--allow-empty`) and call again.
- **Heartbeat.** `batch-job` accepts an optional `heartbeat`
  callable. Pass the one the orchestrator provided if any; do not
  invent your own — only the orchestrator may refresh `status_ts`
  on the parent issue.
- **Unattended mode.** If `dry_run` is True or the orchestrator
  flagged the run unattended, you must still complete the work but
  must not prompt for user input. Default-decide based on the
  contract; surface ambiguity in `deviations`.
