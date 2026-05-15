"""Phase-assertion helpers shared by every runner.

A phase's `expected` block in a scenario YAML maps to a dict of
key -> expected value. This module provides:

- `check_truthy(key, actual, expected)` for boolean-style keys.
- `check_equals(key, actual, expected)` for exact-match keys.
- `check_contains(key, actual_list, expected_subset)` for list keys.
- `evaluate_expected(expected, observed)` returns a list of
  (key, ok, message) tuples — does not raise.

Phase assertions never raise; they return structured results so the
runner can record them in state.json and continue to the next phase
(or abort) per scenario policy.
"""
from __future__ import annotations

from typing import Any


def check_truthy(key: str, actual: Any, expected: bool) -> tuple[bool, str]:
    ok = bool(actual) == bool(expected)
    return ok, f"{key}: expected {expected}, got {bool(actual)}"


def check_equals(key: str, actual: Any, expected: Any) -> tuple[bool, str]:
    ok = actual == expected
    return ok, f"{key}: expected {expected!r}, got {actual!r}"


def check_contains(
    key: str, actual: list, expected_subset: list
) -> tuple[bool, str]:
    actual_set = set(actual or [])
    expected_set = set(expected_subset or [])
    missing = expected_set - actual_set
    ok = not missing
    return ok, f"{key}: missing {sorted(missing)} from {sorted(actual_set)}"


def evaluate_expected(
    expected: dict[str, Any], observed: dict[str, Any]
) -> list[tuple[str, bool, str]]:
    results: list[tuple[str, bool, str]] = []
    for key, exp_val in (expected or {}).items():
        if key not in observed:
            results.append((key, False, f"{key}: observation missing"))
            continue
        actual = observed[key]
        if isinstance(exp_val, bool):
            ok, msg = check_truthy(key, actual, exp_val)
        elif isinstance(exp_val, list):
            ok, msg = check_contains(key, actual if isinstance(actual, list) else [], exp_val)
        else:
            ok, msg = check_equals(key, actual, exp_val)
        results.append((key, ok, msg))
    return results
