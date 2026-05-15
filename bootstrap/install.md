# install.md — bootstrap contract for the new pipeline-ai-sandbox repo

Status: agent-facing contract.
Audience: the Claude Code agent that's been told to bootstrap a freshly
created `pipeline-ai-sandbox` repo from this bundle.

> If you are a human reading this: you don't run this yourself.
> Copy `install.py` (self-extracting installer) into your fresh
> `pipeline-ai-sandbox` repo, then tell a Claude Code agent:
> "Run `python install.py`, then read `bootstrap/install.md` and
> follow it."

## What you (the agent) are doing

You are bootstrapping a brand-new repo called `pipeline-ai-sandbox`.
This repo will become the maintenance project for a set of Claude
Code skills that implement the agent-job dispatch protocol described
in `docs/SPEC-PACKAGE.md`.

By the time you are reading this file, the bundle has already been
extracted onto disk — either by `python install.py` (the self-extracting
installer, recommended) or by `tar -xzf pipeline-skills-package.tar.gz`
(the equivalent tarball form). Your job from here is to verify the
extracted tree, then move on to `NEW-REPO-PLAN.md`.

## Section 1 — pre-flight (always run)

Before writing anything, verify:

1. You are in a git repository:
   ```bash
   git rev-parse --is-inside-work-tree
   ```
   Must return `true`. If not, abort and tell the user to `git init`.

2. The repository has the expected name. Check `git remote -v` for an
   origin URL ending in `pipeline-ai-sandbox.git`. If not, **warn the
   user** and ask for explicit confirmation before continuing — this
   bundle is intended for the `pipeline-ai-sandbox` repo only.

3. The working tree is clean OR contains only this archive's files
   plus a `README.md`:
   ```bash
   git status --short
   ```
   If unrelated files are present, ask the user to stash them or
   confirm overwrite.

4. Your GitHub MCP credentials work:
   ```
   Invoke mcp__github__get_me
   ```
   Record the login. You'll need it later for `vars.AGENT_LOGIN`.

5. Verify Python 3.12 is available (or fall back to 3.11 if not):
   ```bash
   python --version
   ```

If any pre-flight step fails, abort and report the failure.

## Section 2 — file tree target

After install completes, the repo should contain:

```
pipeline-ai-sandbox/
  .claude/skills/
    batch-job/                 # full skill package
      SKILL.md
      templates/
        agent/...
        github/...
      lib/
      README.md
    task-dag/                  # same shape
    orchestrate-issue/         # same shape
    onboarding/                # same shape
    composition-guide/         # SKILL.md only
  test-harness/                # development-only test scaffolding
    SKILL.md
    SPEC.md
    archetypes/                # 8 archetypes
    scenarios/                 # 18 scenarios as YAML
    lib/                       # archetype loader, scenario runner, assertions
    runs/.gitkeep
  docs/                        # reference docs (copies from the POC's pipeline-skills-package/)
    OVERVIEW.md
    SPEC-PACKAGE.md
    skills/
      batch-job/SPEC.md
      task-dag/SPEC.md
      orchestrate-issue/SPEC.md
      onboarding/SPEC.md
      composition-guide/SPEC.md
    test-harness/SPEC.md
  bootstrap/
    install.md                 # this file, kept for reference
  NEW-REPO-PLAN.md             # the next step
  TESTING-IN-POC.md            # for reference (what was tested in the POC)
  README.md                    # written by NEW-REPO-PLAN.md Phase 1, not here
```

Note: README.md, AGENTS.md, CLAUDE.md, .github/workflows/, .agent/,
.gitignore, pytest.ini, etc. are **not** part of this bundle. They
get written by the dispatcher running `NEW-REPO-PLAN.md` Phase 1 and
Phase 2.

## Section 3 — install procedure

The bundle has already been extracted onto disk by `install.py`
(or by `tar -xzf` of the equivalent tarball form). `install.py`
performs sha256 integrity verification on its embedded payload
before extraction, so the bytes on disk are authentic if it exited 0.

