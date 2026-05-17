---
name: reproduce-ci-locally
description: When a CI check fails and you can't read the workflow logs (MCP restrictions, slow log endpoints, deep job histories), reproduce the failure in a fresh per-Python-version venv that matches the CI runner's setup, then run the exact failing command from the workflow YAML — verbatim, not paraphrased. Triggers on `<github-webhook-activity>` events reporting CI failures whose conclusion alone doesn't pinpoint the cause; on user phrases like "reproduce the CI failure locally", "why did CI fail?" (when annotations don't tell you), "set up a venv that matches the CI runner"; whenever a CI step name reveals a Python (or other tool) version that can be installed locally. Negative trigger: failures in steps that require GitHub Actions infrastructure to be meaningful (workflow-dispatch, repo-creation, cross-job artifacts), where local reproduction isn't faithful.
---

# Skill: reproduce-ci-locally

When a CI check fails and the agent can't read the workflow logs
(MCP-restricted environments, slow log endpoints, deep job histories),
the fast path is to reproduce the failure in a **fresh
per-Python-version virtual environment** matching the CI runner's
setup, then run the exact failing command. The reproduction usually
takes <60 seconds and gives you the failure text directly — far
cheaper than guessing-and-pushing.

In one session, this pattern collapsed a CI-failure-to-fix loop from
"push, wait, push, wait" to ~3 minutes wall time: build venv, install
deps, reproduce 3 F401 lint errors, fix, commit, push. Without the
reproduction step the agent would have had to either burn webhook
cycles or read scattered annotation tea-leaves.

---

## Trigger phrases

