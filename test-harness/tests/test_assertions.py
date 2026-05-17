"""Unit tests for the assertions helpers."""
from __future__ import annotations


import assertions


class TestCheckTruthy:
    def test_true_matches_true(self):
        ok, msg = assertions.check_truthy("k", True, True)
        assert ok is True
        assert "True" in msg

    def test_false_matches_false(self):
        ok, _msg = assertions.check_truthy("k", False, False)
        assert ok is True

    def test_truthy_string_matches_true(self):
        ok, _msg = assertions.check_truthy("k", "non-empty", True)
        assert ok is True

    def test_empty_string_matches_false(self):
        ok, _msg = assertions.check_truthy("k", "", False)
        assert ok is True

    def test_mismatched_truthiness(self):
        ok, msg = assertions.check_truthy("k", True, False)
        assert ok is False
        assert "expected False" in msg
        assert "got True" in msg


class TestCheckEquals:
    def test_exact_match(self):
        ok, _ = assertions.check_equals("k", "v", "v")
        assert ok is True

    def test_int_mismatch(self):
        ok, msg = assertions.check_equals("k", 1, 2)
        assert ok is False
        assert "1" in msg and "2" in msg

    def test_dict_match(self):
        ok, _ = assertions.check_equals("k", {"a": 1}, {"a": 1})
        assert ok is True

    def test_dict_mismatch(self):
        ok, _ = assertions.check_equals("k", {"a": 1}, {"a": 2})
        assert ok is False


class TestCheckContains:
    def test_subset_present(self):
        ok, _ = assertions.check_contains("k", ["a", "b", "c"], ["a", "c"])
        assert ok is True

    def test_subset_missing(self):
        ok, msg = assertions.check_contains("k", ["a"], ["a", "b"])
        assert ok is False
        assert "['b']" in msg

    def test_empty_expected_is_trivially_satisfied(self):
        ok, _ = assertions.check_contains("k", [], [])
        assert ok is True
        ok, _ = assertions.check_contains("k", ["x"], [])
        assert ok is True

    def test_none_actual_treated_as_empty(self):
        ok, _ = assertions.check_contains("k", None, [])  # type: ignore[arg-type]
        assert ok is True

    def test_duplicates_don_t_affect_set_logic(self):
        ok, _ = assertions.check_contains("k", ["a", "a", "b"], ["a"])
        assert ok is True


class TestEvaluateExpected:
    def test_returns_per_key_results(self):
        expected = {"a": True, "b": "v", "c": ["x"]}
        observed = {"a": True, "b": "v", "c": ["x", "y"]}
        results = assertions.evaluate_expected(expected, observed)
        assert {k for k, _ok, _msg in results} == {"a", "b", "c"}
        assert all(ok for _k, ok, _msg in results)

    def test_missing_observation_is_failure(self):
        expected = {"a": True}
        results = assertions.evaluate_expected(expected, {})
        assert results == [("a", False, "a: observation missing")]

    def test_bool_expected_uses_truthy_check(self):
        expected = {"flag": True}
        observed = {"flag": "non-empty-string"}
        results = assertions.evaluate_expected(expected, observed)
        assert results[0][1] is True

    def test_list_expected_uses_contains_check(self):
        expected = {"keys": ["a", "b"]}
        observed = {"keys": ["a", "b", "c"]}
        results = assertions.evaluate_expected(expected, observed)
        assert results[0][1] is True

    def test_list_expected_against_non_list_observed_treated_as_empty(self):
        expected = {"keys": ["a"]}
        observed = {"keys": "not-a-list"}
        results = assertions.evaluate_expected(expected, observed)
        assert results[0][1] is False
        assert "missing" in results[0][2]

    def test_scalar_expected_uses_equals_check(self):
        results = assertions.evaluate_expected({"n": 5}, {"n": 5})
        assert results[0][1] is True
        results = assertions.evaluate_expected({"n": 5}, {"n": 6})
        assert results[0][1] is False

    def test_empty_expected_returns_empty_results(self):
        assert assertions.evaluate_expected({}, {"a": 1}) == []
        assert assertions.evaluate_expected(None, {"a": 1}) == []  # type: ignore[arg-type]
