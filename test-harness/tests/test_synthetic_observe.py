"""Unit tests for synthetic-fixture observations."""
from __future__ import annotations


import pytest

import synthetic_observe


@pytest.fixture()
def blank_fixture(tmp_path):
    """A bare fixture dir — no protocol, no AGENTS.md."""
    return tmp_path


@pytest.fixture()
def installed_fixture(tmp_path):
    """A fixture with protocol installed but no onboarding marker."""
    (tmp_path / ".agent").mkdir()
    (tmp_path / ".agent" / "config.json").write_text('{"protocol_version": 1}')
    return tmp_path


@pytest.fixture()
def onboarded_fixture(tmp_path):
    """A fixture with both protocol AND an onboarding marker, plus AGENTS.md."""
    (tmp_path / ".agent" / "installs").mkdir(parents=True)
    (tmp_path / ".agent" / "config.json").write_text('{"protocol_version": 1}')
    (tmp_path / ".agent" / "installs" / "onboarding.log").write_text("done")
    (tmp_path / "AGENTS.md").write_text("# agents")
    (tmp_path / "CLAUDE.md").write_text("# claude")
    return tmp_path


class TestObserveFixture:
    def test_blank_fixture(self, blank_fixture):
        out = synthetic_observe._observe_fixture(blank_fixture)
        assert out["agents_md_present"] is False
        assert out["claude_md_present"] is False
        assert out["protocol_installed"] is False
        assert out["onboarding_started"] is False
        assert out["installed_but_not_onboarded"] is False

    def test_installed_but_not_onboarded(self, installed_fixture):
        out = synthetic_observe._observe_fixture(installed_fixture)
        assert out["protocol_installed"] is True
        assert out["onboarding_started"] is False
        assert out["installed_but_not_onboarded"] is True

    def test_fully_onboarded(self, onboarded_fixture):
        out = synthetic_observe._observe_fixture(onboarded_fixture)
        assert out["protocol_installed"] is True
        assert out["onboarding_started"] is True
        assert out["agents_md_present"] is True
        assert out["claude_md_present"] is True
        assert out["installed_but_not_onboarded"] is False


class TestObserveCompositionGuide:
    def test_returns_keys(self):
        out = synthetic_observe._observe_composition_guide()
        # All catalogue keys present regardless of repo state.
        for key in (
            "frontmatter_parses",
            "markdown_renders",
            "no_broken_internal_links",
            "no_broken_external_links",
            "all_referenced_skills_exist",
        ):
            assert key in out


class TestGenericObserve:
    def test_returns_fixture_and_skill_keys(self, blank_fixture):
        out = synthetic_observe.generic_observe(
            "detect", {}, blank_fixture, {}, expected_keys=None
        )
        # Fixture-derived keys present.
        assert "agents_md_present" in out
        # Composition-guide keys also present.
        assert "frontmatter_parses" in out

    def test_skips_phase_with_non_synthetic_keys(self, blank_fixture):
        with pytest.raises(NotImplementedError) as exc:
            synthetic_observe.generic_observe(
                "invoke",
                {},
                blank_fixture,
                {},
                expected_keys=["envelope_run_status"],
            )
        assert "requires-live-skill-execution" in str(exc.value)
        assert "envelope_run_status" in str(exc.value)

    def test_passes_when_all_keys_in_catalogue(self, blank_fixture):
        out = synthetic_observe.generic_observe(
            "detect",
            {},
            blank_fixture,
            {},
            expected_keys=["protocol_installed", "agents_md_present"],
        )
        assert out["protocol_installed"] is False

    def test_empty_expected_keys_does_not_skip(self, blank_fixture):
        out = synthetic_observe.generic_observe(
            "any", {}, blank_fixture, {}, expected_keys=[]
        )
        assert isinstance(out, dict)

    def test_none_expected_keys_does_not_skip(self, blank_fixture):
        out = synthetic_observe.generic_observe(
            "any", {}, blank_fixture, {}, expected_keys=None
        )
        assert isinstance(out, dict)


class TestSyntheticCatalogue:
    def test_catalogue_contains_known_keys(self):
        for key in ("protocol_installed", "agents_md_present", "frontmatter_parses"):
            assert key in synthetic_observe.SYNTHETIC_CATALOGUE

    def test_catalogue_excludes_live_keys(self):
        for key in (
            "envelope_run_status",
            "batch_job_comment_present",
            "issue_number_present",
        ):
            assert key not in synthetic_observe.SYNTHETIC_CATALOGUE
