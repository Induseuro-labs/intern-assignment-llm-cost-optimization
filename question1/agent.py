"""Question 1: one model call per ticket.

Baseline: ~8,800 points per ticket. This version: see WRITEUP.md.
"""

from __future__ import annotations

from shared.billing import CostSession
from shared.llm import ChatMessage, LlmClient
from shopassist import nodes, prompts
from shopassist.knowledge import KnowledgeBase, default_knowledge_base
from shopassist.parsing import parse_resolution
from shopassist.schema import Resolution

# Public names kept stable for callers and tests.
TicketResolution = Resolution

__all__ = ["SupportCopilot", "TicketResolution", "parse_resolution"]


class SupportCopilot:
    """ShopAssist Tier-1 copilot.

    Given a support ticket and its order snapshot, choose an action, cite the
    help-center article that backs it, and draft the customer reply, in a
    single model call.
    """

    def __init__(
        self,
        session: CostSession | None = None,
        knowledge_base: KnowledgeBase | None = None,
        top_k: int = nodes.DEFAULT_TOP_K,
    ):
        self.session = session or CostSession()
        self.llm = LlmClient(self.session)
        self.knowledge_base = knowledge_base or default_knowledge_base()
        self.top_k = top_k

    def build_messages(self, ticket_id: str) -> list[ChatMessage]:
        """The exact messages sent for a ticket (useful for inspection)."""
        triage = nodes.triage(ticket_id)
        articles = nodes.retrieve(triage, self.knowledge_base, self.top_k)
        return prompts.build_messages(triage, articles)

    def handle_ticket(self, ticket_id: str) -> TicketResolution:
        triage = nodes.triage(ticket_id)
        articles = nodes.retrieve(triage, self.knowledge_base, self.top_k)
        completion = nodes.compose(self.llm, triage, articles, label="handle_ticket")
        return nodes.audit(completion, self.knowledge_base, articles)
