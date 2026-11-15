from __future__ import annotations

import pytest

from eval.reference import TICKET_EXPECTATIONS
from question1.agent import SupportCopilot, parse_resolution

PUBLIC = ["T-1001", "T-1002", "T-1003", "T-1004"]
HOLDOUT = ["T-1091"]
POINTS_TARGET = 3000


def test_resolves_public_tickets():
    copilot = SupportCopilot()
    for tid in PUBLIC:
        expected = TICKET_EXPECTATIONS[tid]
        got = copilot.handle_ticket(tid)
        assert got.action == expected.action
        assert got.kb_article == expected.kb_article


def test_holdout_subscription():
    copilot = SupportCopilot()
    got = copilot.handle_ticket("T-1091")
    exp = TICKET_EXPECTATIONS["T-1091"]
    assert got.action == exp.action
    assert got.kb_article == exp.kb_article


@pytest.mark.parametrize("tid", PUBLIC + HOLDOUT)
def test_cost_within_target(tid):
    copilot = SupportCopilot()
    copilot.handle_ticket(tid)
    assert len(copilot.session.calls) == 1
    assert copilot.session.total_points() <= POINTS_TARGET


def test_completion_stays_parseable():
    copilot = SupportCopilot()
    copilot.handle_ticket("T-1001")
    parsed = parse_resolution(copilot.session.calls[0].completion)
    assert parsed.action == "REFUND"
    assert parsed.customer_reply
