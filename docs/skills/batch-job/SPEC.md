# SPEC — batch-job skill

Status: design-stage
Audience: implementers of the skill in the new `pipeline-ai-sandbox` repo

## Purpose

Submit one batch job from an active issue, poll until the workflow
runner reports a terminal status, validate the summary, and
acknowledge the result. The skill is the agent-side primitive for
running any command registered in `.agent/config.json :: commands`
against a GitHub Actions runner.

This skill is a pure execution primitive. It does not claim issues,
plan subagents, or open PRs — those belong to `task-dag` and
`orchestrate-issue`.

## Trigger conditions

The skill matches when an agent is asked to:

- "Run tests on branch X for issue Y"
- "Submit a batch job for command Z"
- "Dispatch one job against issue N"
- "Use the batch-job skill"

It does **not** match general "run tests" requests outside the
GitHub-native protocol (a local pytest is not a batch job).

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

On success:

```json
{
  "envelope": { "...": "terminal batch-job-request comment body..." },
  "summary": { "...": "inline summary field from envelope..." },
  "summary_json": { "...": "fetched from _agent_runs/runs/<n>/<cid>/summary.json..." },
  "ack_comment_id": 1234567890,
  "log_manifest_path": "runs/42/9876/manifest.json"
}
```

On failure (timeouts, branch_sha_mismatch, parse_error, summary_schema_violation):

- Raise a typed exception that the caller can match: `RunnerPickupTimeoutError`, `RunningTimeoutError`, `BranchShaMismatchError`, `ParseErrorTerminal`, `SummarySchemaViolation`.
- Each exception carries the comment id, run_status, error_kind, and any partial summary content.

## Procedure

The protocol's §9 in `SPEC.md` (POC root) is the canonical procedure.
This skill packages it as follows:

1. **Pre-flight.** Read the issue via the GitHub MCP. Assert `agent-task` label present, body parses as `agent-meta`, caller's `agent_id` matches.
2. **Submit.** Post the request envelope as a new comment via `mcp__github__add_issue_comment`. Capture the returned comment id. Tolerate trailing prose (Claude Code MCP trailer) when re-reading the body.
3. **Poll.** Read the comment at the schedule defined in `.agent/config.json :: comment.poll_*`. On each cycle, invoke the optional `heartbeat()` callable.
4. **Deadlines.** If `run_status == null` past `runner_pickup_timeout_seconds`, raise `RunnerPickupTimeoutError`. If `run_status == "running"` past `running_timeout_seconds`, raise `RunningTimeoutError`. In either case open a `runner-failure` issue first so the operator has audit material.
5. **Terminal.** When `run_status` is terminal, fetch `summary.json` from `_agent_runs` via `mcp__github__get_file_contents`. Validate against the command's `summary_completed` or `summary_error` schema.
6. **Ack.** Per `ack_mode`:
   - `follow_up` (default): post a `kind: "agent-ack"` comment whose `ack_for` matches the request comment id.
   - `inline`: edit the request comment to set `agent_ack: "finished"` and `agent_acked_at`.
7. **Return** the result dict above.

## Self-install logic

On invocation, the skill checks for the presence of:

| File or path | Action if missing |
|---|---|
| `.agent/config.json` | Copy from `templates/agent/config.json` |
| `.agent/scripts/common.py` | Copy from `templates/agent/scripts/common.py` |
| `.agent/scripts/rest_client.py` | Copy from `templates/agent/scripts/rest_client.py` |
| `.agent/scripts/handler.py` | Copy from `templates/agent/scripts/handler.py` |
| `.agent/scripts/agent_lib/` | Copy directory from `templates/agent/scripts/agent_lib/` |
| `.agent/schemas/comment-envelope.schema.json` | Copy from `templates/agent/schemas/` |
| `.agent/schemas/comment-ack-envelope.schema.json` | Copy from `templates/agent/schemas/` |
| `.agent/schemas/log-manifest.schema.json` | Copy from `templates/agent/schemas/` |
| `.agent/schemas/commands/` (directory) | Copy entire directory |
| `.github/workflows/batch-job-handler.yml` | Copy from `templates/github/workflows/` |
| `agent-task` label on the GitHub repo | Create via `mcp__github__` (no schema match — REST POST) |

If `.agent/config.json` exists with a different `protocol_version`, the
skill refuses to overwrite and prompts the user. It does **not**
silently upgrade.

If a workflow YAML exists at the target path with content different
from the bundled template, the skill shows a diff and asks the user
how to proceed (overwrite, skip, write to `.new` for manual merge).

After install, the skill informs the user that onboarding has not been
run and offers to invoke the `onboarding` skill. Decline is fine —
this skill works standalone.

## Bundled templates

The skill's `templates/` directory contains byte-identical copies of
the POC's working source:

```
templates/
  agent/
    config.json                        # from .agent/config.json
    scripts/
      common.py                        # from .agent/scripts/common.py
      rest_client.py
      handler.py
      requirements.txt
      agent_lib/                       # entire directory
    schemas/
      comment-envelope.schema.json
      comment-ack-envelope.schema.json
      log-manifest.schema.json
      issue-body.schema.json
      commands/                        # entire directory
    commands/                          # entire directory
  github/
    workflows/
      batch-job-handler.yml
```

A contract test in this POC (`tests/distribution/test_template_parity.py`)
asserts byte-equivalence between each `templates/<path>` and the
corresponding POC source file.

## SKILL.md frontmatter

```yaml
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
```

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
| Running timeout | Poll loop | Same as above |
| Branch SHA mismatch (terminal) | Runner-written envelope | Raise `BranchShaMismatchError` |
| Parse error (terminal) | Runner-written envelope | Raise `ParseErrorTerminal` |
| Summary schema violation (terminal) | Runner-written envelope | Raise `SummarySchemaViolation` |
| Ack write fails | MCP error | Retry with backoff; emit warning if persistent |

## Tests

### In this POC (partial)

- **Contract test** (`tests/distribution/test_template_parity.py`): verify each bundled template byte-matches the POC source.
- **Schema validity** (`tests/distribution/test_schema_validity.py`): each bundled schema is valid JSON Schema draft 2020-12.
- **Dry-run install**: mock filesystem; assert the skill's install logic identifies the right files to copy.
- **SKILL.md frontmatter validity**: parse YAML, assert required keys present.

### In the new repo (full)

- Reuse the POC's existing `tests/unit/test_skill_batch_job.py` as the baseline.
- Add real-GitHub e2e tests driven by the test harness: dispatch the skill against synthetic archetypes; verify ack arrives, summary validates, log manifest is fetchable.
- Cover all `ack_mode` paths (inline + follow_up).
- Cover all failure-mode exceptions against deliberately broken inputs.

## Anti-patterns

- **Do not** modify `agent-meta` from inside this skill. That is `task-dag`'s job.
- **Do not** open PRs from this skill. PR creation belongs to `orchestrate-issue` or the caller.
- **Do not** retry a `branch_sha_mismatch` with the same branch+SHA — surface the error to the caller.
- **Do not** silently upgrade `.agent/config.json` to a newer `protocol_version`.

## Dependencies

- **None** at the skill level. `batch-job` is self-contained and self-installs all required templates.
- At runtime, depends on a GitHub MCP server reachable from the agent.
