"""``chatty`` test command — emits many log records to force chunk rotation.

Used by harness scenario 12 (``12_huge_log.md``). Args:

- ``lines`` (int, default 500): number of log records to emit.
- ``max_chunk_bytes_compressed`` (int, default 8192): rotation threshold
  applied to the LogWriter for this invocation only. The production
  default (524 288 bytes) remains untouched for non-test commands.

Rationale: live execution showed that triggering rotation at the full
production threshold required ~20 000 lines, which is timing-sensitive
and slow on real GitHub Actions runners. Lowering the per-invocation
threshold for the test command makes rotation fire reliably with a
modest line count, while production defaults are preserved because
chatty calls :py:meth:`LogWriter.set_max_chunk_bytes` itself rather
than mutating any shared config.

Each emitted record carries a high-entropy (per-line unique) payload so
that gzip cannot dedupe the stream down below the rotation threshold —
without this, 500 highly-repetitive lines compressed to <8 KB and never
rotated.
"""

from __future__ import annotations

import hashlib
from typing import Any

try:
    from ..scripts.common import iso_now  # type: ignore[import-not-found]
except (ImportError, ValueError):
    import os, sys
    sys.path.insert(0, os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"
    ))
    from common import iso_now  # type: ignore[import-not-found]


def _entropy_payload(i: int, length: int = 192) -> str:
    """Build a high-entropy, per-line-unique string of ~``length`` chars.

    gzip compresses repeated text aggressively, so a constant pad would
    let 500 lines compress well below an 8 KiB rotation threshold. We
    derive a chain of SHA-256 hex digests seeded by ``i`` and concatenate
    them — this is effectively incompressible and grows linearly with
    line count.
    """
    out_parts: list[str] = []
    seed = f"chatty-line-{i:08d}".encode("utf-8")
    h = hashlib.sha256(seed).hexdigest()  # 64 hex chars
    out_parts.append(h)
    while sum(len(p) for p in out_parts) < length:
        h = hashlib.sha256(h.encode("utf-8")).hexdigest()
        out_parts.append(h)
    return "-".join(out_parts)[:length]


def run(args: dict[str, Any], log_writer, workspace) -> dict[str, Any]:
    # Override the rotation threshold up-front so every record we emit
    # is governed by the test-friendly size.
    max_chunk = int(args.get("max_chunk_bytes_compressed", 8192))
    log_writer.set_max_chunk_bytes(max_chunk)

    n = int(args.get("lines", 500))
    if n < 0:
        n = 0
    for i in range(n):
        log_writer.write({
            "ts": iso_now(),
            "stream": "stdout",
            "phase": "exec",
            "data": f"line {i:08d} {_entropy_payload(i)}",
        })
    return {
        "lines_emitted": n,
        "message": f"chatty emitted {n} lines",
    }
