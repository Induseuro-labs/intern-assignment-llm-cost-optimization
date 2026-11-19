from __future__ import annotations

import pytest

from copilot import prompting, stages
from copilot.extract import DecisionParseError, parse_decision
from copilot.model import Policy
from copilot.search import PolicyIndex, load_index
from eval.reference import TICKET_EXPECTATIONS
from shared.billing import CostSession
from shared.llm import ChatMessage, LlmClient


@pytest.fixture
def index() -> PolicyIndex:
    return load_index()


# --- lookup ---------------------------------------------------------------------


@pytest.mark.parametrize("tid", sorted(TICKET_EXPECTATIONS))
def test_governing_policy_is_in_the_top_two(index, tid):
    chosen = stages.lookup(stages.build_context(tid), index)
    assert len(chosen) == stages.DEFAULT_K
    assert TICKET_EXPECTATIONS[tid].kb_article in [p.article_id for p in chosen]


def test_ranking_is_stable_across_runs(index):
    query = stages.build_context("T-1003").lookup_query
    assert index.rank(query, 3) == index.rank(query, 3)


def test_dump_index_discards_non_citeable_sections():
    dump = (
        "--- returns ---\n# returns\n\nRefund within **30 days**.\n\n"
        "## Internal routing note\nBin labels.\n" + "-" * 40 + "\n"
    )
    built = PolicyIndex.from_dump(dump)
    assert built.article_ids == ["returns"]
    assert built.rank("refund")[0].text == "Refund within 30 days."


# --- prompt ---------------------------------------------------------------------


def test_system_message_is_static_and_user_message_is_compact(index):
    ctx_a = stages.build_context("T-1001")
    msgs_a = prompting.make_messages(ctx_a, stages.lookup(ctx_a, index))
    ctx_b = stages.build_context("T-1002")
    msgs_b = prompting.make_messages(ctx_b, stages.lookup(ctx_b, index))
    assert msgs_a[0].content == msgs_b[0].content == prompting.SYSTEM_PROMPT
    assert "\n " not in msgs_a[1].content  # no indented JSON
    assert "order_id" not in msgs_a[1].content


def test_identifier_fields_are_dropped_but_nothing_else():
    order = {
        "order_id": "o1",
        "sku": "S",
        "product_type": "physical",
        "opened": False,
        "new_field": 3,
    }
    assert prompting.relevant_facts(order) == {
        "product_type": "physical",
        "opened": False,
        "new_field": 3,
    }


def test_cache_pricing_kicks_in_once_the_head_is_big_enough():
    session = CostSession()
    head = "SYSTEM:\n" + "policy " * 1100
    tail = (
        'ORDER_SNAPSHOT:{"product_type":"physical","opened":false,'
        '"delivered_days_ago":1}END_SNAPSHOT'
    )
    LlmClient(session).chat(
        "x",
        [ChatMessage("system", head[len("SYSTEM:\n") :]), ChatMessage("user", tail)],
        cached_prefix=head,
    )
    assert session.calls[0].cached_prefix_tokens >= 1024


# --- extraction -----------------------------------------------------------------


def test_bare_json_is_parsed_and_action_is_normalised():
    got = parse_decision('{"action":"refund","kb_article":"returns-within-30-days"}')
    assert (got.action, got.kb_article, got.customer_reply) == (
        "REFUND",
        "returns-within-30-days",
        "",
    )


def test_json_wrapped_in_prose_fences_and_extra_braces_still_parses():
    text = (
        'Notes {not json} then:\n```json\n{"action": "REPLACE", "kb_article": "a", '
        '"customer_reply": "ok {x}"}\n```'
    )
    got = parse_decision(text)
    assert (got.action, got.customer_reply) == ("REPLACE", "ok {x}")


@pytest.mark.parametrize(
    "text", ["", "no json here", '{"action":"REFUND"}', "{broken"]
)
def test_completions_without_a_decision_are_rejected(text):
    with pytest.raises(DecisionParseError):
        parse_decision(text)


# --- verify ---------------------------------------------------------------------

SHORTLIST = [Policy("returns-within-30-days", "x")]


def test_verify_accepts_a_well_formed_answer(index):
    got = stages.verify(
        '{"action":"REFUND","kb_article":"returns-within-30-days"}', index, SHORTLIST
    )
    assert (got.action, got.kb_article) == ("REFUND", "returns-within-30-days")


@pytest.mark.parametrize(
    "completion",
    [
        "sorry, I cannot help",
        '{"action":"GIVE_MONEY","kb_article":"returns-within-30-days"}',
        '{"action":"REFUND","kb_article":"made-up-policy"}',
    ],
)
def test_verify_downgrades_bad_answers_to_tier2(index, completion):
    got = stages.verify(completion, index, SHORTLIST)
    assert (got.action, got.kb_article) == ("ESCALATE_TIER2", "returns-within-30-days")
