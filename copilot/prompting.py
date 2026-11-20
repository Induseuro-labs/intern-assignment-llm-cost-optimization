"""The one prompt the model ever sees.

How the billing rules shaped it:

* Output tokens are 5x the price of input tokens, so the model is asked for a
  bare JSON object and nothing else — no reasoning, no quotations, no
  restating the ticket.
* The system message is completely static (no run ids, nothing per-ticket).
  It is a stable prefix, so it qualifies for cache pricing automatically once
  it reaches the provider's minimum cached-prefix size.
* Per-ticket content is appended after the static part and kept minimal: the
  ranked policies, the thread, and the policy-relevant order facts as compact
  single-line JSON.
"""

from __future__ import annotations

import json
from typing import Sequence

from shared.llm import ChatMessage
from copilot.model import Policy, TicketContext

SYSTEM_PROMPT = "\n".join(
    [
        "You are ShopAssist, a Tier-1 e-commerce support agent. Resolve the ticket "
        "using only the POLICIES and the ORDER_SNAPSHOT facts.",
        "Actions: REFUND, REPLACE, SEND_ARTICLE (policy denies the request), "
        "ESCALATE_TIER2 (needs manual review).",
        'Reply with JSON only: {"action":"<action>","kb_article":"<policy id>",'
        '"customer_reply":"<one short sentence>"}',
    ]
)

# Pure identifiers: they never influence which policy applies. Everything
# else on the order is passed through, including fields added in the future.
_IDENTIFIER_FIELDS = frozenset({"order_id", "sku"})


def relevant_facts(order: dict) -> dict:
    """Return the order without its identifier fields."""
    return {k: v for k, v in order.items() if k not in _IDENTIFIER_FIELDS}


def snapshot_line(order_facts: dict) -> str:
    """Compact one-line JSON: same facts, far fewer tokens than indent=2."""
    return json.dumps(order_facts, separators=(",", ":"))


def render_policies(policies: Sequence[Policy]) -> str:
    return "\n".join(f"{p.article_id}: {p.text}" for p in policies)


def make_messages(context: TicketContext, policies: Sequence[Policy]) -> list[ChatMessage]:
    user = (
        f"POLICIES:\n{render_policies(policies)}\n"
        f"THREAD:\n{context.thread}\n"
        f"ORDER_SNAPSHOT:{snapshot_line(context.order_facts)}END_SNAPSHOT"
    )
    return [ChatMessage("system", SYSTEM_PROMPT), ChatMessage("user", user)]


def cacheable_head() -> str:
    """The prompt head that is byte-identical across every ticket."""
    return f"SYSTEM:\n{SYSTEM_PROMPT}"
