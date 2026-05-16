# Spec: `vendored-bundle-discipline`

## Intent

Some repos hold a vendored / bootstrap-installed code bundle whose source-of-truth lives elsewhere — `.claude/skills/`, a Git submodule, a `vendor/` directory, a downloaded distribution. Edits made directly in the consuming repo silently diverge from the source. The pattern repeats: a contributor finds a lint hit / type error / formatting drift in vendored code, "just fixes it inline", and the next bundle rebuild overwrites the fix without warning. This skill encodes the discipline: identify vendored paths, mark them non-editable in CI and lint config, and round-trip changes through the source.

In the `pipeline-ai-sandbox` bootstrap run, 27 of 29 ruff hits lived in vendored paths under `.claude/skills/*/templates/` and `.agent/` (self-installed copies of the bundle). The initial CI workflow used `continue-on-error: true` on the ruff step to swallow the noise. That made the workflow report "Success" while annotations showed two `exit code 1` per matrix leg. The fix was `extend-exclude` in `pyproject.toml` — applied retroactively after the user pointed at the green-with-red-annotations CI run.

## Trigger

**Direct triggers:**
- "These lint hits are in vendored code — how do I exempt them?"
- "Should I fix the type errors in `vendor/<x>`?"
- "Why is CI green but showing exit code 1 annotations?"
- "Set up lint for a repo with a bootstrap bundle."

**Proactive triggers:**
- A PR adds lint CI to a repo containing `.claude/skills/`, `vendor/`, `third_party/`, `templates/`, or any directory whose `README.md` says "do not edit; round-trip through `<source>`."
- A user adds `continue-on-error: true` to a lint/format/typecheck step.
- A `.gitignore` or `pyproject.toml` modification touches a vendored path.

**Negative triggers:**
- Pure consumer repo with no vendored code — skip.
- Vendored code already excluded from lint; nothing to do.

## Inputs

- Repo working tree.
- Known list of vendored paths (if available); else infer from `MANIFEST.txt`, `bootstrap/install.md`, `vendor/README.md`, or per-directory `README.md` files that say "do not edit."
- Existing lint/format/typecheck CI workflow (if any).

## Outputs

- A `[tool.<linter>]` (or equivalent) section in `pyproject.toml` / config file with `extend-exclude` (or per-linter equivalent) listing vendored paths.
- A `CONTRIBUTING.md` (or AGENTS.md) section documenting the round-trip rule.
- Removal of any `continue-on-error: true` on lint/format/typecheck steps (use config-level exclusion instead).
- Optional: a pre-commit hook or CI check that warns on edits to vendored paths.

## Workflow

1. **Identify vendored paths.** Look for any of:
   - A top-level `MANIFEST.txt` listing files with their source-of-truth.
   - A `bootstrap/install.md` or `vendor/README.md`.
   - Directories whose `README.md` opens with "do not edit" / "regenerated from".
   - Submodules (`git submodule status`).
   - Common conventions: `.claude/skills/*/templates/`, `vendor/`, `third_party/`, `node_modules/` (always vendored).
2. **Verify with the user** before treating ambiguous paths as vendored.
3. **Read the existing CI configs.** Find any lint/format/typecheck step with `continue-on-error: true`, `--exit-zero`, `|| true`, or equivalent — these mask the problem this skill solves.
4. **Configure the linter at the config level**, not the CI level. For ruff: add `extend-exclude = [...]` under `[tool.ruff]` in `pyproject.toml`. For mypy: `exclude = '...'` in `[tool.mypy]`. For flake8: `extend-exclude = ...` in `.flake8`. For prettier/eslint: `.prettierignore` / `.eslintignore`.
5. **Remove the CI bypass.** Drop `continue-on-error: true` (and `--exit-zero`, `|| true`) from the lint/format/typecheck steps.
6. **Verify locally.** Run the linter; the hit count should drop. Run with a deliberately-introduced lint error in vendored code; the linter should still skip it. Run with an introduced lint error in non-vendored code; it should fail.
7. **Document the rule** in `AGENTS.md` / `CONTRIBUTING.md`: "Files under `<vendored paths>` are vendored from `<source>`. Do not edit in this repo; round-trip changes through `<source>`."
8. **Optional pre-commit guard.** If the team has had repeated mishaps, add a pre-commit hook: `git diff --cached --name-only | grep -E '^(\.claude/skills/|vendor/)' && echo "vendored edits — round-trip via the POC" && exit 1`.

## Concrete examples

### Example 1 — `pipeline-ai-sandbox` (this session)

State before: `.github/workflows/test-harness-ci.yml` had `continue-on-error: true` on the ruff step; `ruff check .` produced 29 hits, 27 inside `.claude/skills/*/templates/` and `.agent/`.

Action:
```toml
# pyproject.toml — appended to [tool.ruff]
extend-exclude = [
    ".agent",
    ".claude/skills/*/templates",
]
```
```yaml
# .github/workflows/test-harness-ci.yml — change
      - name: Lint with ruff
-       continue-on-error: true
        run: ruff check .
```

Result: `ruff check .` exits 0 locally and in CI. The 2 hits in `test-harness/lib/` (this repo's own code) were independently fixed (unused `os` and `json` imports removed). PR merged.

### Example 2 — Node consumer with a `vendor/` directory

State before: ESLint reports 200+ hits in `vendor/`; team has `--fix` muscle memory but PRs keep showing `vendor/` diffs.

Action:
```
# .eslintignore — add
vendor/
```
```
# AGENTS.md — append section
## Vendored code
Files under `vendor/` are produced by `tools/vendor.sh`. Do not edit
them directly — make the change in the upstream source and re-run
the vendoring script.
```

Result: ESLint count drops to 0 in `vendor/`; PR review converges on real code.

## Anti-patterns

- **`continue-on-error: true` as a lint exemption.** Hides real signal under "Success". (Session: pre-fix CI run showed exit-1 annotations behind a Success badge.)
- **Excluding vendored code only in CI, not locally.** Developers' editor lint flags vendored hits and they get "fixed" — out of sync with CI. Config-level exclusion is read by both.
- **Treating "almost vendored" paths as editable.** A `.agent/` directory copied from `.claude/skills/orchestrate-issue/templates/` IS vendored even though it lives at a non-vendored path — its source-of-truth is upstream.
- **Editing vendored code "just this once."** It survives one bundle rebuild and silently disappears on the next.
- **No documentation in AGENTS.md.** Future contributors will repeat the mistake.

## Acceptance criteria

1. Linter (ruff/mypy/eslint/etc.) exits 0 locally and in CI.
2. No `continue-on-error: true` / `--exit-zero` / `|| true` on any lint/format/typecheck step.
3. `AGENTS.md` (or equivalent) names the vendored paths and the round-trip rule.
4. A deliberately-introduced lint error in vendored code is skipped; the same error in non-vendored code fails the build.
5. The exclusion is config-level, not CI-level (editors see it too).

## Files this skill creates / modifies

- `pyproject.toml` (or `.flake8`, `mypy.ini`, `.eslintignore`, etc.) — add `extend-exclude` for vendored paths.
- `.github/workflows/<lint-or-ci>.yml` — remove `continue-on-error: true` on the lint step.
- `AGENTS.md` or `CONTRIBUTING.md` — append the round-trip rule.
- Optionally `.pre-commit-config.yaml` or `.husky/pre-commit` — add a guard against vendored edits.
