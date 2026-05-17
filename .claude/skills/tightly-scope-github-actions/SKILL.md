---
name: tightly-scope-github-actions
description: Constrain every GitHub Actions workflow to exactly what it needs to do — minimal `on:` triggers, explicit `paths:` filter (positive list preferred), and per-step coverage matching the repo's actually-editable surface. Triggers proactively before committing any change under `.github/workflows/`, when authoring a newly-approved workflow (after `ask-before-adding-cicd` clears it), or when auditing existing workflows that run on PRs touching files they don't validate. A cold re-read of the workflow YAML must find zero lines whose presence isn't justified; steps that validate bootstrap / vendored / read-only content belong in the upstream repo where the content is authored, not here. Tightening sometimes leads to deletion — surface that as a separate decision to the user.
---

# Skill: tightly-scope-github-actions

When a GitHub Actions workflow is being added or modified, scope it to
**exactly what it needs to do and nothing else**. Three dimensions, all
must be checked:

1. **Triggers** — minimal `on:` block. Don't list events that aren't
   used. Don't fire on `pull_request` if the workflow's job doesn't
   produce PR-relevant signal.
2. **Paths filter** — `paths:` (positive list) or `paths-ignore:`
   (negative list) restricting which file changes wake the workflow.
   The default of "fire on every PR / every push" is almost never the
   right scope.
3. **Per-step coverage** — every step's actions must validate content
   that is **actually editable in this repo**, given the repo's
   editing model. Steps that validate bootstrap / vendored / read-only
   content belong upstream where the content is authored, not here.

A workflow that runs unscoped on every PR — even with cheap steps — is
wrong by default. It costs compute, it adds PR-status noise, and it
teaches reviewers to ignore CI status.

---

## Trigger phrases

### Direct triggers
- "Scope this workflow tightly."
- "Audit `.github/workflows/<name>.yml` for what it actually validates."
- "Why is this CI running on docs-only PRs?"

### Proactive triggers
- You're about to commit a change to a file under `.github/workflows/`.
  Apply this skill before pushing.
- `ask-before-adding-cicd` cleared a new workflow. Apply this skill
  when authoring it.
- You notice an existing workflow running on a PR that touches none of
  the files it validates. Audit and tighten.
- A user complains about CI noise / wasted compute.

### Negative triggers
- The workflow truly does need to run on every PR (e.g., a
  required-status-check enforcing a repo-wide policy). Document that
  explicitly in a YAML comment; don't tighten beyond the policy's
  intent.

---

## Workflow

1. **Read the workflow YAML.** Note current `on:`, `paths`, per-step
   actions, and any inline comments explaining intent.
2. **Articulate the workflow's purpose** in one sentence. If you can't,
   the workflow is probably broken or unnecessary — stop and ask the
   user before scoping.
3. **Read the repo's editing rules.** Compile a list of paths that are
   editable here vs. paths that are read-only / bootstrap / vendored.
   Use `AGENTS.md` / `CLAUDE.md` as the source of truth.
4. **Map each step to its target paths.** What files does this step
   actually need to validate? Are those files editable here?
5. **Delete steps whose targets aren't editable here.** Bootstrap
   schema validation, vendored-code lint, read-only spec parsing —
   those belong in the upstream repo where the content is authored.
6. **Tighten triggers:**
   - Drop event types that aren't needed.
   - Add `paths:` to scope to the editable surface that survived step 5.
     Prefer positive lists (`paths:`) over `paths-ignore:` so new paths
     default to "not run" — adding a new path is explicit.
   - For `push:`, restrict to relevant branches (usually `[main]`).
   - Question whether you need `schedule:` at all. Most workflows
     don't.
7. **Re-read the YAML cold.** Each line must justify itself. Lines
   without justification get deleted.
8. **If tightening leaves no useful surface, surface the deletion as a
   separate decision to the user.** Don't bundle "tighten" and "delete"
   in one motion.

---

## Concrete examples

### Example 1 — the workflow that got deleted (PR #8)

**Before** (`.github/workflows/test-harness-ci.yml`):

```yaml
name: test-harness-ci
on:
  pull_request:
  push:
    branches: [main]
  schedule:
    - cron: '0 7 * * *'

jobs:
  static-validation:
    strategy:
      matrix:
        python-version: ['3.11', '3.12']
    steps:
      - Lint with ruff (`ruff check .`)
      - Compile-check Python sources (.claude/skills + test-harness)
      - YAML parse (scenarios + skill workflow templates)
      - JSON parse (archetype manifests)
      - SKILL.md frontmatter validation
      - Scenario cross-reference (archetype + skill existence)
      - Scenario runner discovery
      - Unit tests
```

