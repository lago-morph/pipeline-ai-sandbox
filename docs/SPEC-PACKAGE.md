# SPEC-PACKAGE — pipeline-skills-package

Status: design-stage
Audience: implementers building the bootstrap bundle in this POC repo

> Read `OVERVIEW.md` before this file. This is the meta-spec that
> cross-references the per-skill SPECs and defines the package-level
> contracts that apply to all of them.

## The 6 skill specs

| Skill | SPEC | Distributable? | Self-installs? |
|---|---|---|---|
| `batch-job` | [`skills/batch-job/SPEC.md`](./skills/batch-job/SPEC.md) | yes | yes |
| `task-dag` | [`skills/task-dag/SPEC.md`](./skills/task-dag/SPEC.md) | yes | yes |
| `orchestrate-issue` | [`skills/orchestrate-issue/SPEC.md`](./skills/orchestrate-issue/SPEC.md) | yes | yes |
| `onboarding` | [`skills/onboarding/SPEC.md`](./skills/onboarding/SPEC.md) | yes | indirectly (creates well-known branch + dialog dir) |
| `composition-guide` | [`skills/composition-guide/SPEC.md`](./skills/composition-guide/SPEC.md) | yes | no (docs-only) |
| `test-harness` | [`test-harness/SPEC.md`](./test-harness/SPEC.md) | **no** (dev only) | no |

The 5 distributable skills are what end users invoke. The
test-harness skill is bundled with the bootstrap (so the new repo
has it from day one) but excluded from any future distribution build.

## Package-level contracts

These contracts apply across all 5 distributable skills.

### Skill installation scope

All skills install at the **project level**: `.claude/skills/<name>/`
inside the target repo. Never at the user level (`~/.claude/skills/`)
in v1. Rationale: the protocol's `.agent/` directory and workflow
YAMLs live in the repo; the skills that drive them should too — same
audit boundary, same versioning, same review surface.

### Self-install marker

A skill considers the protocol "installed" when `.agent/config.json`
exists in the target repo. Each skill, on invocation, checks this
marker and self-installs its bundled templates if missing.

A skill considers the repo "onboarded" when both:

- `.agent/config.json` is present
- A dialog file exists on the well-known branch `agent-job-protocol/onboarding`

Not-onboarded is fine. The 4 protocol skills work standalone. The
onboarding skill is offered, never required.

### Conflict handling on install

If a target file exists at a path the skill wants to install:

1. If content is byte-identical to the bundled template → no-op.
2. If content differs:
   - Compute a diff and show to the user.
   - Ask: "overwrite, skip, or write to `<path>.new` for manual merge?"
3. If the user declines and selects skip, the skill records the skip
   in its own state log (`.agent/installs/<skill>.log`) and proceeds.

`AGENTS.md` and `CLAUDE.md` are **never** in the installable file
list of any of the 5 skills. The onboarding skill alone can propose
pointer-line edits to those files, and only with explicit per-file
user approval.

### Bundled templates discipline

Each skill bundles **its own** copy of every template file it needs.
Some files (e.g. `.agent/scripts/common.py`) appear in multiple skill
packages. The contract test (`tests/distribution/test_template_parity.py`)
asserts that:

- Each bundled template byte-matches the POC's working source.
- Across skills, copies of the same template are byte-identical to each other.

If the POC source changes, the contract test fails until the bundled
copies are regenerated.

### SKILL.md frontmatter

Every distributable skill's SKILL.md has:

```yaml
---
name: <skill-name>
description: |
  <2-4 sentence description, includes trigger phrases the skill matches>
allowed-tools:
  - <list of tools the skill calls>
---
```

`description` is the substring Claude Code matches when routing the
Skill tool. It must mention at least one canonical trigger phrase
and must end with the self-install note (where applicable).

### Versioning

Each skill's `SKILL.md` carries a `# Version` header at the bottom:

```markdown
---
Version: 1.0.0
Protocol-version: 1
Last-synced-from-POC: 2026-05-14
---
```

Bumping `Protocol-version` requires shipping the new handler on the
default branch first (per POC SPEC §13).

## Cross-skill behaviors

### Skill A invokes skill B

When `orchestrate-issue` invokes `batch-job` or `task-dag`, it calls
into the **Python helpers** (importable as a library), not the
Skill-tool invocation. The Python helpers are part of the bundled
templates and live at `.agent/scripts/agent_lib/` plus the skill's
own `lib/` directory.

