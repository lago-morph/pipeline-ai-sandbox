# TESTING-IN-POC — partial-testing strategy

Status: design-stage
Audience: implementers of the contract tests + dispatcher running `PLAN-PACKAGE.md`

> Read `OVERVIEW.md` and `SPEC-PACKAGE.md` first. This file
> describes what CAN and what CANNOT be tested in this POC repo,
> and how to structure the partial-testing work to maximise
> coverage without disrupting the POC.

## The constraint

The POC repo (`poc-github-ai-sandbox`) is preserved as a proof of
concept. Modifying its operational files (`.agent/`,
`.github/workflows/`, `_agent_runs` branch, existing `skills/batch-job/`,
existing `skills/task-dag/`, existing `tests/unit/`, existing
`tests/e2e/`) is forbidden by this work's scope.

This places a hard ceiling on what can be tested here:

- **Yes**: contract tests, schema validation, dry-run install logic, mock-based unit tests, lint/round-trip tests of the bundle.
- **No**: live skill execution against real GitHub from this repo, end-to-end onboarding interview, parallel subagent fanout exercising the actual protocol workflows.

The "no" items are covered in the new `pipeline-ai-sandbox` repo by
the test harness (see `test-harness/SPEC.md` + `NEW-REPO-PLAN.md`).

Accept this. The remainder is meaningful coverage, not theater.

## Test surface (in this POC)

All new tests live under `tests/distribution/`. The POC's
`pytest.ini` has `testpaths = tests`, so `tests/distribution/` is
picked up automatically. The existing 446 POC tests under
`tests/unit/` and `tests/e2e/` remain untouched.

The new test directory:

```
tests/distribution/
  __init__.py
  conftest.py                       # fixtures: POC source paths, bundle paths
  test_template_parity.py           # bundled templates byte-match POC source
  test_schema_validity.py           # bundled JSON schemas are Draft 2020-12 valid
  test_skill_md_frontmatter.py      # every SKILL.md parses + has required keys
  test_install_dry_run.py           # mock filesystem install logic
  test_recipe_idempotent.py         # apply recipe twice = no-op second time
  test_archive_round_trip.py        # tarball extract == recipe apply
  test_bundle_contents.py           # manifest matches actual bundle contents
  test_no_secrets_in_bundle.py      # no secret patterns in any bundled file
  test_distribution_excludes.py     # distribution-exclude.txt is honored
  test_bundle_size.py               # bundle stays under reasonable size cap
  test_workflow_yaml_syntax.py      # bundled GHA YAMLs parse + validate against schema
  test_python_syntax.py             # every bundled .py file imports without syntax errors
  test_onboarding_questions.py      # interview-questions.yml schema + tree completeness
  test_archetype_manifests.py       # test-harness archetypes have valid manifests
  test_scenario_yamls.py            # test-harness scenarios have valid spec
  fixtures/
    fake_repos/                     # synthetic repo trees for dry-run install tests
      blank-repo/
      with-agents-md/
      with-conflicting-skill/
    expected_recipe_excerpts/       # expected snippets in the generated recipe
```

## Per-test detail

### `test_template_parity.py`

```python
# For each skill that bundles templates:
#   For each path in the skill's templates/ tree:
#     The bundled file's bytes must equal the POC source file's bytes.
#
# Skills checked: batch-job, task-dag, orchestrate-issue, onboarding
# (composition-guide bundles nothing; test-harness bundles non-POC files)
```

This is the **most important** test in this directory. If it fails,
the POC source has drifted from the bundled copies and the next
build must re-sync.

### `test_schema_validity.py`

Every bundled `*.schema.json` file:

- Is valid JSON
- Has `$schema` set to `https://json-schema.org/draft/2020-12/schema`
- Validates against the meta-schema (use `jsonschema.Draft202012Validator.check_schema(...)`)

### `test_skill_md_frontmatter.py`

Each `SKILL.md` in the bundle:

- Has a leading `---` YAML frontmatter block
- Frontmatter contains `name`, `description`, `allowed-tools`
- `name` matches the directory name
- `description` is non-empty
- `allowed-tools` is a list of strings

### `test_install_dry_run.py`

For each skill that self-installs, simulate the install against a
synthetic empty repo (under `fixtures/fake_repos/blank-repo/`) using
a mocked filesystem (`tmp_path` fixture). Assert:

- The skill identifies the correct file list to copy.
- After install, every expected file is present at its expected path.
- Re-running the install on the same fixture is a no-op (idempotent).

Also test conflict handling:

- Pre-create one of the target files with different content under `fixtures/fake_repos/with-conflicting-skill/`.
- Run the install in a mode that simulates "user chose: skip".
- Assert the pre-existing file is untouched and the install log records the skip.

### `test_recipe_idempotent.py`

Apply the recipe's instructions against an empty fixture directory.
Then apply them again. Second application:

- Detects every file already exists with matching content.
- Performs zero writes.
- Reports "no changes" cleanly.

This tests that an interrupted bootstrap install can be resumed
safely.

### `test_archive_round_trip.py`

Extract the bundled tarball to a temp directory. Apply the bundled
recipe to a different temp directory. Compare the two trees:

- Same file list.
- Same file contents (bytewise).
- Same permissions where preservable.

### `test_bundle_contents.py`

Read `bootstrap/dist/MANIFEST.txt`. Walk the tarball. Walk the
recipe-extracted tree. Three views must agree:

