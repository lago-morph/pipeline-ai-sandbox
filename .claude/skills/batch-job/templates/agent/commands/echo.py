"""``echo`` command: trivial demonstration handler.

Echoes its args back inside the summary. Useful for end-to-end POC
testing without depending on any synthetic test data.
"""

from __future__ import annotations

from typing import Any

try:
    from ..scripts.common import iso_now  # type: ignore[import-not-found]
except (ImportError, ValueError):
    import os, sys
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
    from common import iso_now  # type: ignore[import-not-found]


def run(args: dict[str, Any], log_writer, workspace) -> dict[str, Any]:
    message = str(args.get("message", "")) or "hello"
    log_writer.write({
        "ts": iso_now(),
        "stream": "stdout",
        "phase": "exec",
        "data": message,
    })
    return {
        "echoed_args": dict(args),
        "message": message,
    }
