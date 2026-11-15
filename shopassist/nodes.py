"""The four pipeline stages: triage -> retrieve -> compose -> audit.

Only ``compose`` needs language understanding, so it is the only stage that
calls the model. Triage, retrieval and audit are deterministic code: they cost
zero points, cannot hallucinate, and are unit-testable.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Sequence

from shared.billing import CACHE_MIN_PREFIX
from shared.llm import LlmClient
from shared.tokens import count_tokens
from shared.tools import format_thread, get_order, get_ticket
from shopassist import prompts
from shopassist.knowledge import KnowledgeBase
from shopassist.parsing import ResolutionParseError, parse_resolution
from shopassist.schema import Action, Article, Resolution, TriageResult

logger = logging.getLogger(__name__)

DEFAULT_TOP_K = 2
_FALLBACK_REPLY = "A specialist will follow up shortly."


def triage(ticket_id: str) -> TriageResult:
    """Load the ticket and its order, and derive the retrieval query."""
    ticket = get_ticket(ticket_id)
    order = get_order(ticket["order_id"])
    thread = format_thread(ticket)
    return TriageResult(
        ticket_id=ticket_id,
        thread=thread,
        order_facts=prompts.policy_facts(order),
        search_query=_search_query(thread, order),
    )


def _search_query(thread: str, order: dict) -> str:
    """Thread text plus the order facts that are true, spelled out as words."""
    raised_flags = [name.replace("_", " ") for name, value in order.items() if value is True]
    parts = [thread, str(order.get("product_type", "")), str(order.get("title", "")), *raised_flags]
    return " ".join(parts)


def retrieve(
    triage_result: TriageResult, knowledge_base: KnowledgeBase, top_k: int = DEFAULT_TOP_K
) -> list[Article]:
    """Pick the few policies worth paying input tokens for."""
    return knowledge_base.search(triage_result.search_query, top_k=top_k)


def compose(
    llm: LlmClient, triage_result: TriageResult, articles: Sequence[Article], label: str = "compose"
) -> str:
    """The single model call: decide the action and cite the policy."""
    messages = prompts.build_messages(triage_result, articles)
    return llm.chat(label, messages, cached_prefix=_cacheable_prefix())


@lru_cache(maxsize=1)
def _cacheable_prefix() -> str | None:
    """Offer the static prefix for caching only once it is large enough to qualify."""
    prefix = prompts.static_prefix()
    return prefix if count_tokens(prefix) >= CACHE_MIN_PREFIX else None


def audit(
    completion: str, knowledge_base: KnowledgeBase, articles: Sequence[Article]
) -> Resolution:
    """Validate the model's answer; hand anything malformed to a human.

    A wrong automated refund is costlier than a manual review, so an answer
    that cannot be parsed, names an unknown action, or cites an article that
    does not exist is downgraded to a Tier-2 escalation instead of raising.
    """
    try:
        resolution = parse_resolution(completion)
    except ResolutionParseError:
        logger.warning("Unparseable completion; escalating to Tier 2")
        return _escalation(completion, articles)

    if not Action.is_valid(resolution.action):
        logger.warning("Unknown action %r; escalating to Tier 2", resolution.action)
        return _escalation(completion, articles)
    if resolution.kb_article not in knowledge_base:
        logger.warning("Unknown article %r; escalating to Tier 2", resolution.kb_article)
        return _escalation(completion, articles)
    return resolution


def _escalation(completion: str, articles: Sequence[Article]) -> Resolution:
    return Resolution(
        action=Action.ESCALATE_TIER2.value,
        kb_article=articles[0].article_id if articles else "",
        customer_reply=_FALLBACK_REPLY,
        raw_completion=completion,
    )
