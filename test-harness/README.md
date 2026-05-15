# test-harness

This is the **test-harness DEVELOPMENT-ONLY skill**. Entry point:
[`SKILL.md`](./SKILL.md).

It drives the 5 distributable skills (`batch-job`, `task-dag`,
`orchestrate-issue`, `onboarding`, `composition-guide`) against
synthetic archetypes and the live new repo. **NOT for end-user
distribution.**

See also:

- [`SPEC.md`](./SPEC.md) — long-form design spec
- [`archetypes/`](./archetypes/) — 8 archetype fixture trees
- [`scenarios/`](./scenarios/) — 18 scenario YAML specs
- [`lib/`](./lib/) — Python helpers (`archetype_loader.py`,
  `scenario_runner.py`, `assertions.py`, `state.py`)
- [`runs/`](./runs/) — per-run state directory (gitkeep'd)
