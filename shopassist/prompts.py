"""The one prompt sent to the model.

Cost rules that shaped it:

* Output tokens cost 5x input, so the model is asked for bare JSON and nothing
  else. No reasoning, no quoting, no restating.
* The system message is fully static (no run ids, no per-ticket text). It is a
  stable prefix, so it becomes cacheable the moment it reaches the provider's
  minimum cached-prefix size.
* Per-ticket content goes last and is kept minimal: only the retrieved
  policies, the thread, and the policy-relevant order facts as compact JSON.
"""

from __future__ import annotations

import json
from typing import Sequence

from shared.llm import ChatMessage
from shopassist.schema import Article, TriageResult

SYSTEM_PROMPT = (
    "You are ShopAssist, a Tier-1 e-commerce support agent. Resolve the ticket "
    "using only the POLICIES and the ORDER_SNAPSHOT facts.\n"
    "Actions: REFUND, REPLACE, SEND_ARTICLE (policy denies the request), "
    "ESCALATE_TIER2 (needs manual review).\n"
    'Reply with JSON only: {"action":"<action>","kb_article":"<policy id>",'
    '"customer_reply":"<one short sentence>"}'
)

# Identifiers carry no policy signal; every other order field is passed through.
_NON_POLICY_FIELDS = frozenset({"order_id", "sku"})


def policy_facts(order: dict) -> dict:
    """Drop identifier fields from an order snapshot."""
    return {k: v for k, v in order.items() if k not in _NON_POLICY_FIELDS}


def render_snapshot(order_facts: dict) -> str:
    """Compact single-line JSON: same facts, far fewer tokens than indent=2."""
    return json.dumps(order_facts, separators=(",", ":"))


def render_policies(articles: Sequence[Article]) -> str:
    return "\n".join(f"{a.article_id}: {a.body}" for a in articles)


def build_messages(triage: TriageResult, articles: Sequence[Article]) -> list[ChatMessage]:
    user = (
        f"POLICIES:\n{render_policies(articles)}\n"
        f"THREAD:\n{triage.thread}\n"
        f"ORDER_SNAPSHOT:{render_snapshot(triage.order_facts)}END_SNAPSHOT"
    )
    return [ChatMessage("system", SYSTEM_PROMPT), ChatMessage("user", user)]


def static_prefix() -> str:
    """The prompt prefix that is byte-identical across every ticket."""
    return f"SYSTEM:\n{SYSTEM_PROMPT}"
