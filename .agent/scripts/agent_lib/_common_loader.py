"""Locate and load the central ``common.py`` module by file path.

The agent-mode helpers run from many entry points (CLI, tests,
imported by subagents). We deliberately keep the import shape as
robust as ``skills/batch-job/common.py`` so a stray ``common`` already
in ``sys.modules`` does not break us.
"""

from __future__ import annotations

import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import ModuleType


def locate_repo_root(start: Path | None = None) -> Path:
    """Walk upwards from ``start`` looking for ``.agent/config.json``."""
    here = (start or Path(__file__)).resolve()
    candidates = [here] if here.is_dir() else [here.parent, *here.parents]
    for parent in candidates:
        if (parent / ".agent" / "config.json").exists():
            return parent
    raise RuntimeError("could not locate repo root (no .agent/config.json found)")


REPO_ROOT = locate_repo_root()
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def load_common() -> ModuleType:
    """Return the central agent-protocol ``common`` module, loaded once."""
    name = "agent_protocol_common"
    if name in sys.modules:
        return sys.modules[name]
    path = REPO_ROOT / ".agent" / "scripts" / "common.py"
    spec = spec_from_file_location(name, path)
    if spec is None or spec.loader is None:  # pragma: no cover - import path
        raise RuntimeError(f"could not load common module from {path}")
    mod = module_from_spec(spec)
    sys.modules[name] = mod  # register before exec so dataclasses work
    spec.loader.exec_module(mod)
    return mod