Calling another skill via the Skill tool from inside an executing
skill is **not supported** in v1 — too easy to recurse.

### Onboarding referrals

When any of the 4 protocol skills self-installs and notices the
absence of an onboarding dialog file, it emits a one-time message:

> Protocol installed. Onboarding has not been run in this repo. Run
> `/onboarding` for guided integration with your existing workflow,
> or skip — the skills work standalone.

The message appears once per skill per session (skill records the
hint in `.agent/installs/<skill>.log`).

## Bundle structure

The bootstrap bundle has this layout (the recipe Markdown and the
tarball both produce this tree when applied/extracted):

```
<repo-root>/
  .claude/skills/
    batch-job/
      SKILL.md
      templates/agent/...
      templates/github/...
      lib/...
    task-dag/
      SKILL.md
      templates/...
      lib/...
    orchestrate-issue/
      SKILL.md
      templates/...
      lib/...
    onboarding/
      SKILL.md
      templates/...
      lib/...
    composition-guide/
      SKILL.md
  test-harness/
    SKILL.md
    archetypes/...
    scenarios/...
    lib/...
    runs/.gitkeep
  docs/
    OVERVIEW.md             (the same OVERVIEW.md the POC has)
    SPEC-PACKAGE.md
    skills/<name>/SPEC.md   (all 6 specs replicated for in-repo reference)
    test-harness/SPEC.md
  bootstrap/
    install.md              (the agent-facing contract)
  NEW-REPO-PLAN.md
  TESTING-IN-POC.md         (so the new repo has a copy of the POC's testing strategy for reference)
  README.md                  (new-repo-specific README written by install.md)
```

The recipe Markdown also includes `install.md` as its first section so
the agent reading it executes installation top-to-bottom.

## Build process

A small script at `pipeline-skills-package/bootstrap/build.py` generates
both forms from one source:

1. Walks `pipeline-skills-package/`.
2. Excludes files listed in `bootstrap/distribution-exclude.txt`.
3. Generates `bootstrap/dist/install.md` (the recipe).
4. Generates `bootstrap/dist/pipeline-skills-package.tar.gz` (the tarball).
5. Generates `bootstrap/dist/MANIFEST.txt` listing all included files
   with sha256 sums.

The script is the single source of truth. Manual edits to the recipe
or tarball are forbidden (the build script re-generates them).

## Contract tests in this POC

A new directory `tests/distribution/` houses the contract tests. The
POC's `pytest.ini` already restricts test discovery to `tests/`, so
adding files under `tests/distribution/` is picked up automatically.

The tests:

| Test | Asserts |
|---|---|
| `test_template_parity.py` | Every bundled template byte-matches the POC's working source |
| `test_schema_validity.py` | Every bundled JSON schema is a valid Draft 2020-12 document |
| `test_skill_md_frontmatter.py` | Every SKILL.md has the required frontmatter keys |
| `test_install_dry_run.py` | Install logic against a mock filesystem produces the right file list |
| `test_recipe_idempotent.py` | Applying the recipe twice in a row is a no-op the second time |
| `test_archive_round_trip.py` | Extracting the tarball matches applying the recipe byte-for-byte |
| `test_bundle_contents.py` | Manifest matches the actual files in the tarball / recipe |
| `test_no_secrets_in_bundle.py` | No file in the bundle contains anything matching common secret patterns |

These tests run with the POC's normal pytest invocation. They do not
touch `.agent/`, `.github/workflows/`, or any other POC operational
file.

## Out-of-scope for v1

- Backend abstraction (Bitbucket/Jira adapter). See
  `proposals/agent-api-refactor/` in this POC for the design brief.
- User-level skills (`~/.claude/skills/`).
- Skill registries other than Claude Code's project-level scope.
- Auto-update of installed skills (overwrite logic stays manual).

These belong in v2.

## Cross-document references

- `OVERVIEW.md` — high-level explanation with the flow diagram
- `PLAN-PACKAGE.md` — how to build this package in this POC repo
- `TESTING-IN-POC.md` — partial-testing strategy
- `NEW-REPO-PLAN.md` — what happens after the archive lands in the new repo
- `bootstrap/install.md` — the agent contract for the new repo
- `RESUME.md` — handoff prompt for a future session
