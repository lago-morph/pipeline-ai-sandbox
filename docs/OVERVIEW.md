# OVERVIEW — pipeline-skills-package

> If you are picking this work up cold, read this file first. It is the
> map for everything else in `pipeline-skills-package/`.

This directory is the **derived work** product of the
`poc-github-ai-sandbox` proof-of-concept. The POC validated a protocol
for AI agents to dispatch work into GitHub Actions runners using only
GitHub MCP transport. This directory packages that protocol as a set of
distributable Claude Code skills, plus the bootstrap and plans for the
next phase of work.

The POC repo (everything outside this directory) is preserved as-is.
Nothing under `pipeline-skills-package/` modifies POC code, tests,
workflows, or the `_agent_runs` branch.

## Three artifacts, two destinations

```
This POC repo (poc-github-ai-sandbox)
   │
   │  Partial testing here against bundled skill templates,
   │  schema validators, and onboarding interview logic.
   │  POC's existing 446 tests stay untouched.
   │
   ▼
Build the self-extracting bootstrap bundle
   │  (lives at pipeline-skills-package/bootstrap/dist/ once built)
   │
   │  Archive contains: 5 distributable skills + test harness +
   │  per-skill specs + install.md + new-repo plan + design docs.
   │  Two forms generated from one source: a single recipe Markdown
   │  file AND a tar.gz, byte-equivalent in content.
   │
   ▼
User copies archive into a brand-new repo named `pipeline-ai-sandbox`
   │
   │  Tells an agent: "unzip/expand and follow install.md"
   │
   ▼
New repo (pipeline-ai-sandbox, the maintenance project)
   │
   │  Test harness runs here (real GitHub via the agent's own MCP
   │  credentials — no separate test account).
   │  Full testing, ongoing development of the 5 skills.
   │  POC repo stays preserved as historical reference.
   │
   ▼
Future distribution builds (5 user-facing skills only;
test harness stays in the maintenance repo).
```

## The three pieces

### 1. This POC repo

The home of the original protocol implementation. Everything under
`.agent/`, `.github/workflows/`, `skills/batch-job/`, `skills/task-dag/`,
`harness/`, `tests/`, and `_agent_runs` is the POC. It will not be
modified by this packaging work.

Inside the POC, `pipeline-skills-package/` is a new subdirectory that
contains:

- This file (`OVERVIEW.md`)
- A package-level spec (`SPEC-PACKAGE.md`)
- Implementation plans (`PLAN-PACKAGE.md`, `NEW-REPO-PLAN.md`)
- Per-skill specs under `skills/<name>/SPEC.md`
- Test-harness spec under `test-harness/SPEC.md`
- A testing strategy doc (`TESTING-IN-POC.md`)
- A bootstrap install contract (`bootstrap/install.md`)
- A handoff prompt (`RESUME.md`)

The eventual build artifacts (recipe + tarball) land under
`pipeline-skills-package/bootstrap/dist/` — that path is gitignored by
default but the recipe is small enough to commit if desired.

### 2. The self-extracting bootstrap bundle

Two forms, same content:

- **Recipe Markdown** — a single file with all bundled files inlined in
  fenced code blocks. An agent reads it top to bottom and creates each
  file in the location its header specifies. Pure text. Diffs cleanly.
- **Tarball (tar.gz)** — a traditional archive arranged so that
  extracting at repo root places everything correctly. Faster to apply
  in one step.

Both forms include `install.md` as their entry point. `install.md`
tells the agent what to verify, what to copy where, and how to confirm
the install succeeded. Both forms are generated from one source
directory by a small build script.

### 3. The new repo: pipeline-ai-sandbox

A freshly created GitHub repo. The user copies the archive in,
tells an agent to extract and run `install.md`, and the resulting repo
contains:

- The 5 distributable skill packages with bundled templates
- The test harness (development-only — does not ship in future
  distributions)
- All per-skill specs and design docs
- A working CI setup so the test harness can drive real GitHub Actions
- A README explaining the maintenance project's purpose

From there, the new repo is the home for ongoing skill development.
It dogfoods the protocol: the test harness drives real issues, real
batch-jobs, real subagent fanout against the new repo itself, using
the agent's own MCP credentials. No separate test account required.