Walk the tree and verify presence against Section 2's layout, then
run Section 4's verification.

### Conflict handling

`install.py` refuses to overwrite existing files whose content differs
from the bundle unless `--force` was passed. If you see file conflicts
reported by `install.py`, stop and surface them to the user before
proceeding. Identical files are silently skipped (idempotent re-runs).

For `README.md` specifically: it should not yet exist (Section 2 has
no README in the bundle). If it does, surface to the user.

`.gitignore` is in the same boat — if one exists, surface to user.

## Section 4 — verification (always run after install)

After all files are written (or verified present in tarball form):

1. Walk the file tree against the expected manifest:
   ```bash
   find .claude/skills -type f
   find test-harness -type f
   find docs -type f
   ```
   Compare to the manifest in `MANIFEST.txt` (also bundled).

2. Verify SKILL.md frontmatter for each of the 5 + 1 skills:
   - File starts with `---`
   - Has `name`, `description`, `allowed-tools` keys

3. Verify Python files compile:
   ```bash
   find test-harness -name "*.py" -exec python -m py_compile {} +
   find .claude/skills -name "*.py" -exec python -m py_compile {} +
   ```

4. Verify YAML files parse:
   ```bash
   find test-harness/scenarios -name "*.yml" | xargs -I {} python -c "import yaml; yaml.safe_load(open('{}'))"
   find test-harness/archetypes -name "manifest.json" | xargs -I {} python -c "import json; json.load(open('{}'))"
   ```

5. Print a verification summary to the user:
   ```
   pipeline-ai-sandbox bootstrap install report
   - Files written: <count>
   - Files matched manifest: <count>
   - SKILL.md frontmatter valid: 6/6
   - Python files compiled: <count>
   - YAML files parsed: <count>
   - Status: SUCCESS
   ```

If anything fails verification, surface it and stop. Do not advance
to Section 5.

## Section 5 — next step

After successful verification:

1. Make an initial commit:
   ```bash
   git add .
   git commit -m "bootstrap pipeline-ai-sandbox from pipeline-skills-package bundle"
   ```

2. Push to origin (if origin is configured):
   ```bash
   git push -u origin main
   ```

3. Tell the user:
   ```
   Bootstrap complete. Next step:

   Read NEW-REPO-PLAN.md at the repo root. It describes a
   long-running, parallel, overnight-executable plan to:
     - Scaffold the maintenance project (README, AGENTS.md, CI)
     - Self-install the agent-job protocol in this repo
     - Materialise and validate all test harness archetypes
     - Implement and drive all 18 scenarios against live GitHub
     - Dogfood orchestrate-issue end-to-end
     - Write a retrospective

   When you're ready to start: tell a Claude Code agent
     "Read NEW-REPO-PLAN.md and execute it. UNATTENDED=1 if you
     want overnight, otherwise interactive."
   ```

## Recovery

If install was interrupted mid-extract:

1. Re-run `python install.py`.
2. `install.py` is idempotent — files that already match the bundle
   content are silently skipped; conflicts are surfaced before any
   write happens.
3. Verification (Section 4) catches any partial writes.

Idempotency is a design goal — running install twice should be
safe.

## What this bundle does NOT do

- Set up `vars.AGENT_LOGIN` on the GitHub repo (`NEW-REPO-PLAN.md`
  Phase 0 handles that).
- Create the `agent-task` label (skills self-create on first install).
- Create the `_agent_runs` orphan branch (skills self-create).
- Configure GitHub Actions secrets (none required — uses default
  `GITHUB_TOKEN`).

## Provenance

This bundle was generated by `pipeline-skills-package/bootstrap/build.py`
in the POC repo `lago-morph/poc-github-ai-sandbox`. The manifest's
`generated_at` timestamp records when. Each bundled file's
`sha256` lives in `MANIFEST.txt`.

If you need to regenerate the bundle (because the POC source changed),
re-run the build script in the POC repo.
