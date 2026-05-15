---
name: batch-job
description: |
  Submit one batch job from an active GitHub issue using the agent-job
  protocol; poll for terminal status; ack the result. Use when an agent
  needs to run a workflow command (tests, build, deploy) inside a GitHub
  Actions runner without holding secrets locally. Self-installs templates
  on first invocation if .agent/config.json is missing.
allowed-tools:
  - Bash
  - Read
  - Write
  - Edit
  - mcp__github__issue_read
  - mcp__github__add_issue_comment
  - mcp__github__get_file_contents
---

# batch-job

Submit a single batch job from an active GitHub issue, poll until the
workflow runner reports a terminal status, validate the summary, and
acknowledge the result. This skill is the agent-side primitive for
running any command registered in `.agent/config.json :: commands`
against a GitHub Actions runner.

This skill is a pure execution primitive. It does **not** claim issues,
plan subagents, or open pull requests — those belong to `task-dag` and
`orchestrate-issue`.

## When this skill triggers

Invoke this skill when an agent is asked to do any of the following:

- "Run tests on branch X for issue Y."
- "Submit a batch job for command Z."
- "Dispatch one job against issue N."
- "Use the batch-job skill."

It does **not** trigger on general "run tests" requests outside the
GitHub-native protocol. A local `pytest` invocation is not a batch job.

## Inputs

| Field | Type | Required | Notes |
|---|---|---|---|
| `issue_number` | int | yes | Must be an open issue with `agent-task` label and a valid `agent-meta` block |
| `command` | string | yes | Must appear in `.agent/config.json :: commands` |
| `args` | object | yes | Validated against `.agent/schemas/commands/<command>.schema.json` before submission |
| `branch` | string | yes | Must already exist on origin |
| `commit_sha` | string | yes | Full 40-char SHA; verified by the runner |
| `subagent_id` | string | yes | Identifier of the calling agent |
| `agent_id` | string | yes | The primary's process-level identity; must match the issue's `agent-meta.agent_id` |
| `ack_mode` | enum | no | `"follow_up"` (default for MCP-only callers) or `"inline"` (for REST-credentialed callers) |
| `heartbeat` | callable | no | Invoked once per poll cycle so the caller can refresh `status_ts` on the parent issue |

## Outputs

On success, the skill returns:

```json
{
  "envelope": { "...": "terminal batch-job-request comment body..." },
  "summary": { "...": "inline summary field from envelope..." },
  "summary_json": { "...": "fetched from _agent_runs/runs/<n>/<cid>/summary.json..." },
  "ack_comment_id": 1234567890,
  "log_manifest_path": "runs/42/9876/manifest.json"
}
```

On failure, the skill raises a typed exception that the caller can
match against:

- `RunnerPickupTimeoutError`
- `RunningTimeoutError`
- `BranchShaMismatchError`
- `ParseErrorTerminal`
- `SummarySchemaViolation`

Each exception carries the comment id, `run_status`, `error_kind`, and
any partial summary content available at the time of failure.

## Procedure

The protocol's §9 in the POC `SPEC.md` is the canonical procedure. This
skill packages it into seven steps:

1. **Pre-flight.** Read the issue via the GitHub MCP
   (`mcp__github__issue_read`). Assert the `agent-task` label is
   present, the body parses as a valid `agent-meta` block, and the
   caller's `agent_id` matches the issue's `agent-meta.agent_id`.
2. **Submit.** Post the request envelope as a new comment via
   `mcp__github__add_issue_comment`. Capture the returned comment id.
   Tolerate trailing prose (the Claude Code MCP trailer) when
   re-reading the body — the MCP may HTML-escape body content and
   append a prose trailer; both must be stripped before envelope parse.
3. **Poll.** Read the comment at the schedule defined in
   `.agent/config.json :: comment.poll_*`. On each cycle, invoke the
   optional `heartbeat()` callable so the caller can refresh
   `status_ts` on the parent issue while waiting.
4. **Deadlines.** If `run_status == null` past
   `comment.runner_pickup_timeout_seconds`, open a `runner-failure`
   issue first (so the operator has audit material), then raise
   `RunnerPickupTimeoutError`. If `run_status == "running"` past
   `comment.running_timeout_seconds`, do the same and raise
   `RunningTimeoutError`.
