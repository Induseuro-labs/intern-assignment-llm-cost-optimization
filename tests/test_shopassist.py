from __future__ import annotations

import pytest

from eval.reference import TICKET_EXPECTATIONS
from shared.llm import ChatMessage, LlmClient
from shared.billing import CostSession
from shopassist import nodes, prompts
from shopassist.knowledge import KnowledgeBase, default_knowledge_base
from shopassist.parsing import ResolutionParseError, parse_resolution
from shopassist.schema import Article


@pytest.fixture
def kb() -> KnowledgeBase:
    return default_knowledge_base()


# --- retrieval ---------------------------------------------------------------


@pytest.mark.parametrize("tid", sorted(TICKET_EXPECTATIONS))
def test_retrieval_surfaces_the_governing_article(kb, tid):
    articles = nodes.retrieve(nodes.triage(tid), kb)
    assert len(articles) == nodes.DEFAULT_TOP_K
    assert TICKET_EXPECTATIONS[tid].kb_article in [a.article_id for a in articles]


def test_search_is_deterministic(kb):
    query = nodes.triage("T-1003").search_query
    assert kb.search(query, 3) == kb.search(query, 3)


def test_blob_index_drops_sections_without_an_article_id():
    blob = (
        "--- returns ---\n# returns\n\nRefund within **30 days**.\n\n"
        "## Internal routing note\nBin labels.\n" + "-" * 40 + "\n"
    )
    index = KnowledgeBase.from_blob(blob)
    assert index.article_ids == ["returns"]
    assert index.search("refund")[0].body == "Refund within 30 days."


# --- prompt ------------------------------------------------------------------


def test_prompt_is_static_first_and_compact(kb):
    triage = nodes.triage("T-1001")
    first = prompts.build_messages(triage, nodes.retrieve(triage, kb))
    other = nodes.triage("T-1002")
    second = prompts.build_messages(other, nodes.retrieve(other, kb))
    assert first[0].content == second[0].content == prompts.SYSTEM_PROMPT
    assert "\n " not in first[1].content  # no indented JSON
    assert "order_id" not in first[1].content


def test_snapshot_keeps_every_policy_fact():
    order = {"order_id": "o1", "sku": "S", "product_type": "physical", "opened": False, "new_field": 3}
    assert prompts.policy_facts(order) == {"product_type": "physical", "opened": False, "new_field": 3}


def test_prefix_caching_engages_once_prefix_is_large_enough():
    session = CostSession()
    prefix = "SYSTEM:\n" + "policy " * 1100
    prompt_tail = 'ORDER_SNAPSHOT:{"product_type":"physical","opened":false,"delivered_days_ago":1}END_SNAPSHOT'
    LlmClient(session).chat(
        "x", [ChatMessage("system", prefix[len("SYSTEM:\n"):]), ChatMessage("user", prompt_tail)],
        cached_prefix=prefix,
    )
    assert session.calls[0].cached_prefix_tokens >= 1024


# --- parsing -----------------------------------------------------------------


def test_parse_bare_json():
    got = parse_resolution('{"action":"refund","kb_article":"returns-within-30-days"}')
    assert (got.action, got.kb_article, got.customer_reply) == ("REFUND", "returns-within-30-days", "")


def test_parse_json_wrapped_in_prose_and_braces():
    text = 'Notes {not json} then:\n```json\n{"action": "REPLACE", "kb_article": "a", "customer_reply": "ok {x}"}\n```'
    got = parse_resolution(text)
    assert (got.action, got.customer_reply) == ("REPLACE", "ok {x}")


@pytest.mark.parametrize("text", ["", "no json here", '{"action":"REFUND"}', "{broken"])
def test_parse_rejects_missing_decision(text):
    with pytest.raises(ResolutionParseError):
        parse_resolution(text)


# --- audit -------------------------------------------------------------------

_RETRIEVED = [Article("returns-within-30-days", "x")]


def test_audit_passes_valid_answer(kb):
    got = nodes.audit('{"action":"REFUND","kb_article":"returns-within-30-days"}', kb, _RETRIEVED)
    assert (got.action, got.kb_article) == ("REFUND", "returns-within-30-days")


@pytest.mark.parametrize(
    "completion",
    [
        "sorry, I cannot help",
        '{"action":"GIVE_MONEY","kb_article":"returns-within-30-days"}',
        '{"action":"REFUND","kb_article":"made-up-policy"}',
    ],
)
def test_audit_escalates_bad_answers(kb, completion):
    got = nodes.audit(completion, kb, _RETRIEVED)
    assert (got.action, got.kb_article) == ("ESCALATE_TIER2", "returns-within-30-days")