### Direct triggers
- "Reproduce the CI failure locally."
- "Why did CI fail?" (when annotations don't tell you).
- "Set up a venv that matches the CI runner."

### Proactive triggers
- A `<github-webhook-activity>` event arrives reporting a CI failure
  on a PR you're driving, AND the failure conclusion alone doesn't
  identify the root cause, AND you cannot fetch full workflow logs
  via MCP tools.
- The CI step name reveals a Python (or other tool) version
  (`static-validation (py3.12)`, `tests (node-20)`) and the failure is
  in a step you can run locally (lint, test, compile-check,
  format-check).

### Negative triggers
- The failure is in a step that requires GitHub Actions infrastructure
  to be meaningful (workflow-dispatch propagation, repo-creation
  flows, cross-job artifact uploads). Reproducing those locally is
  not faithful.
- The CI annotations already pinpoint the failure (file:line:rule).
  No reproduction needed; just fix.

---

## Inputs

- **Workflow YAML** at `.github/workflows/<name>.yml` so you can read
  the exact step commands.
- **`requirements-dev.txt`** (or pyproject `[project.optional-dependencies].dev`)
  for the CI's pip install line.
- **Python version** from the matrix axis in the failing job name
  (`(py3.12)` → 3.12).
- A writable scratch directory for the venv (`/tmp/.venv-ci` is fine;
  it should NOT live under the repo tree).

---

## Workflow

1. **Identify the Python version** from the failing job name. Workflow
   matrix names usually embed it: `static-validation (py3.11)`,
   `tests (3.12.4)`, etc.
2. **Check the version is available locally:** `which python3.X` and
   `python3.X --version`. If missing, install it via the system
   package manager or `uv python install 3.X`. If the version can't
   be installed (CI uses a beta / patch release not yet packaged),
   pick the closest available + note the discrepancy in your
   follow-up.
3. **Create a fresh venv:** `python3.X -m venv /tmp/.venv-ci`. Always
   prefer a scratch path outside the repo so it never accidentally
   gets committed.
4. **Install the CI's deps:** read the workflow's install step. Most
   are `pip install -r requirements-dev.txt`. Run that with the
   venv's pip: `/tmp/.venv-ci/bin/pip install -q -r requirements-dev.txt`.
5. **Run the exact failing command.** Copy it verbatim from the
   workflow YAML; don't paraphrase. If the workflow uses
   `python -m pytest test-harness/tests -ra -q`, run that exact line
   with `/tmp/.venv-ci/bin/python -m pytest test-harness/tests -ra -q`.
6. **Bisect step-by-step if needed.** Some workflows have many steps
   in one job. Run them in order until one fails. Keep going past the
   first failure if the workflow's job has `continue-on-error: true`
   — you want every CI-visible failure, not just the first.
7. **Fix what reproduced.** Commit on the same branch tracking the
   failing PR. Don't squash; the fix-commit is independent evidence
   that the failure was understood.
8. **Push and watch CI.** You're subscribed to the PR; the webhook
   tells you whether the fix took.

---

## Concrete examples

### Example 1 — F401 unused imports caught by CI's `ruff check .`

**Session evidence**: PR #5 first push failed both
`static-validation (py3.11)` and `static-validation (py3.12)`. No log
access. Job name confirmed both Python versions had the same failure
(so likely not version-specific).

```bash
# Step 2: confirm 3.12 available
which python3.12 && python3.12 --version
# /usr/bin/python3.12
# Python 3.12.3

# Step 3: fresh venv
python3.12 -m venv /tmp/.venv-ci

# Step 4: deps
/tmp/.venv-ci/bin/pip install -q -r requirements-dev.txt

# Step 5: reproduce — CI runs `ruff check .` from repo root
/tmp/.venv-ci/bin/ruff check .
# F401 [*] `json` imported but unused
#   --> test-harness/tests/test_runner_batch_job_happy_path.py:15:8
# F401 [*] `os` imported but unused
#   --> test-harness/tests/test_runner_batch_job_happy_path.py:16:8
# F401 [*] `scenario_runner` imported but unused
#   --> test-harness/tests/test_runner_batch_job_happy_path.py:110:12
# Found 3 errors.

# Step 7: fix the 3 imports, commit, push (commit e5e2efb).
```

**Wall time from webhook to push: ~3 minutes.**

### Example 2 — test failure that's actually a dependency conflict

Hypothetical but informed by common patterns: a `pytest` failure in
`test_widget_render` reports
`AttributeError: module 'numpy' has no attribute 'asarray'`. The
error suggests numpy version drift.

```bash
# Step 1: workflow says py3.11.
# Step 3-4: venv + install.
python3.11 -m venv /tmp/.venv-ci
/tmp/.venv-ci/bin/pip install -q -r requirements-dev.txt

# Step 5: reproduce.
/tmp/.venv-ci/bin/python -m pytest tests/test_widget_render.py -q
# AttributeError: module 'numpy' has no attribute 'asarray'

# Step 6: check what was installed.
/tmp/.venv-ci/bin/pip show numpy
# Version: 1.18.0   ← prehistoric

# Step 7: fix — bump the floor in requirements-dev.txt:
#   numpy>=1.24
```

The reproduction immediately showed the dependency-resolution issue
that the CI logs would have shown anyway, but without needing log
access.

---

## Anti-patterns

- **Don't reproduce in the project's working venv** — it's
  contaminated by editable installs and your local in-progress
  changes. The point is to mirror CI's fresh runner.
- **Don't paraphrase the workflow command.** If CI runs
  `python -m pytest test-harness/tests -ra -q`, don't run
  `pytest test-harness/tests`. The flags and the `python -m` matter.
  `addopts` from `pytest.ini` apply either way, but config-discovery
  starts from the cwd; run from the same cwd CI uses.
- **Don't skip the deps install** because "the system pytest is
  fine" — your system pytest might be a different major version,
  silently changing behaviour (markers, fixture scopes).
- **Don't keep the venv inside the repo tree** — it'll show up in
  `git status`, get accidentally committed, slow down tooling.
- **Don't reproduce-and-guess.** If the reproduction succeeds (CI
  passes locally), the failure is environment-specific to the
  runner (network, secrets, time-of-day). Don't push a "should fix
  it" commit; identify the actual environmental cause.

---

## Acceptance criteria

1. The failing CI command runs locally and produces output you can
   read.
2. The local output either reproduces the failure (success — now
   fix it) or doesn't (and that itself is a finding worth reporting).
3. The venv is outside the repo tree.
4. The Python version matches the failing CI job's matrix axis.
5. The reproduction uses the EXACT command from the workflow YAML,
   not a paraphrase.
