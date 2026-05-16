# AGENTS.md suggestions from run Vs1aL

Concrete proposals for the maintainer to fold into top-level
`AGENTS.md` (or leave in-place as a reference). Each item has a
copy-paste-ready rule plus a one-line rationale.

1. **Test before you commit (harness sanity).**
   Rule: `Before committing changes under test-harness/lib/, test-harness/runners/, .claude/skills/, or .agent/, sweep all 18 scenarios with python3 test-harness/runners/<id>.py and confirm exit 0 for each.`
   Rationale: a single broken import in the shared lib breaks every runner. The harness CI catches this in PR, but pre-commit feedback is faster.

2. **Don't re-bundle test-harness/lib/ from this repo back into the POC.**
   Rule: `test-harness/lib/ in pipeline-ai-sandbox is editable here, but every change must round-trip through the POC repo's pipeline-skills-package/test-harness/lib/ before it can be re-bundled.`
   Rationale: the lib is part of the source-of-truth bundle. Editing it here without round-tripping diverges the bundle from the rebuild script's output.

3. **Always set degraded_reason on synthetic-mode degradation.**
   Rule: `Any scenario runner that detects it cannot run with the requested target must record a degraded_reason string in state.diagnostics before continuing under a fallback target.`
   Rationale: the test-results.md aggregator distinguishes "skipped because the runner chose to" from "skipped because a key is unobservable in synthetic mode". Without degraded_reason, future runs can't tell why a scenario didn't run live.

4. **Open issues via mcp__github__issue_write, not via shell hacks.**
   Rule: `Issue and PR creation goes through the GitHub MCP tools (issue_write, create_pull_request). Do not call gh / curl / git via Bash for these operations - the MCP enforces the repo scope.`
   Rationale: writing through Bash bypasses the scope enforcement and may silently target the wrong repo.

5. **Don't push to `main` directly.**
   Rule: `Every change reaches main via a PR. Direct pushes to main are forbidden. PRs are draft until the run is fully complete.`
   Rationale: this is the protocol's PR-gated workflow. Skipping the gate undermines lock-and-sweep and close-on-merge.

6. **Don't modify bootstrap-installed files.**
   Rule: `Files under docs/, bootstrap/, test-harness/{SKILL,SPEC,archetypes,scenarios}/, and .claude/skills/ are bootstrap-installed and must round-trip through the POC. PRs against this repo that change those files require explicit user approval and a note in the retrospective.`
   Rationale: these files are the source-of-truth bundle. Out-of-band edits will be overwritten on the next bundle rebuild.

7. **Restart-safety check before every long phase.**
   Rule: `Before starting any phase that runs > 5 minutes, write state.json with status: in_progress. After the phase completes, update status to done and persist again.`
   Rationale: a session can be reclaimed at any moment. Without this, restart resumes from too-early a checkpoint and re-does work.

8. **Use isolation: "worktree" for parallel subagents whose writes can collide.**
   Rule: `If two parallel subagents could write to overlapping paths or commit overlapping diffs, dispatch them with isolation: "worktree". If their write scopes are obviously disjoint, no isolation is fine.`
   Rationale: worktree isolation costs time (clone + merge); use it where it matters.

9. **Honour the agent-meta block on issues.**
   Rule: `Issues with an "agent-task" label must contain a fenced agent-meta block matching .agent/schemas/issue-body.schema.json. Issues without are not picked up by orchestrate-issue.`
   Rationale: the schema is the protocol's contract.

10. **Generate, don't copy.**
    Rule: `When N artifacts are mechanically derived from a single source (e.g. 18 runners from 18 scenario YAMLs), check in a small generator script and a generation marker. Re-running the generator is the canonical way to update the artifacts.`
    Rationale: keeping 18 hand-edited near-duplicates in sync rots fast.

11. **Skip < failure when the test can't be run.**
    Rule: `If a phase can't be evaluated under the current target (missing dependency, missing scope, missing data), raise NotImplementedError with a short reason. The runner marks the phase as skipped; the report distinguishes skipped from failed.`
    Rationale: false-failures pollute the signal. Skip is honest.

12. **Don't leave dispatcher state on the wrong branch.**
    Rule: `Dispatcher state (runs/<run_id>/state.json) is committed to the working feature branch. Per-scenario harness state (harness/runs/<run_id>/<scenario_id>/state.json) is NOT committed - it is gitignored.`
    Rationale: scenario state files are reproducible from the runners; committing them clutters PRs and creates merge conflicts on every re-run.
