"""Tests for SyntheticOnboardingObserver — covers all 4 onboarding modes."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def _common_loadable():
    p = REPO_ROOT / ".agent" / "scripts" / "common.py"
    spec = importlib.util.spec_from_file_location("_harness_agent_common", p)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("_harness_agent_common", mod)
    spec.loader.exec_module(mod)
    yield


class TestConstruction:
    def test_rejects_bad_mode(self):
        import synthetic_drivers

        with pytest.raises(ValueError, match="mode"):
            synthetic_drivers.SyntheticOnboardingObserver(mode="bogus")

    def test_requires_agent_login(self):
        import synthetic_drivers

        with pytest.raises(ValueError, match="agent_login"):
            synthetic_drivers.SyntheticOnboardingObserver(
                mode="decline", agent_login=""
            )


class TestDeclineMode:
    def test_decline_writes_no_state(self, tmp_path):
        import synthetic_drivers

        obs = synthetic_drivers.SyntheticOnboardingObserver(mode="decline")
        # No setup phase asserts; jump to detect.
        obs("detect", {}, tmp_path, {})
        interview_out = obs(
            "interview",
            {"scripted_answers": {"decline": True}},
            tmp_path,
            {},
        )
        assert interview_out["decline_acknowledged"] is True
        verify_out = obs("verify", {}, tmp_path, {})
        assert verify_out["dialog_file_present"] is False
        assert verify_out["recommendations_file_present"] is False
        assert verify_out["no_state_written"] is True


class TestExistingAgentsMdMode:
    def test_pointer_only_adoption(self, tmp_path):
        import synthetic_drivers

        # Seed AGENTS.md + CLAUDE.md so the "body unchanged" check
        # has real content.
        (tmp_path / "AGENTS.md").write_text("# AGENTS\n\nExisting body content.\n")
        (tmp_path / "CLAUDE.md").write_text("# CLAUDE\n\nUntouched.\n")
        obs = synthetic_drivers.SyntheticOnboardingObserver(
            mode="existing_agents_md"
        )
        obs("detect", {}, tmp_path, {})
        interview_out = obs(
            "interview",
            {"scripted_answers": {"adoption": "pointer-only"}},
            tmp_path,
            {},
        )
        assert interview_out["dialog_file_present"] is True
        # Honour the min-threshold semantics (literal-12 when met).
        assert interview_out["questions_answered_min"] == 12
        rec_out = obs("recommend", {}, tmp_path, {})
        assert rec_out["recommendations_file_present"] is True
        assert rec_out["no_agents_md_edits_proposed"] is True
        assert rec_out["pointer_edit_proposed"] is True
        apply_out = obs("apply", {"approve_all": True}, tmp_path, {})
        assert apply_out["pointer_added_to_agents_md"] is True
        assert apply_out["agents_md_body_unchanged"] is True
        verify_out = obs("verify", {}, tmp_path, {})
        assert verify_out["meta_status"] == "onboarded"
        assert verify_out["claude_md_body_unchanged"] is True


class TestResumeMode:
    def test_resume_continues_from_recorded_index(self, tmp_path):
        import synthetic_drivers

        obs = synthetic_drivers.SyntheticOnboardingObserver(mode="resume")
        setup_out = obs(
            "setup",
            {"preexisting_dialog_questions_answered": 13},
            tmp_path,
            {},
        )
        assert setup_out["dialog_file_present"] is True
        assert setup_out["questions_answered"] == 13
        detect_out = obs("detect", {}, tmp_path, {})
        assert detect_out["onboarding_started"] is True
        assert detect_out["resume_point_index"] == 14
        interview_out = obs(
            "interview",
            {"mode": "resume", "scripted_answers_from": 14},
            tmp_path,
            {},
        )
        assert interview_out["questions_answered"] == 22
        assert interview_out["no_questions_re_asked"] is True
        obs("recommend", {}, tmp_path, {})
        verify_out = obs("verify", {}, tmp_path, {})
        assert verify_out["meta_status"] == "onboarded"


class TestReviseMode:
    def test_revise_records_revision_and_applies(self, tmp_path):
        import synthetic_drivers

        obs = synthetic_drivers.SyntheticOnboardingObserver(mode="revise")
        setup_out = obs("setup", {}, tmp_path, {})
        assert setup_out["dialog_file_present"] is True
        assert setup_out["recommendations_file_present"] is True
        detect_out = obs("detect", {}, tmp_path, {})
        assert detect_out["protocol_installed"] is True
        assert detect_out["onboarding_started"] is True
        assert detect_out["revise_offered"] is True
        interview_out = obs(
            "interview",
            {
                "mode": "revise",
                "scripted_answers": {"change_integration": "switch to full"},
            },
            tmp_path,
            {},
        )
        assert interview_out["dialog_revision_recorded"] is True
        rec_out = obs("recommend", {}, tmp_path, {})
        assert rec_out["recommendations_diff_present"] is True
        apply_out = obs("apply", {}, tmp_path, {})
        assert apply_out["revised_integration_applied"] is True
        verify_out = obs("verify", {}, tmp_path, {})
        assert verify_out["meta_status"] == "onboarded"
        assert verify_out["revision_count"] == 1


class TestUnknownPhase:
    def test_unknown_phase_raises(self, tmp_path):
        import synthetic_drivers

        obs = synthetic_drivers.SyntheticOnboardingObserver(mode="decline")
        with pytest.raises(ValueError, match="unknown phase"):
            obs("nope", {}, tmp_path, {})


class TestRunnerCLIs:
    def test_runners_import_with_right_scenario_id(self):
        import importlib

        for runner_name in (
            "onboarding-decline",
            "onboarding-existing-agents-md",
            "onboarding-resume-mid-interview",
            "onboarding-revise",
        ):
            mod_path = REPO_ROOT / "test-harness" / "runners" / f"{runner_name}.py"
            spec = importlib.util.spec_from_file_location(
                f"_runner_{runner_name.replace('-', '_')}", mod_path
            )
            assert spec is not None
            mod = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = mod
            spec.loader.exec_module(mod)
            assert mod.SCENARIO_ID == runner_name


class TestDialogPersistence:
    def test_dialog_file_layout(self, tmp_path):
        """Dialog file lives at .agent/onboarding/dialog.json — verifies
        the expected on-disk layout."""
        import synthetic_drivers

        obs = synthetic_drivers.SyntheticOnboardingObserver(mode="resume")
        obs("setup", {"preexisting_dialog_questions_answered": 5}, tmp_path, {})
        dialog_path = tmp_path / ".agent" / "onboarding" / "dialog.json"
        assert dialog_path.is_file()
        data = json.loads(dialog_path.read_text())
        assert data["questions_answered"] == 5
        assert data["mode"] == "resume"