**Audit against editing rules** (`AGENTS.md` §2: "Never modify
bootstrap-installed files under `.claude/skills/`, `docs/`, or
`test-harness/{SKILL.md,SPEC.md,archetypes/,scenarios/}`"):

| Step | Targets | Editable here? |
|---|---|---|
| ruff | all `.py` | only `test-harness/{lib,runners,tests}/` + `.agent/scripts/` |
| py_compile | `.claude/skills/**.py` + `test-harness/**.py` | most of `.claude/skills/` is bootstrap |
| YAML parse | scenarios + skill templates | bootstrap, can't edit |
| JSON parse | archetype manifests | bootstrap, can't edit |
| SKILL.md frontmatter | `.claude/skills/*/SKILL.md` | bootstrap, can't edit |
| Scenario cross-reference | scenarios → archetypes + skills | bootstrap on both sides |
| Scenario runner discovery | lists files | theatre |
| Unit tests | `test-harness/tests/` | yes |

**Tightening decision**: 4 of 8 steps validate bootstrap-installed
content this repo can't edit; they belong in the POC repo's CI. Step 7
is theatre. After stripping, only ruff (on editable paths only) and
pytest remain. At that point the question flipped to "should this
workflow exist at all?" The answer was no, and PR #8 deleted the whole
file. **Tightening is good practice even when it leads to deletion —
it forces the question.**

### Example 2 — a correct paths filter that still didn't justify the workflow

**`.github/workflows/contract-tests.yml`** (also deleted in PR #8):

```yaml
on:
  pull_request:
    paths:
      - '.claude/skills/**/templates/agent/schemas/**'
```

The trigger fired only on schema changes. The mistake here wasn't the
scope (which was correct) but the *purpose* — the schemas it validated
weren't supposed to change in this repo. `ask-before-adding-cicd` should
have killed this workflow before it was authored; once it existed,
`tightly-scope-github-actions` couldn't save it from being cruft.

### Example 3 — authoring a well-scoped workflow

Suppose `ask-before-adding-cicd` clears you to add a workflow that runs
`pytest` on the harness lib tests only. Authored correctly:

```yaml
name: harness-lib-tests
on:
  pull_request:
    paths:
      - 'test-harness/lib/**'
      - 'test-harness/tests/**'
      - 'test-harness/runners/**'
      - 'pyproject.toml'
      - 'requirements-dev.txt'
      - '.github/workflows/harness-lib-tests.yml'
  push:
    branches: [main]
    paths:
      - 'test-harness/lib/**'
      - 'test-harness/tests/**'
      - 'test-harness/runners/**'

jobs:
  pytest:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.12' }
      - run: pip install -q -r requirements-dev.txt
      - run: python -m pytest test-harness/tests -ra -q
```

Notes:
- `paths:` is a positive list — adding a new editable directory
  requires an explicit workflow update.
- `push:` is restricted to `main` AND to the same paths.
- Workflow file itself is in `paths:` so changes to the workflow
  trigger the workflow (catches breakage of the workflow itself).
- No `schedule:` — pytest doesn't need to run on a timer.
- One Python version, not a matrix, until matrix coverage is
  explicitly justified.
- One job, one purpose. The name reflects exactly what it does.

---

## Anti-patterns

- **Default-on triggers.** A bare `pull_request:` (no path filter, no
  type filter) is almost always wrong. Default expansion to every PR /
  every event is the source of most CI noise.
- **Kitchen-sink jobs.** "Static validation" jobs that bundle 5+
  unrelated steps tend to accumulate cruft. Prefer one job per
  purpose. Each job's name should describe a single thing.
- **`paths-ignore:` as a primary defence.** It papers over scope bugs;
  a new directory automatically becomes in-scope. Prefer `paths:`
  (positive list) so new directories default to "not run" and adding a
  path is explicit.
- **Matrix axes without justification.** Running py3.11 + py3.12 +
  py3.13 + py3.14 because "it might break on a future version" triples
  your compute for no observed signal. Add matrix axes only when a real
  regression motivates it.
- **`schedule:` on workflows whose job doesn't need a timer.** Daily
  cron is a load-bearing pattern only for actual canaries. For most
  workflows, schedule should be the exception.
- **Bootstrap-installed schema / lint validation in a maintenance
  repo.** Those checks belong in the upstream repo where the content
  is authored. Replicating them downstream is duplicate work and
  creates "where does this bug live?" confusion.
- **Workflows whose self-name doesn't describe what they do.**
  `test-harness-ci` is generic; the survivor was actually
  "validate the bootstrap manifest" + "lint test-harness Python" — two
  different purposes glued together.

---

## Acceptance criteria

1. The workflow's purpose can be stated in one sentence.
2. Every `on:` event type is justified; no defaults inherited silently.
3. Every triggering event has a `paths:` (preferred) or `paths-ignore:`
   filter, OR an inline comment explaining why the workflow truly does
   need to fire on every change.
4. Every step's coverage targets paths that are editable in this repo.
5. The workflow file is itself in the workflow's `paths:` list (so
   changes to the workflow trigger the workflow).
6. A cold re-read finds zero lines whose presence isn't justified.

---

## See also

- `ask-before-adding-cicd` — the companion skill that gates whether a
  workflow should exist at all. Apply that one *before* this one.
