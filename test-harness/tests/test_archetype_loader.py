"""Unit tests for archetype materialisation."""
from __future__ import annotations

import json

import pytest

import archetype_loader


@pytest.fixture()
def fake_archetypes(tmp_path, monkeypatch):
    """Construct a fake archetypes root with one archetype and chdir there."""
    root = tmp_path / "test-harness" / "archetypes"
    arche = root / "tiny"
    (arche / "src").mkdir(parents=True)
    (arche / "src" / "hello.txt").write_text("hi")
    (arche / "README.md").write_text("# hi")
    (arche / "manifest.json").write_text(
        json.dumps(
            {
                "name": "tiny",
                "files": ["README.md", "src/hello.txt"],
                "expected_discovery": {"language": "txt"},
            }
        )
    )
    # Second archetype to make "valid list" assertions non-trivial.
    other = root / "other"
    other.mkdir()
    (other / "manifest.json").write_text(json.dumps({"name": "other", "files": []}))
    monkeypatch.chdir(tmp_path)
    return tmp_path


class TestArchetypePath:
    def test_returns_existing_path(self, fake_archetypes):
        p = archetype_loader.archetype_path("tiny")
        assert p.is_dir()

    def test_unknown_archetype_raises(self, fake_archetypes):
        with pytest.raises(FileNotFoundError) as exc:
            archetype_loader.archetype_path("nope")
        assert "tiny" in str(exc.value) and "other" in str(exc.value)


class TestLoadManifest:
    def test_returns_parsed_json(self, fake_archetypes):
        m = archetype_loader.load_manifest("tiny")
        assert m["name"] == "tiny"
        assert m["expected_discovery"] == {"language": "txt"}


class TestMaterialise:
    def test_copies_listed_files(self, tmp_path, fake_archetypes):
        dest = tmp_path / "fixture"
        manifest = archetype_loader.materialise("tiny", dest)
        assert manifest["name"] == "tiny"
        assert (dest / "README.md").is_file()
        assert (dest / "src" / "hello.txt").read_text() == "hi"

    def test_resets_existing_dest(self, tmp_path, fake_archetypes):
        dest = tmp_path / "fixture"
        dest.mkdir()
        (dest / "stale.txt").write_text("old")
        archetype_loader.materialise("tiny", dest)
        assert not (dest / "stale.txt").exists()
        assert (dest / "README.md").is_file()

    def test_raises_on_missing_listed_file(self, tmp_path, fake_archetypes):
        # Corrupt the manifest to reference a file we know doesn't exist.
        arche = fake_archetypes / "test-harness" / "archetypes" / "tiny"
        (arche / "manifest.json").write_text(
            json.dumps({"name": "tiny", "files": ["READ-NOT-ME.md"]})
        )
        with pytest.raises(FileNotFoundError):
            archetype_loader.materialise("tiny", tmp_path / "fixture")

    def test_handles_empty_files_list(self, tmp_path, fake_archetypes):
        dest = tmp_path / "fixture"
        manifest = archetype_loader.materialise("other", dest)
        assert manifest["name"] == "other"
        assert dest.is_dir()
        # No files copied.
        assert list(dest.iterdir()) == []
