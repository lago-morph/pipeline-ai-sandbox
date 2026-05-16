"""``bad-summary`` test command — intentionally returns invalid summary.

Used by harness scenario 07 (``07_summary_schema_violation.md``) to
exercise the handler's defense-in-depth ``summary_schema_violation``
path. The schema demands ``required_field`` in the completed summary,
but this handler returns ``{}`` so the validator must reject it.
"""

from __future__ import annotations

from typing import Any

try:
    from ..scripts.common import iso_now  # type: ignore[import-not-found]
except (ImportError, ValueError):
    import os, sys
    sys.path.insert(0, os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"
    ))
    from common import iso_now  # type: ignore[import-not-found]


def run(args: dict[str, Any], log_writer, workspace) -> dict[str, Any]:
    log_writer.write({
        "ts": iso_now(),
        "stream": "stdout",
        "phase": "exec",
        "data": "bad-summary about to return invalid summary",
    })
    # Intentionally missing the schema-required ``required_field``.
    return {}
