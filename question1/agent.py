"""Question 1 track: resolve each ticket with a single model call.

The unmodified starter spent ~8,800 points per ticket; see
WRITEUP.md for what this version spends and why.
"""

from __future__ import annotations

from shared.billing import CostSession
from shared.llm import ChatMessage, LlmClient
from copilot import stages
from copilot.extract import parse_decision
from copilot.model import Decision
from copilot.prompting import make_messages
from copilot.search import PolicyIndex, load_index

# Names kept stable so callers and tests need no changes.
TicketResolution = Decision

__all__ = ["SupportCopilot", "TicketResolution", "parse_decision"]


class SupportCopilot:
    """ShopAssist Tier-1 copilot.

    Reads a support ticket together with its order snapshot, picks the
    action, names the help-center article that backs it, and drafts the
    customer reply — all within one model call.
    """

    def __init__(
        self,
        session: CostSession | None = None,
        index: PolicyIndex | None = None,
        article_limit: int = stages.DEFAULT_K,
    ):
        self.session = session or CostSession()
        self.llm = LlmClient(self.session)
        self.index = index or load_index()
        self.article_limit = article_limit

    def build_messages(self, ticket_id: str) -> list[ChatMessage]:
        """Exactly the messages that will be sent for this ticket."""
        context = stages.build_context(ticket_id)
        policies = stages.lookup(context, self.index, self.article_limit)
        return make_messages(context, policies)

    def handle_ticket(self, ticket_id: str) -> TicketResolution:
        context = stages.build_context(ticket_id)
        policies = stages.lookup(context, self.index, self.article_limit)
        completion = stages.decide(self.llm, context, policies, label="handle_ticket")
        return stages.verify(completion, self.index, policies)
