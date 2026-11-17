"""Regression test from docs/trace_case.md: seeded_regression C-008@11.

Lab 8's grader PASSES this trial (ledger 20.000đ = label), but the reply tells the customer
35.000đ. The first wrong step is the reply event; ReplyMatchesLedger must catch it, and the
same claim@seed on `fixed` must stay green.
"""
import pytest

pytestmark = pytest.mark.student


def _grade(shape):
    from pydantic_evals.evaluators import EvaluatorContext

    from lab9 import graders
    from lab9.trace_case import investigate

    case = investigate(shape, "C-008", 11)
    ctx = EvaluatorContext(name="t", inputs={}, metadata=None, expected_output=case["label"],
                           output=case["trial"], duration=0.0, _span_tree=None, attributes={}, metrics={})
    return case["trial"], graders.ReplyMatchesLedger().evaluate(ctx)


def test_lab9_trace_case_c008_misreport_is_caught():
    trial, verdict = _grade("seeded_regression")
    assert trial["lab8_pass"] is True                 # the Lab 8 grader alone misses it
    assert trial["snapshot"]["refund_vnd"] == 20000
    assert verdict.value is False and "35000" in verdict.reason


def test_lab9_trace_case_c008_fixed_reports_ledger_amount():
    _, verdict = _grade("fixed")
    assert verdict.value is True
