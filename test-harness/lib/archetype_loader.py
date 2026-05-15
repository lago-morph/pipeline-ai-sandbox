"""Materialise an archetype's snapshot tree into a fixture directory."""
from __future__ import annotations

import json
import shutil
from pathlib import Path


ARCHETYPES_ROOT = Path("test-harness/archetypes")


def archetype_path(name: str) -> Path:
    p = ARCHETYPES_ROOT / name
    if not p.is_dir():
        valid = sorted(c.name for c in ARCHETYPES_ROOT.iterdir() if c.is_dir())
        raise FileNotFoundError(
            f"archetype not found: {name!r}. Valid archetypes: {valid}"
        )
    return p


def load_manifest(name: str) -> dict:
    return json.loads((archetype_path(name) / "manifest.json").read_text())


def materialise(name: str, dest: Path) -> dict:
    """Copy an archetype's files to `dest`. Returns manifest.

    `dest` is created fresh; any pre-existing contents are removed.
    """
    src = archetype_path(name)
    manifest = load_manifest(name)
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    for rel in manifest.get("files", []):
        src_file = src / rel
        if not src_file.is_file():
            raise FileNotFoundError(
                f"manifest references missing file {rel} for archetype {name}"
            )
        dst_file = dest / rel
        dst_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_file, dst_file)
    return manifest