## The five distributable skills

| Skill | Role |
|---|---|
| `batch-job` | Submit one batch job from an active issue, poll for terminal status, ack. Self-installs its templates on first invocation. |
| `task-dag` | Claim issue, plan subagents, merge sub-branches, schedule successors. Self-installs its templates. |
| `orchestrate-issue` | End-to-end primary-agent loop for heavy adoption. Wraps `task-dag` + `batch-job` into one invocation: claim → plan → fan out → batch-job → merge → PR. |
| `onboarding` | Interview-based discovery of an existing repo's workflow; produces a recommendations document and optionally applies edits. Triggered automatically when other skills detect they are uninstalled, or on demand. |
| `composition-guide` | SKILL.md-only reference explaining how to compose the four implementation skills above for users who prefer the primitives over the orchestrator. |

Each skill is a fully self-contained Claude Code skill package:

- `SKILL.md` with frontmatter for skill-tool discovery
- Bundled templates (workflow YAMLs, `.agent/` scripts, schemas, config)
- Self-install logic embedded in SKILL.md ("if these files are missing,
  copy them from this skill's `templates/` directory into the target
  repo at these paths")

A skill is "installed" in the target repo when `.agent/config.json`
is present. A repo is "onboarded" when both `.agent/config.json` and
the onboarding dialog file (on the well-known branch
`agent-job-protocol/onboarding`) are present.

## The test harness (development only)

The test harness is the 6th skill in the bundle but it is
**not part of the eventual end-user distribution**. It lives only in
the new repo. Its purpose:

- Generate synthetic repo archetypes (with/without AGENTS.md,
  with/without CI, GitLab vs GHA vs Jenkins, etc.).
- Drive the 5 distributable skills against those archetypes.
- Validate end-to-end behavior against real GitHub from an agent
  sandbox using the agent's own MCP credentials.

See `test-harness/SPEC.md` for full detail.

## What "install" means at each level

| Boundary | What "install" does |
|---|---|
| Skill into target repo | Each skill, on first invocation, detects whether its templates are present in the target repo (under `.agent/`, `.github/workflows/`, `.claude/skills/<name>/`). If missing, the skill copies its bundled templates into place via tool calls. |
| Bootstrap into new repo | The agent in the new repo expands the archive (extract tarball or follow recipe Markdown), then runs the install.md procedure to lay out the skills, test harness, specs, and CI files. |
| Future end-user adoption | A user in any project invokes any of the 5 skills directly. The skill self-installs its templates. The onboarding skill can also be invoked explicitly for guided adoption. |

## Why this structure

- **POC stays a POC.** Treating it as historical reference makes it
  reliable as a source of truth for the protocol's working state.
- **One subdirectory contains all derived work.** Reviewers and future
  agents can tell at a glance what is POC and what is package.
- **The archive is the handoff.** It is the only artifact that
  crosses the boundary between this repo and the new one. Everything
  the new repo needs to bootstrap is inside it.
- **Templates are contract-tested copies, not symlinks.** A test in
  this POC asserts that bundled templates byte-match the POC's
  working source. The POC remains canonical until the new repo
  takes over.
- **Self-installation per skill.** Each skill is independently usable
  in any project that has Claude Code skills enabled. No global
  installer step.

## How to navigate this directory

| If you want to … | Read |
|---|---|
| Understand the whole package | This file, then `SPEC-PACKAGE.md` |
| Know how each skill behaves | `skills/<name>/SPEC.md` |
| Know how the test harness behaves | `test-harness/SPEC.md` |
| Build the bootstrap archive in this repo | `PLAN-PACKAGE.md` |
| Test the work in this repo without disrupting the POC | `TESTING-IN-POC.md` |
| Set up the new `pipeline-ai-sandbox` repo from the archive | `bootstrap/install.md`, then `NEW-REPO-PLAN.md` |
| Continue this work in a future session | `RESUME.md` |

## Provenance

This directory was created on a `claude/assess-project-status-YBFY9`
branch in `lago-morph/poc-github-ai-sandbox`. The design decisions
captured here came from a single planning conversation that reviewed
the POC's state, distilled the protocol from `SPEC.md`, and produced
the architecture described above.
