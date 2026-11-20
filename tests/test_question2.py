from __future__ import annotations

import pytest

from eval.reference import TICKET_EXPECTATIONS
from question2.agent import SupportPipeline
from shared.kb import expanded_help_center_blob
from shared.tokens import count_tokens
from copilot.search import PolicyIndex, load_index

VISIBLE = ["T-1001", "T-1002", "T-1003", "T-1004"]
UNSEEN = ["T-1091"]
EVERY = VISIBLE + UNSEEN
CEILING_PER_TICKET = 2500


def test_expanded_help_center_still_exceeds_any_context_window():
    assert count_tokens(expanded_help_center_blob()) > 200_000


def test_dump_index_matches_the_citeable_articles():
    from_dump = PolicyIndex.from_dump(expanded_help_center_blob())
    assert from_dump.article_ids == load_index().article_ids


def test_pipeline_resolves_every_public_ticket():
    pipe = SupportPipeline()
    for tid in VISIBLE:
        want = TICKET_EXPECTATIONS[tid]
        got = pipe.handle_ticket(tid)
        assert (got.action, got.kb_article) == (want.action, want.kb_article)


def test_pipeline_resolves_the_holdout_ticket():
    want = TICKET_EXPECTATIONS[UNSEEN[0]]
    got = SupportPipeline().handle_ticket(UNSEEN[0])
    assert (got.action, got.kb_article) == (want.action, want.kb_article)


@pytest.mark.parametrize("tid", EVERY)
def test_only_compose_is_billed_and_budget_holds(tid):
    pipe = SupportPipeline()
    pipe.handle_ticket(tid)
    assert [call.label for call in pipe.session.calls] == ["compose"]
    assert pipe.session.total_points() <= CEILING_PER_TICKET
