"""Gate receipts must not turn partial execution or duplicate phases into PASS."""

from typing import Any

import pytest
from tools.quality_gate import partition, reconcile


def test_partition_is_disjoint_complete_and_keeps_properties_separate() -> None:
    items: list[dict[str, Any]] = [
        {"nodeid": f"tests/a.py::case[{i}]", "property": i == 2} for i in range(5)
    ]
    items.append({"nodeid": "tests/b.py::property", "property": True})
    groups = partition(items, 2)
    assert groups == [
        [x["nodeid"] for x in items[:2]],
        [items[2]["nodeid"]],
        [x["nodeid"] for x in items[3:5]],
        [items[5]["nodeid"]],
    ]
    assert sorted(node for group in groups for node in group) == sorted(x["nodeid"] for x in items)
    with pytest.raises(ValueError, match="duplicate"):
        partition(items + items[:1])
    with pytest.raises(ValueError, match="positive"):
        partition(items, 0)


def test_timeout_teardown_failure_and_missing_phase_are_not_pass() -> None:
    good = [
        {"nodeid": "a", "when": phase, "outcome": "passed"}
        for phase in ("setup", "call", "teardown")
    ]
    assert reconcile(["a"], good, 0) == {"a": "PASS"}
    assert reconcile(["a"], good, None) == {"a": "INCOMPLETE"}
    assert reconcile(["a"], good[:-1], 0) == {"a": "INCOMPLETE"}
    assert reconcile(
        ["a"], [*good[:-1], {"nodeid": "a", "when": "teardown", "outcome": "failed"}], 1
    ) == {"a": "FAIL"}
    assert reconcile(["a"], [dict(good[0], outcome="skipped"), good[-1]], 0) == {"a": "SKIP"}


def test_unexpected_duplicate_results_and_duplicate_expected_are_rejected() -> None:
    event = {"nodeid": "a", "when": "call", "outcome": "passed"}
    with pytest.raises(ValueError, match="duplicate"):
        reconcile(["a"], [event, event], 0)
    with pytest.raises(ValueError, match="unexpected"):
        reconcile(["b"], [event], 0)
    with pytest.raises(ValueError, match="duplicate"):
        reconcile(["a", "a"], [], 0)
