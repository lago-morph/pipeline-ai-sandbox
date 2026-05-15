"""``run-tests`` command stub.

Pretends to run a suite and returns a fake-but-realistic summary that
conforms to ``commands/run-tests.schema.json``'s ``summary_completed``
shape. Streams a few records through ``log_writer`` so the manifest
contains real chunks.
"""

from __future__ import annotations

import random
from typing import Any

try:
    from ..scripts.common import iso_now  # type: ignore[import-not-found]
except (ImportError, ValueError):
    import os, sys
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
    from common import iso_now  # type: ignore[import-not-found]


def run(args: dict[str, Any], log_writer, workspace) -> dict[str, Any]:
    """Execute the (faked) test command.

    ``args`` is already validated against the command schema by the
    handler, so ``suite`` is guaranteed present.
    """
    suite = args["suite"]
    shard = args.get("shard")
    filter_ = args.get("filter")

    log_writer.write({
        "ts": iso_now(),
        "stream": "meta",
        "phase": "setup",
        "data": {
            "msg": "starting run-tests",
            "suite": suite,
            "shard": shard,
            "filter": filter_,
        },
    })

    # Deterministic-ish fake numbers based on suite size.
    base_counts = {"unit": 120, "integration": 40, "e2e": 12}
    total = base_counts.get(suite, 25)
    rng = random.Random(f"{suite}:{shard}:{filter_}")

    failed = rng.randint(0, max(1, total // 25))
    skipped = rng.randint(0, max(1, total // 30))
    passed = total - failed - skipped
    duration = round(rng.uniform(2.0, 12.0) + total * 0.1, 2)

    failed_tests: list[dict[str, str]] = []
    for i in range(failed):
        log_writer.write({
            "ts": iso_now(),
            "stream": "stdout",
            "phase": "exec",
            "data": f"FAIL test_{suite}_{i}",
        })
        failed_tests.append({
            "name": f"test_{suite}_{i}",
            "message": "AssertionError: synthetic failure",
        })

    log_writer.write({
        "ts": iso_now(),
        "stream": "stdout",
        "phase": "exec",
        "data": f"ran {total} {suite} tests in {duration}s",
    })
    log_writer.write({
        "ts": iso_now(),
        "stream": "meta",
        "phase": "teardown",
        "data": {"msg": "run-tests complete"},
    })

    return {
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
        "duration_seconds": duration,
        "failed_tests": failed_tests,
    }
