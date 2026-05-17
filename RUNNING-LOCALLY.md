# RUNNING-LOCALLY.md

How to run the test harness from a local clone — both the unit suite
and the live-target scenarios.

Audience: someone with a Linux workstation, a GitHub account that
has write access to `lago-morph/pipeline-ai-sandbox`, and the
Claude Code CLI installed.

## 1. Clone and bootstrap

```bash
git clone git@github.com:lago-morph/pipeline-ai-sandbox.git
cd pipeline-ai-sandbox
```

The harness uses Python 3.11+. Install dev dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
```

That installs `pytest`, `pyyaml`, `jsonschema`, `requests`, and
`ruff` — everything the harness needs.

## 2. Run the unit suite

```bash
python -m pytest test-harness/tests
```

The suite covers every module under `test-harness/lib/` plus the
runners' smoke paths against an in-memory GitHub client. No network
is touched; the suite runs in well under 2 seconds.

Run a single observer's tests:

```bash
python -m pytest test-harness/tests/test_live_observe.py -v
python -m pytest test-harness/tests/test_orchestrate_observe.py -v
```

## 3. Run a scenario runner in synthetic mode (default)

Each `test-harness/runners/<scenario>.py` is invokable directly:

```bash
python test-harness/runners/batch-job-happy-path.py --run-id smoke-1
```

With no credentials in the environment, every phase that requires
live skill execution is marked `skipped` with reason
`requires-live-skill-execution`. Exit code is 0 (skips are not
failures).

Per-scenario state lives at `harness/runs/<run_id>/<scenario>/`. The
`fixture/` subdir is the materialised archetype; `state.json` is
the per-phase log.

## 4. Run a scenario live against real GitHub

Live-target scenarios drive an issue + comments + branches + a PR
against a real GitHub repo. The current set with live observers:

- `batch-job-happy-path` (PR #5)
- `orchestrate-issue-single-subagent` (PR #12)
- `orchestrate-issue-parallel-fanout` (PR #13)
- `task-dag-claim-and-plan` (PR #14)
- `orchestrate-issue-restart-recovery` (PR #15)

### 4.1 Authenticate

Get a personal access token (PAT) with the `repo` scope. Easiest
path is `gh auth login` if you have the GitHub CLI installed:

```bash
gh auth login
gh auth token  # prints the token to stdout
```

Export it for the harness to find:

```bash
export GITHUB_TOKEN="$(gh auth token)"
# or, if you prefer:
export GH_TOKEN="..."
```

Either env var works; the harness checks both.

### 4.2 Point the harness at a repo

Set the `owner/repo` slug. The default if you run from inside a
clone is the `origin` remote's GitHub URL, so usually nothing extra
is needed:

```bash
export GITHUB_REPOSITORY="lago-morph/pipeline-ai-sandbox"
```

Or run from inside the clone and let the harness resolve `origin`.

Optional: pin the comment-author the workflow expects:

```bash
export AGENT_LOGIN="$(gh api user --jq .login)"
```

If unset, the workflows' `author_association` gate covers anyone
with repo write access (see `AGENTS.md` §6.3). Setting it just
narrows the audit trail.

### 4.3 Drive the scenario

```bash
python test-harness/runners/batch-job-happy-path.py \
    --run-id local-$(date +%s) \
    --target live-new-repo
```

The runner:

1. Materialises the archetype.
2. Resolves the live GitHub client from the env (`GITHUB_TOKEN` +
   `GITHUB_REPOSITORY`).
3. Constructs the live observer.
4. Drives the scenario's phases. Polling intervals are 5 seconds
   by default; full scenarios complete in 1-3 minutes depending on
   workflow latency.

State and diagnostics land in
`harness/runs/<run_id>/<scenario>/state.json`. If credentials are
missing, the runner falls back to synthetic-fixture and records
`degraded_reason` in the state's `diagnostics` block (so failures
are honest, not silent).

## 5. Quick reference: env vars

| Var | Purpose | Default |
|---|---|---|
| `GITHUB_TOKEN` (or `GH_TOKEN`) | PAT with repo scope | none — required for live |
| `GITHUB_REPOSITORY` | `owner/repo` slug | resolved from `origin` |
| `AGENT_LOGIN` | comment author the workflow gates on | `agent_login=agent` (workflow falls back to author_association) |
| `HARNESS_RUN_ID` | shared run-id across multiple runner invocations | per-invocation timestamp |

## 6. Forensics on a failed live run

When a scenario fails, the harness intentionally leaves the
issue / branches / PR intact for inspection. Find the artifacts:

- `harness/runs/<run_id>/<scenario>/state.json` — last phase status +
  diagnostics.
- The created issue on GitHub — search for the run id in the title or
  the body's `agent-meta` block.
- The feature branch (`agent/...`) and its sub-branches
  (`agent/...--sub-NN`).
- Any PR opened by the orchestrate observer.

Clean up after diagnosing:

```bash
# Close the issue (no-op if already closed by close-on-merge):
gh issue close <number>

# Delete leftover branches:
gh api repos/lago-morph/pipeline-ai-sandbox/git/refs/heads/<branch> -X DELETE
```

## 7. Running under Claude Code

The same harness is what Claude Code uses when driving the protocol
end-to-end. The CLI exposes the runners via the same shell-out path
this doc describes. Setting `GITHUB_TOKEN` in the Claude Code env is
not necessary inside the managed remote-execution environment — the
agent's GitHub MCP tools cover the same operations. The runners are
available for human runs and CI runs against the same logic.

## 8. CI runs

This repo's only CI is the protocol-runtime workflows
(`lock-and-sweep.yml`, `batch-job-handler.yml`,
`close-on-merge.yml`). There is no PR-time test runner — the unit
suite runs locally and in PR diffs by human inspection. If you want
PR-time test enforcement, ask the maintainer first (see the
`ask-before-adding-cicd` skill).