- Same file paths
- Same sha256 sums

### `test_no_secrets_in_bundle.py`

For every bundled file, scan for patterns matching common secret
shapes (PAT, AWS key, JWT, GitHub token prefixes, password assignments,
private key headers). Use a small allowlist for known-safe matches
(e.g., schema examples).

This is a smoke test, not a security guarantee. It prevents the
most obvious leaks.

### `test_distribution_excludes.py`

Read `bootstrap/distribution-exclude.txt`. Verify every excluded
path/pattern is honored:

- `pipeline-skills-package/runs/` is NOT in the bundle.
- `pipeline-skills-package/bootstrap/dist/` is NOT in the bundle (no recursion).
- `PLAN-PACKAGE.md` and `RESUME.md` are NOT in the bundle.

### `test_bundle_size.py`

The total bundle size should stay under a reasonable cap. Soft cap
~10 MB; hard cap 50 MB. Exceeding the hard cap fails the test.

### `test_workflow_yaml_syntax.py`

Each bundled `.github/workflows/*.yml` template:

- Parses as YAML
- Validates against the GitHub Actions workflow schema
- Has the `${{ vars.AGENT_LOGIN || 'jonathanmanton' }}` fallback (regression test for PR #56 in the POC)

### `test_python_syntax.py`

Every bundled `.py` file:

- Parses with `ast.parse`
- Has no syntax errors

Does **not** import the modules (they may have external dependencies
not satisfied in the test environment); just check syntax.

### `test_onboarding_questions.py`

`interview-questions.yml`:

- Parses as YAML
- Has the 6 expected top-level categories (intent, problems, current-workflow, integration-preferences, sensitive-files, confirmation)
- Each question has `id`, `text`, `type`, and optional `branches`
- No duplicate question IDs

### `test_archetype_manifests.py`

For each archetype under `test-harness/archetypes/`:

- `manifest.json` parses
- Lists every file in the archetype directory
- Notes expected discovery outputs

### `test_scenario_yamls.py`

For each scenario under `test-harness/scenarios/`:

- YAML parses
- References a valid archetype name
- References a valid skill name
- Has at least one phase
- Phase names are unique within a scenario

## Test categories: what they cover vs don't

| Category | Covered here | Deferred to new repo |
|---|---|---|
| Template content correctness | ✅ byte-match against POC source | Live execution of templates |
| Schema validity | ✅ all schemas valid | Live envelope round-trip |
| SKILL.md format | ✅ frontmatter present + valid | Skill-tool routing in Claude Code |
| Install logic — dry run | ✅ mock filesystem | Live install in real repo |
| Bundle round-trip | ✅ recipe vs tarball byte-equal | User actually copying + extracting |
| No secrets | ✅ pattern scan | Threat-model security review |
| Workflow YAML syntax | ✅ parse + schema | Actual GitHub Actions execution |
| Python syntax | ✅ ast.parse | Runtime behaviour |
| Onboarding interview content | ✅ structure | Live interview with user |
| Archetype + scenario YAMLs | ✅ structure | Live scenario execution |

## Running the tests

```bash
# All distribution tests
python -m pytest tests/distribution/ -v --tb=short

# All POC tests (includes distribution)
python -m pytest tests/ -q --tb=short
```

The POC's existing 446 tests must continue to pass. The new
distribution tests add to that baseline. The expected total after
implementation: 446 + ~25-40 new tests = ~470-485 passing.

## Coverage targets

| Module | POC coverage | New target |
|---|---|---|
| Existing `.agent/`, `skills/`, `harness/lib/` | ~93% | Unchanged |
| `pipeline-skills-package/bootstrap/build.py` | N/A | ≥90% |
| `pipeline-skills-package/skills/*/lib/` | N/A | tested transitively via dry-run install + contract tests; full coverage in new repo |

## What NOT to do in this POC

- **Don't** invoke any of the 5 distributable skills against a real
  GitHub repo from this sandbox. That is the new repo's test harness's
  job, not this POC's.
- **Don't** test the full onboarding interview interactively. The
  interview-state-machine unit tests are sufficient here.
- **Don't** install the bundle into this POC repo to test it
  end-to-end. The POC already has a working install of the protocol
  via its `.agent/`; installing the bundled version on top would
  conflict.
- **Don't** modify any of the POC's existing tests.

## Failure handling

If `tests/distribution/` fails:

1. The build (Phase 4 in `PLAN-PACKAGE.md`) aborts.
2. The dispatcher updates `runs/<run_id>/state.json` with the failure.
3. The dispatcher writes a remediation note in the run report.
4. The bundle is **not shipped** until tests pass.

If `tests/unit/` or `tests/e2e/` (existing POC tests) start failing
during this work:

1. **Something in the new code touched the POC.** This is a serious
   violation of scope.
2. Abort immediately and surface to the user.
3. Identify and revert the offending change.

## Integration with `PLAN-PACKAGE.md`

Phase 4 of the build plan runs these tests. The plan's success
criterion is "all tests pass." Until they do, the bundle is not
considered built.

## Integration with `NEW-REPO-PLAN.md`

The full test surface (live execution, real GitHub, interactive
onboarding) is covered in the new repo by the test harness. The
distribution tests run here are the **gate** — only after they
pass does the bundle become shippable to the new repo.
