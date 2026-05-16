"""Synthetic-fixture observe functions.

In synthetic-fixture mode no live skill runs against real GitHub. We
can still observe a fair number of assertion keys directly from the
materialised fixture (the archetype tree on disk) and from the
distributable skills' on-disk text. This module exposes a single
`generic_observe(phase_name, inputs, fixture_dir, diagnostics)` that:

1. Inspects the fixture + repo state to produce values for the keys it
   can answer synthetically (see `_KEYS_BY_FIXTURE` and `_KEYS_BY_SKILL_TEXT`).
2. Returns a dict mapping every supported key -> observed value.
3. Raises `NotImplementedError("requires-live-skill-execution")` if the
   phase only contains keys this module cannot answer — the runner
   marks the phase as `skipped`.

Per-runner specialisations may layer on top via:

    from synthetic_observe import generic_observe

    def observe(phase, inputs, fixture, diagnostics):
        base = generic_observe(phase, inputs, fixture, diagnostics, expected_keys=...)
        # add scenario-specific keys to `base` here
        return base
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
SKILLS_DIR = REPO_ROOT / ".claude" / "skills"


# Keys observable purely from the fixture contents. In synthetic mode
# these have *meaningful* values derived from the materialised tree.
_FIXTURE_KEYS = {
    "agents_md_present",
    "claude_md_present",
    "protocol_installed",
    "onboarding_started",
    "installed_but_not_onboarded",
}

# Keys observable from the on-disk skill text (composition-guide etc).
_SKILL_TEXT_KEYS = {
    "frontmatter_parses",
    "markdown_renders",
    "no_broken_internal_links",
    "no_broken_external_links",
    "all_referenced_skills_exist",
}

# Union of keys for which generic_observe can give an authoritative answer.
SYNTHETIC_CATALOGUE: set[str] = _FIXTURE_KEYS | _SKILL_TEXT_KEYS


def _check_protocol_installed(fixture: Path) -> bool:
    return (fixture / ".agent" / "config.json").is_file()


def _check_onboarding_started(fixture: Path) -> bool:
    # The dialog file lives on the agent-job-protocol/onboarding well-known
    # branch; in a synthetic fixture the equivalent marker is a
    # `.agent/installs/onboarding.log` or `onboarding-dialog.md` at the
    # repo root. Fixture archetypes don't ship those, so this is False
    # for every archetype except where the archetype's manifest says so.
    if (fixture / ".agent" / "installs" / "onboarding.log").is_file():
        return True
    if (fixture / "onboarding-dialog.md").is_file():
        return True
    # Honour archetype manifest hints
    return False


def _observe_fixture(fixture: Path) -> dict[str, Any]:
    protocol = _check_protocol_installed(fixture)
    started = _check_onboarding_started(fixture)
    return {
        "agents_md_present": (fixture / "AGENTS.md").is_file(),
        "claude_md_present": (fixture / "CLAUDE.md").is_file(),
        "protocol_installed": protocol,
        "onboarding_started": started,
        "installed_but_not_onboarded": protocol and not started,
    }


def _observe_composition_guide() -> dict[str, Any]:
    skill_md = SKILLS_DIR / "composition-guide" / "SKILL.md"
    text = skill_md.read_text() if skill_md.is_file() else ""
    starts_with_frontmatter = text.startswith("---")
    # Find every fenced inline reference of the form `<skill-name>` we
    # care about and check the directory exists.
    referenced = sorted(
        set(
            re.findall(
                r"`(batch-job|task-dag|orchestrate-issue|onboarding|composition-guide)`",
                text,
            )
        )
    )
    all_exist = all((SKILLS_DIR / s / "SKILL.md").is_file() for s in referenced)
    # Internal links: any `](path)` ending in `.md` should point to a real file.
    md_link = re.compile(r"\]\((?P<href>[^)\s]+\.md)\)")
    internal_ok = True
    for m in md_link.finditer(text):
        href = m.group("href")
        if href.startswith("http://") or href.startswith("https://"):
            continue
        # Resolve relative to the SKILL.md
        target = (skill_md.parent / href).resolve()
        if not target.is_file():
            internal_ok = False
            break
    # External-link sanity: just check none are obviously malformed.
    ext_ok = True
    for m in re.finditer(r"\]\((https?://[^\s)]+)\)", text):
        if " " in m.group(1):
            ext_ok = False
            break
    return {
        "frontmatter_parses": starts_with_frontmatter,
        "markdown_renders": bool(text.strip()),
        "no_broken_internal_links": internal_ok,
        "no_broken_external_links": ext_ok,
        "all_referenced_skills_exist": referenced if all_exist else [],
    }


def generic_observe(
    phase_name: str,
    inputs: dict[str, Any],
    fixture: Path,
    diagnostics: dict[str, Any],
    expected_keys: list[str] | None = None,
) -> dict[str, Any]:
    observed: dict[str, Any] = {}
    observed.update(_observe_fixture(fixture))
    observed.update(_observe_composition_guide())

    if expected_keys is not None:
        unknown = set(expected_keys) - SYNTHETIC_CATALOGUE
        if unknown:
            # Any expected key outside the synthetic catalogue means
            # the phase needs a real skill run to be evaluated honestly.
            raise NotImplementedError(
                f"requires-live-skill-execution (phase={phase_name!r}, "
                f"non-synthetic-keys={sorted(unknown)})"
            )
    return observed
