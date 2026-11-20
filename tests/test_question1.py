from __future__ import annotations

import pytest

from eval.reference import TICKET_EXPECTATIONS
from question1.agent import SupportCopilot, parse_decision

VISIBLE = ["T-1001", "T-1002", "T-1003", "T-1004"]
UNSEEN = ["T-1091"]
EVERY = VISIBLE + UNSEEN
CEILING_PER_TICKET = 3000


def resolutions_for(agent, ticket_ids):
    return {tid: agent.handle_ticket(tid) for tid in ticket_ids}


def test_public_tickets_resolve_correctly():
    copilot = SupportCopilot()
    for tid, got in resolutions_for(copilot, VISIBLE).items():
        want = TICKET_EXPECTATIONS[tid]
        assert (got.action, got.kb_article) == (want.action, want.kb_article)


def test_holdout_ticket_resolves_correctly():
    got = SupportCopilot().handle_ticket(UNSEEN[0])
    want = TICKET_EXPECTATIONS[UNSEEN[0]]
    assert (got.action, got.kb_article) == (want.action, want.kb_article)


@pytest.mark.parametrize("tid", EVERY)
def test_single_call_within_budget(tid):
    copilot = SupportCopilot()
    copilot.handle_ticket(tid)
    assert len(copilot.session.calls) == 1
    assert copilot.session.total_points() <= CEILING_PER_TICKET


def test_recorded_completion_can_be_reparsed():
    copilot = SupportCopilot()
    copilot.handle_ticket(VISIBLE[0])
    again = parse_decision(copilot.session.calls[0].completion)
    assert again.action == "REFUND"
    assert again.customer_reply
