# test-results.md - run Vs1aL

Run id: `Vs1aL`  
Working branch: `claude/execute-repo-plan-Vs1aL`  
Scenarios driven: 18

## Summary

| Outcome | Count |
|---|---|
| full_pass | 1 |
| partial_pass | 4 |
| fully_skipped | 13 |
| failed | 0 |

Phase-level counts:

| Status | Count |
|---|---|
| skipped | 66 |
| done | 6 |

## Environment constraint

All 18 scenarios declared `target: live-new-repo` (or default-live). In this dispatcher's environment the GitHub MCP scope is restricted to the current repo `lago-morph/pipeline-ai-sandbox`, so `mcp__github__create_repository` cannot mint fresh per-scenario test repos. Runners detected the constraint at archetype-materialise time and recorded `degraded_reason` in their `state.json :: diagnostics`, then ran the scenario against a synthetic fixture instead.

Consequence: every phase whose `expected` block references a key requiring real skill execution (e.g. `repo_created`, `batch_job_comment_present`, `envelope_run_status`, `pr_merged`, `subagents_dispatched`) is marked `skipped` with `requires-live-skill-execution` and the offending keys listed. Phases whose `expected` block is fully answerable from the materialised fixture (e.g. `agents_md_present`, `protocol_installed`, `frontmatter_parses`) ran their assertions.

## Per-scenario detail

| Scenario | Outcome | Phases done / skipped / failed | Degraded |
|---|---|---|---|
| `batch-job-branch-sha-mismatch` | fully_skipped | 0 / 3 / 0 | yes |
| `batch-job-happy-path` | fully_skipped | 0 / 3 / 0 | yes |
| `batch-job-parse-error` | fully_skipped | 0 / 3 / 0 | yes |
| `batch-job-runner-pickup-timeout` | fully_skipped | 0 / 3 / 0 | yes |
| `composition-guide-render` | full_pass | 2 / 0 / 0 | yes |
| `multi-scenario-soak` | fully_skipped | 0 / 4 / 0 | yes |
| `onboarding-blank-repo` | partial_pass | 1 / 4 / 0 | yes |
| `onboarding-decline` | partial_pass | 1 / 2 / 0 | yes |
| `onboarding-existing-agents-md` | partial_pass | 1 / 4 / 0 | yes |
| `onboarding-resume-mid-interview` | fully_skipped | 0 / 5 / 0 | yes |
| `onboarding-revise` | fully_skipped | 0 / 6 / 0 | yes |
| `orchestrate-issue-parallel-fanout` | fully_skipped | 0 / 5 / 0 | yes |
| `orchestrate-issue-restart-recovery` | fully_skipped | 0 / 5 / 0 | yes |
| `orchestrate-issue-single-subagent` | fully_skipped | 0 / 5 / 0 | yes |
| `protocol-installed-not-onboarded` | partial_pass | 1 / 4 / 0 | yes |
| `task-dag-claim-and-plan` | fully_skipped | 0 / 4 / 0 | yes |
| `task-dag-merge-conflicts` | fully_skipped | 0 / 3 / 0 | yes |
| `task-dag-stale-takeover` | fully_skipped | 0 / 3 / 0 | yes |

## What would change with live MCP

If the dispatcher MCP scope included `mcp__github__create_repository` and the bundled skills' POC-side helpers ran as Python in-process, the runners would:

1. Phase `setup` would create `lago-morph/<run_id>-<scenario_id>` (or under the agent's personal account), push the archetype tree via `mcp__github__push_files`, open an `agent-task` issue.
2. Phase `invoke` would call the skill under test (`batch-job` / `task-dag` / `orchestrate-issue` / `onboarding` / `composition-guide`) via its Python lib helpers, pointing at the live repo.
3. Phase `verify` would re-read the live repo / issue / comments / PRs via `mcp__github__*` and assert against the YAML's `expected` block.

The harness's restart-safety guarantees that re-running a scenario picks up from the earliest pending or in_progress phase, so a partial-live run can be resumed under a less-restricted MCP scope without losing the synthetic-mode signal already captured.

## Failures

No scenarios failed in this run.
