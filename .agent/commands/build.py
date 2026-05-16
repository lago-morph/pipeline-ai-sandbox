"""``build`` command stub. Pretends to build a target."""

from __future__ import annotations

from typing import Any

try:
    from ..scripts.common import iso_now  # type: ignore[import-not-found]
except (ImportError, ValueError):
    import os, sys
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
    from common import iso_now  # type: ignore[import-not-found]


def run(args: dict[str, Any], log_writer, workspace) -> dict[str, Any]:
    target = args.get("target", "default")
    release = bool(args.get("release", False))

    log_writer.write({
        "ts": iso_now(),
        "stream": "meta",
        "phase": "setup",
        "data": {"msg": "build started", "target": target, "release": release},
    })
    log_writer.write({
        "ts": iso_now(),
        "stream": "stdout",
        "phase": "exec",
        "data": f"compiling {target}{' (release)' if release else ''}",
    })
    log_writer.write({
        "ts": iso_now(),
        "stream": "meta",
        "phase": "teardown",
        "data": {"msg": "build complete"},
    })

    artifact = f"build/out/{target}{'-release' if release else ''}.bin"
    return {
        "artifact_path": artifact,
        "size_bytes": 1024 * (4096 if release else 2048),
        "duration_seconds": 3.5 if release else 1.25,
    }
