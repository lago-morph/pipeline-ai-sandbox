# CLAUDE.md

Read [`AGENTS.md`](AGENTS.md) first. This file adds Claude-Code-specific
notes on top of the shared agent guidance.

## Available skills

Installed at `.claude/skills/` (project-level scope):

- `batch-job` — submit one batch job, poll for terminal status, ack
- `task-dag` — claim issue, plan subagents, merge sub-branches
- `orchestrate-issue` — end-to-end primary-agent loop (claim → plan →
  fan out → batch-job → merge → PR)
- `onboarding` — interview-based adoption of the protocol in a repo
- `composition-guide` — docs-only reference for composing the four
  implementation skills above

Plus the development-only `test-harness/` skill (not in `.claude/skills/`;
lives at the repo top level under `test-harness/`).

Each of the 5 distributable skills self-installs its templates on first
invocation if `.agent/config.json` is absent.

## Parallel fanout

Per [`NEW-REPO-PLAN.md`](NEW-REPO-PLAN.md), parallel subagent fanout
uses the `Agent` tool with `isolation: "worktree"`. Dispatch all
subagents in a wave in a single message; collect results before
dispatching the next wave. Default `MAX_PARALLEL=4`.

## MCP scope

When using `mcp__github__*` tools, the scope is the current repo
(`pipeline-ai-sandbox` under the agent's own GitHub login). The
harness's `live-new-repo` scenarios create fresh temporary repos under
that same login; never reuse an existing repo for a scenario.

## PR defaults

Open PRs as **draft** by default. Promote to ready-for-review only
after the relevant test-harness scenarios are green.

## Commit message style

- Imperative mood ("add archetype manifest", not "added" or "adds").
- Lowercase first character.
- No trailing period.
- Subject line under 72 characters.
- Body (optional) wraps at 72 characters and explains the why, not the
  what.
