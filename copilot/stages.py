"""The four pipeline steps: context -> lookup -> decide -> verify.

Only ``decide`` needs language understanding, so it is the only step that
calls the model. The other three are deterministic code: they cost zero
points, cannot hallucinate, and are trivial to unit-test.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Sequence

from shared.billing import CACHE_MIN_PREFIX
from shared.llm import LlmClient
from shared.tokens import count_tokens
from shared.tools import format_thread, get_order, get_ticket
from copilot import prompting
from copilot.model import Decision, Outcome, Policy, TicketContext
from copilot.extract import DecisionParseError, parse_decision
from copilot.search import PolicyIndex

logger = logging.getLogger(__name__)

DEFAULT_K = 2
_TIER2_NOTE = "A specialist will follow up shortly."


def build_context(ticket_id: str) -> TicketContext:
    """Load the ticket and its order, and derive the lookup query."""
    ticket = get_ticket(ticket_id)
    order = get_order(ticket["order_id"])
    thread = format_thread(ticket)
    return TicketContext(
        ticket_id=ticket_id,
        thread=thread,
        order_facts=prompting.relevant_facts(order),
        lookup_query=_query_from(thread, order),
    )


def _query_from(thread: str, order: dict) -> str:
    """Thread text plus the order's product info and the facts that hold."""
    true_flags = [flag.replace("_", " ") for flag, value in order.items() if value is True]
    parts = [thread, str(order.get("product_type", "")), str(order.get("title", "")), *true_flags]
    return " ".join(parts)


def lookup(context: TicketContext, index: PolicyIndex, limit: int = DEFAULT_K) -> list[Policy]:
    """Choose the small set of policies that are worth paying input tokens for."""
    return index.rank(context.lookup_query, limit=limit)


def decide(
    llm: LlmClient, context: TicketContext, policies: Sequence[Policy], label: str = "compose"
) -> str:
    """The single model call: choose the action and cite the policy."""
    messages = prompting.make_messages(context, policies)
    return llm.chat(label, messages, cached_prefix=_cache_head())


@lru_cache(maxsize=1)
def _cache_head() -> str | None:
    """Offer the static head for caching only once it is large enough to qualify."""
    head = prompting.cacheable_head()
    return head if count_tokens(head) >= CACHE_MIN_PREFIX else None


def verify(completion: str, index: PolicyIndex, policies: Sequence[Policy]) -> Decision:
    """Check the model's answer; route anything unusable to a human.

    An automated refund that should not have happened costs more than a
    manual review, so a completion that cannot be parsed, names an action
    outside the four allowed values, or cites a policy that does not exist is
    downgraded to Tier 2 instead of raising.
    """
    try:
        decision = parse_decision(completion)
    except DecisionParseError:
        logger.warning("Completion could not be parsed; routing to Tier 2")
        return _tier2_fallback(completion, policies)

    if not Outcome.is_allowed(decision.action):
        logger.warning("Action %r is not allowed; routing to Tier 2", decision.action)
        return _tier2_fallback(completion, policies)
    if decision.kb_article not in index:
        logger.warning("Policy %r does not exist; routing to Tier 2", decision.kb_article)
        return _tier2_fallback(completion, policies)
    return decision


def _tier2_fallback(completion: str, policies: Sequence[Policy]) -> Decision:
    return Decision(
        action=Outcome.ESCALATE_TIER2.value,
        kb_article=policies[0].article_id if policies else "",
        customer_reply=_TIER2_NOTE,
        model_output=completion,
    )
