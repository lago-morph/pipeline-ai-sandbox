# k8-platform — Pipeline-AI-Sandbox Skill Compatibility & Workflow Refactor Report

**Date:** 2026-05-17
**Author repo:** `lago-morph/pipeline-ai-sandbox`
**Target repo:** `lago-morph/k8-platform`
**Source of truth for target state:** `summary/status-2026-05-17.md`,
`summary/functionality-2026-05-17.md`, `summary/run-log-2026-05-17.md`
(commit `c125c21` on `main`).

This report assesses how the skills authored in `pipeline-ai-sandbox`
fit into `k8-platform`, what decisions the maintainer needs to make
before adopting them, what risks adoption carries, and how the existing
`terraform-test.yml` workflow should be refactored to take advantage of
the new capabilities.

---

## 1. Context

### 1.1 What k8-platform looks like today

- One GitHub Actions workflow (`.github/workflows/terraform-test.yml`,
  425 lines) handles `plan-only` and `apply-and-destroy` for both
  Terraform modules.
- Only three GitHub secrets (`AWS_ACCESS_KEY_ID`,
  `AWS_SECRET_ACCESS_KEY`, `AWS_REGION`); everything else is
  auto-discovered at runtime.
- Auto-CI is restricted to `test/**` branches (PR #6); other prefixes
  require `workflow_dispatch`.
- Eight Claude skills are installed under `.claude/skills/`: two repo-
  specific (`terraform-ci-watch`, `crossplane-claim-verify`) and six
  factory skills copied from `lago-morph/software-factory` in PR #11
  on 2026-05-14.
- One historical GitHub issue (#2, closed); no labels, no PR templates,
  no issue templates, no CODEOWNERS.
- Roadmap lives in `ai/handoff.md`; ten PRs have shipped, but
  **Iteration 1 has never been observed to apply-and-destroy end-to-end
  on the Pluralsight sandbox** (status blocker **B1**).

### 1.2 What pipeline-ai-sandbox ships

| Skill | Purpose |
|---|---|
| `batch-job` | Submit one batch job from a GitHub issue; poll for terminal status; ack. The agent-side primitive for running any command registered in `.agent/config.json :: commands` inside a GitHub Actions runner. |
| `task-dag` | Manage one agent-task issue as a DAG node: claim, plan subagents, merge subagent branches, schedule follow-ups. |
| `orchestrate-issue` | End-to-end primary loop: claim unclaimed issue → plan → fan out parallel subagents → run batch jobs → merge → open PR. |
| `onboarding` | Interview-based protocol adoption in an existing repo. Interruptible/resumable. Writes `.agent/onboarding/`. |
| `composition-guide` | Reference card for composing `batch-job` + `task-dag` manually. Documentation only. |
| `ask-before-adding-cicd` | Hard gate against unauthorised CI/CD changes. |
| `tightly-scope-github-actions` | Workflow hygiene rule: minimal `on:`, explicit `paths:`, per-step coverage. |
| `reproduce-ci-locally` | Reproduce a CI failure in a per-Python-version venv. |
| `live-observer-pattern` | Architecture for cross-phase async test observers (pipeline-ai-sandbox-internal). |
| Six "factory" skills already in k8-platform (`parallel-subagent-fanout`, `self-retrospective`, `subagent-prompting`, `post-edit-reread-pass`, `retro-coverage-audit-and-backfill`, `always-commit-skill-to-repo`). |

### 1.3 Shared shape

Both repos already assume:

- Secrets live in GitHub Actions, not on the agent.
- The agent dispatches workflows and reads their results back through
  comments / acks rather than executing privileged commands locally.
- One repo per MCP scope (`mcp__github__*` is repo-scoped).

This means the agent-job protocol from `pipeline-ai-sandbox` is a
natural generalisation of what `terraform-test.yml` already does for a
single command.

---

## 2. Fit assessment

| Skill | Fit | Why |
|---|---|---|
| `batch-job` | **Strong** | Generalises the `workflow_dispatch` pattern that `terraform-test.yml` uses. Multiple commands (plan, apply-and-destroy, Crossplane apply, claim-verify) can be registered as siblings instead of being encoded as a `mode` input. |
| `task-dag` | **Strong** | Directly addresses status blocker **B5** ("no backlog tracked in GitHub Issues; roadmap lives only in `ai/handoff.md`"). Iter 2's ~5 deliverables (REQ-XP-01..04 plus the end-to-end claim test) map cleanly onto DAG sub-issues. |
| `orchestrate-issue` | **Strong** | Composes the two primitives into the iteration-as-issue loop the repo currently lacks. Iter 2 / 3 / 6 are natural targets. |
| `onboarding` | **Strong** | The interview-based adoption flow is exactly the right tool for the migration. Interruptible/resumable; writes `.agent/onboarding/` so each decision is reviewable. |
| `composition-guide` | Reference | Useful if k8-platform wants to wire primitives manually for a custom primary-agent loop. |
| `ask-before-adding-cicd` | **Strong** | k8-platform deliberately keeps one workflow (PR #6 was a cost-control decision); this guard prevents accidental workflow proliferation during the refactor. |
| `tightly-scope-github-actions` | **Strong** | Enforces the same pattern as new workflows are added under the agent-job protocol. |
| `reproduce-ci-locally` | Marginal | Targeted at Python+venv reproduction; k8-platform CI is Terraform/bash and depends on AWS sandbox creds that can't be reproduced locally. `terraform-ci-watch`'s failure-taxonomy already covers most of the same ground. Worth porting the *idea* (reproduce-before-push) but not the skill verbatim. |
| `live-observer-pattern` | **No fit** | Internal pipeline-ai-sandbox test-harness architecture; not portable. |
| Factory skills | Already present | Identical code on both sides (PR #11). Decide whether to keep duplicating or share a canonical source. |

### 2.1 What still needs to be k8-platform-specific

- `terraform-ci-watch` — its failure taxonomy is Terraform/AWS-shaped
  and not generic enough to live in the protocol.
- `crossplane-claim-verify` — wholly k8-platform-specific (XRDs, EKS
  out-of-band checks).
- The sandbox bootstrap (S3 + DynamoDB recreated per session) is
  k8-platform-shaped and stays in the workflow.

The general rule: **agent-job protocol primitives stay generic; the
domain-specific verification skills remain repo-local but are invoked
as batch-job commands.**

---

## 3. Decisions the maintainer needs to make

These are the choices that the `onboarding` skill will explicitly ask
about. Surfacing them up front so they can be answered deliberately.

1. **Workflow topology — one workflow or many?**
   `terraform-test.yml` uses a `mode` input today. The agent-job
   protocol templates assume one workflow per command under
   `.github/workflows/agent-job-<command>.yml`. Trade-off: a single
   workflow is simpler to maintain and matches PR #6's "one workflow,
   one concurrency group" decision; per-command workflows are more
   orthogonal and match the protocol's defaults.
   **Recommendation:** keep a single workflow but split the mode input
   into a `command` input (`plan`, `apply-and-destroy`, `crossplane-apply`,
   `verify-claim`) so commands can be added without proliferating YAML.

2. **Source of truth for the roadmap.** `ai/handoff.md` today;
   orchestrate-issue assumes GitHub issues + their threaded ack
   comments are authoritative. Pick one or define how the two stay
   in sync. **Recommendation:** make issues authoritative after the
   migration; demote `handoff.md` to a generated view (or a short
   pointer to the iteration milestone).

3. **Crossplane verification placement.** `crossplane-claim-verify`
   runs locally today and needs kubeconfig. Either rewrite it as a
   batch-job command (`verify-claim`) so the runner has the kubeconfig
   and the agent doesn't, or leave it agent-local and accept that the
   agent must fetch kubeconfig per session.
   **Recommendation:** convert to a batch-job command. Keeps the
   "agent holds no AWS creds" invariant intact and reuses the
   workflow's existing `aws eks update-kubeconfig` step.

4. **Issue and label taxonomy.** Protocol needs structured issues;
   repo has zero labels. Seed set:
   - `agent-task` (claimable by protocol)
   - `iteration:0` … `iteration:6`
   - `area:terraform`, `area:crossplane`, `area:argocd`, `area:ci`,
     `area:docs`
   - `blocked-on:<issue-#>` (free-form, used by `task-dag`)
   - `claimed-by:<agent-login>` (set by `task-dag` on claim)

5. **Branch-prefix collision.** `test/**` is the only auto-CI prefix
   today; protocol runners typically push to `agent-job/<id>/<run-id>`
   branches. Decide whether protocol branches auto-trigger or stay
   `workflow_dispatch`-only.
   **Recommendation:** keep `agent-job/**` as `workflow_dispatch`-only.
   The protocol dispatches explicitly per job; auto-trigger adds no
   value and would multiply sandbox cost.

6. **Factory-skill duplication.** Six skills now live in both repos
   verbatim. Options:
   - Keep verbatim copies and accept drift.
   - Vendor via a one-shot install script in `pipeline-ai-sandbox`.
   - Treat `pipeline-ai-sandbox` as the canonical source and add a
     CI check in k8-platform that the copies are byte-identical.

7. **How much of `terraform-ci-watch` survives.** Significant overlap
   with `batch-job`'s polling loop. Options:
   - Reframe as a thin wrapper over `batch-job` (3-strike escalation
     and failure-taxonomy stay; polling delegates to `batch-job`).
   - Delete and inline the failure taxonomy into a batch-job
     extension.
   **Recommendation:** wrapper. The Terraform-specific failure
   taxonomy and 3-strike rule are load-bearing and shouldn't be lost.

8. **Concurrency strategy across protocol branches.** Today the
   `terraform-${{ github.ref }}` group serialises per-branch. Multiple
   `agent-job/*` branches from a single `task-dag` will not share that
   group and could race on Terraform state.
   **Recommendation:** add a coarse `aws-sandbox` concurrency group
   (with `cancel-in-progress: false`) across all AWS-touching commands
   so only one job can mutate sandbox state at a time, even across
   branches.

---

## 4. Risks

These are concrete risks that emerged from cross-reading the status
doc and the skill manifests.

| # | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| R1 | **Sandbox capacity vs. parallel fanout.** Pluralsight cap = 9 instances / 4 h (status §F1, F2). `parallel-subagent-fanout` + `task-dag` default to `MAX_PARALLEL=4`. If any subagent dispatches `apply-and-destroy`, the cap and the 4-hour clock are blown almost immediately. | High | High | Set `MAX_PARALLEL=1` for any task-dag whose subagents hit AWS. Reserve fanout for doc / YAML / spec issues. Add a coarse `aws-sandbox` concurrency group (decision #8). |
| R2 | **CI cost from chatty agent activity.** PR #6 deliberately turned off auto-CI for `feat/fix/chore` to protect the sandbox. Agent branches push frequently; if `agent-job/**` is accidentally included in `on.push.branches`, the sandbox is consumed by background dispatches. | Medium | High | Explicitly keep `agent-job/**` out of the `push:` trigger; use `workflow_dispatch` only. |
| R3 | **Terraform state-lock contention** across parallel `agent-job/*` branches. The existing per-branch concurrency group doesn't help across branches. | Medium | Medium | Decision #8 (sandbox-wide concurrency group). |
| R4 | **Crossplane verify needs a live cluster the agent can't reach.** Status blocker **B1** (Iter 1 apply never succeeded end-to-end) is still the gate. Adopting the protocol before B1 is cleared means the new tooling cannot be exercised against anything real. | Certain (gating) | High | Clear B1 with current tooling *before* refactoring. Do not migrate until one `apply-and-destroy` is observed green. |
| R5 | **`handoff.md` drift during migration.** Both the issue thread and `handoff.md` will be partially-authoritative for several sessions. Silent disagreement risk. | High | Medium | Pick one cutover commit; afterwards `handoff.md` is a pointer only. Add a one-liner at the top stating the cutover. |
| R6 | **Onboarding-branch collision.** `onboarding` writes to a well-known branch (`agent-job-protocol/onboarding`). Confirm it doesn't collide with the existing `test/**` policy or with `claude/**` branches. | Low | Low | Verify before first invocation; the prefix is distinct from all existing prefixes. |
| R7 | **Factory-skill drift.** Six identical skills in two repos will diverge silently over time unless one repo is canonical. | Medium | Low | Adopt decision #6 (canonical source + byte-identical check). |
| R8 | **Crossplane provider package churn** (status §F6). Provider was bumped in PR #7 and the v2 family is moving quickly. Refactor adds new entry points (`crossplane-apply` command) that have to be kept current. | Medium | Low–Medium | Pin in `variables.tf` (already done) and only bump deliberately. |
| R9 | **Let's Encrypt rate limits under repeated apply/destroy cycles** (status §F4). Protocol may dispatch apply-and-destroy more often than today. | Medium | Medium | Default to LE staging issuer during protocol-driven runs; production only for end-state validation. Add an ADR. |
| R10 | **Pluralsight credentials expire every 4 h** (status §F9). `batch-job`'s polling loop assumes secrets are valid for the run; if creds expire mid-job, the runner silently fails. | High (continuous) | Low (operational) | Already covered by existing rotation discipline; protocol doesn't make it worse but should surface "credential expired" as a distinct failure category in the taxonomy. |

---

## 5. Proposed workflow refactor

Sequencing matters. Do **not** start the refactor before clearing
status blocker B1 (Iter 1 apply-and-destroy observed green end-to-end).

### Phase 0 — Pre-refactor (current session work)
1. Run `apply-and-destroy` on `main` against a fresh sandbox (existing
   tooling). Resolve B1.
2. Add Cognito groups (`k8s-admins`, `k8s-viewers`) to
   `terraform/base/cognito.tf` (status §B6).
3. Update `handoff.md` with proof.

### Phase 1 — Onboarding & seed
1. Invoke `onboarding` skill against k8-platform. Capture answers to
   decisions #1–#8 above in `.agent/onboarding/recommendations.md`.
2. Self-install protocol templates (`batch-job`, `task-dag`,
   `orchestrate-issue` write to `.agent/config.json` and template
   files on first invocation).
3. Seed the label taxonomy (decision #4) and create one issue template
   (`agent-task.md`) under `.github/ISSUE_TEMPLATE/`.

### Phase 2 — Generalise the workflow
1. Refactor `terraform-test.yml` so the `mode` input becomes a
   `command` input with values: `plan`, `apply-and-destroy`,
   `crossplane-apply`, `verify-claim`. Each value gates a different
   job-step subset.
2. Register the command set in `.agent/config.json :: commands`.
3. Add a coarse `aws-sandbox` concurrency group with
   `cancel-in-progress: false` across all AWS-touching commands
   (decision #8).
4. Keep `test/**` auto-trigger; explicitly do not auto-trigger on
   `agent-job/**`.
5. Apply `tightly-scope-github-actions` to the resulting YAML.

### Phase 3 — Drive Iter 2 via the protocol
1. Open one parent issue (`epic: Iter 2 — Crossplane foundations`)
   labelled `iteration:2`.
2. Open five child agent-task issues:
   - `PlatformSecret` XRD + Composition
   - `PlatformCluster` XRD + Composition
   - `ClusterSecretStore` for ASM
   - ArgoCD `Application` pointing at `crossplane/`
   - End-to-end claim test
3. Dispatch `orchestrate-issue` against the parent. `MAX_PARALLEL=1`
   because all subagents touch state.
4. Convert `crossplane-claim-verify` to a batch-job command
   (`verify-claim`).

### Phase 4 — Promote issues to source of truth
1. Demote `ai/handoff.md` to a top-of-file pointer at the current
   open iteration milestone.
2. Reframe `terraform-ci-watch` as a thin wrapper over `batch-job`
   that keeps its failure taxonomy and 3-strike escalation.
3. Resolve the stale link to `ai/testing-overview.md` in
   `docs/operations.md` (status §F7).

### Phase 5 — Iter 3+ as orchestrate-issue loops
Each iteration becomes one `orchestrate-issue` epic. `task-dag`
decomposes; `batch-job` dispatches; `crossplane-claim-verify` (now
a batch-job command) gates merges.

---

## 6. Open questions

These didn't fit into a single decision above and are worth flagging
for the maintainer:

- **Should the protocol's `agent-task` label coexist with the repo's
  `iteration:N` labels, or be merged?** The protocol assumes
  `agent-task` is sufficient; k8-platform's iteration-based planning
  benefits from `iteration:N` as a sortable axis.
- **Is `parallel-subagent-fanout` still used directly, or only via
  `task-dag`?** The two overlap; pick one entry point to avoid
  documentation drift.
- **Where does the LE-staging-vs-production decision live now?**
  Status §F4 flagged it as missing from the design. The refactor is
  a natural moment to land an ADR.

---

## 7. Summary

The pipeline-ai-sandbox skills are a **good fit** for k8-platform —
strong on `batch-job`, `task-dag`, `orchestrate-issue`, `onboarding`,
and the two CI-discipline skills; marginal on `reproduce-ci-locally`;
no fit on `live-observer-pattern`. The principal decisions are
workflow topology, source-of-truth migration for the roadmap, and
where Crossplane verification runs. The principal risks are sandbox
capacity under parallel fanout and the fact that the migration
shouldn't start until Iter 1 has been observed apply-green at least
once. The recommended refactor keeps a single workflow with a
generalised `command` input, drives Iter 2 as the first
`orchestrate-issue` epic, and promotes GitHub issues over
`ai/handoff.md` only after the cutover.

*End of report.*