5. **Terminal.** When `run_status` is terminal (`completed`, `error`,
   or `parse_error`), fetch `summary.json` from `_agent_runs` via
   `mcp__github__get_file_contents`. Validate against the command's
   `summary_completed` or `summary_error` schema (defense in depth).
6. **Ack.** Per `ack_mode`:
   - `follow_up` (default): post a `kind: "agent-ack"` comment whose
     `ack_for` matches the request comment id. The original request
     comment is not modified.
   - `inline`: edit the request comment to set `agent_ack: "finished"`
     and `agent_acked_at`. This is the only write the agent makes to
     the comment.
7. **Return** the result dict shown above.

## Self-install logic

A repo is "installed" for this protocol when `.agent/config.json`
exists. The presence of that file is the install marker.

On invocation, this skill checks for each of the following paths in
the target repo and copies the matching template if missing:

| Target path | Bundled template |
|---|---|
| `.agent/config.json` | `templates/agent/config.json` |
| `.agent/scripts/common.py` | `templates/agent/scripts/common.py` |
| `.agent/scripts/rest_client.py` | `templates/agent/scripts/rest_client.py` |
| `.agent/scripts/handler.py` | `templates/agent/scripts/handler.py` |
| `.agent/scripts/requirements.txt` | `templates/agent/scripts/requirements.txt` |
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
| `agent-task` label on the GitHub repo | Created via `mcp__github__` (no schema; REST POST) |

**Install marker.** `.agent/config.json` is the canonical marker. If
the file is present, the skill considers the protocol installed and
proceeds to step 1 of the procedure. If absent, the skill performs the
copy table above before proceeding.

**Conflict handling.** If a target file exists at a path the skill
wants to install:

1. If content is byte-identical to the bundled template — no-op.
2. If content differs — compute a diff and show it to the user; ask
   "overwrite, skip, or write to `<path>.new` for manual merge?"
3. If the user selects skip, record the skip in
   `.agent/installs/batch-job.log` and proceed.

If `.agent/config.json` exists with a different `protocol_version`, the
skill refuses to overwrite and prompts the user. It does **not**
silently upgrade.

After install, the skill checks for an onboarding dialog file on the
well-known `agent-job-protocol/onboarding` branch. If absent, it emits
the one-time message offering to invoke the `onboarding` skill. Decline
is fine — this skill works standalone.

## Failure modes

| Failure | Detection | Handling |
|---|---|---|
| Issue not found | MCP returns 404 | Raise `IssueNotFoundError` |
| Issue lacks `agent-task` label | Pre-flight check | Raise `PreflightFailedError`, suggest onboarding |
| Body lacks `agent-meta` | Pre-flight check | Raise `PreflightFailedError` |
| `agent_id` mismatch | Pre-flight check | Raise `AgentIdMismatchError`, do not submit |
| Args fail schema | Pre-submit check | Raise `InvalidArgsError` with schema error |
| Comment post fails | MCP error | Retry with backoff; raise after 3 attempts |
| Runner-pickup timeout | Poll loop | Open `runner-failure` issue; raise `RunnerPickupTimeoutError` |
| Running timeout | Poll loop | Open `runner-failure` issue; raise `RunningTimeoutError` |
| Branch SHA mismatch (terminal) | Runner-written envelope | Raise `BranchShaMismatchError` |
| Parse error (terminal) | Runner-written envelope | Raise `ParseErrorTerminal` |
| Summary schema violation (terminal) | Runner-written envelope | Raise `SummarySchemaViolation` |
| Ack write fails | MCP error | Retry with backoff; emit warning if persistent |
| MCP HTML-escapes comment body | Re-read of own comment | Decode entities before envelope parse; tolerate Claude Code MCP prose trailer |

## Anti-patterns

- **Do not** modify `agent-meta` from inside this skill. That is
  `task-dag`'s job.
- **Do not** open pull requests from this skill. PR creation belongs to
  `orchestrate-issue` or the caller.
- **Do not** retry a `branch_sha_mismatch` with the same branch + SHA —
  surface the error to the caller.
- **Do not** silently upgrade `.agent/config.json` to a newer
  `protocol_version`. Refuse and prompt the user.
- **Do not** call other skills via the Skill tool from inside this
  skill. If composition is needed, the caller (`orchestrate-issue`)
  imports this skill's `lib/` helpers directly.

---
Version: 1.0.0
Protocol-version: 1
Last-synced-from-POC: 2026-05-14
---
