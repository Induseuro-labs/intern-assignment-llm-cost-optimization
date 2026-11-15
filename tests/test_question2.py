from __future__ import annotations

import pytest

from eval.reference import TICKET_EXPECTATIONS
from question2.agent import SupportPipeline
from shared.kb import expanded_help_center_blob
from shared.tokens import count_tokens
from shopassist.knowledge import KnowledgeBase, default_knowledge_base

PUBLIC = ["T-1001", "T-1002", "T-1003", "T-1004"]
HOLDOUT = ["T-1091"]
POINTS_TARGET = 2500


def test_help_center_exceeds_context():
    assert count_tokens(expanded_help_center_blob()) > 200_000


def test_index_covers_every_citeable_article_in_expanded_help_center():
    from_blob = KnowledgeBase.from_blob(expanded_help_center_blob())
    assert from_blob.article_ids == default_knowledge_base().article_ids


def test_pipeline_resolves_public_tickets():
    pipe = SupportPipeline()
    for tid in PUBLIC:
        expected = TICKET_EXPECTATIONS[tid]
        got = pipe.handle_ticket(tid)
        assert got.action == expected.action
        assert got.kb_article == expected.kb_article


def test_pipeline_resolves_holdout():
    got = SupportPipeline().handle_ticket("T-1091")
    exp = TICKET_EXPECTATIONS["T-1091"]
    assert (got.action, got.kb_article) == (exp.action, exp.kb_article)


@pytest.mark.parametrize("tid", PUBLIC + HOLDOUT)
def test_cost_within_target(tid):
    pipe = SupportPipeline()
    pipe.handle_ticket(tid)
    assert [call.label for call in pipe.session.calls] == ["compose"]
    assert pipe.session.total_points() <= POINTS_TARGET
