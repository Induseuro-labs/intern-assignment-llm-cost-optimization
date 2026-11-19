"""Question 2 track: gather -> lookup -> decide -> verify.

The unmodified starter spent ~73,500 points per ticket over four
model calls. The four steps survive, but only ``decide`` talks to the model;
WRITEUP.md has the numbers.
"""

from __future__ import annotations

from dataclasses import dataclass

from shared.billing import CostSession
from shared.llm import LlmClient
from copilot import stages
from copilot.model import Decision, Policy, TicketContext
from copilot.search import PolicyIndex, load_index

__all__ = ["SupportPipeline", "TicketResolution"]


@dataclass
class TicketResolution:
    action: str
    kb_article: str


class SupportPipeline:
    """The Question 1 product recast as an explicit four-step pipeline."""

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

    def handle_ticket(self, ticket_id: str) -> TicketResolution:
        context = self._gather(ticket_id)
        policies = self._lookup(context)
        draft = self._decide(context, policies)
        final = self._verify(draft, policies)
        return TicketResolution(final.action, final.kb_article)

    def _gather(self, ticket_id: str) -> TicketContext:
        """Plain code, 0 points: read ticket + order, build the lookup query."""
        return stages.build_context(ticket_id)

    def _lookup(self, context: TicketContext) -> list[Policy]:
        """Plain code, 0 points: lexical ranking over the policy index."""
        return stages.lookup(context, self.index, self.article_limit)

    def _decide(self, context: TicketContext, policies: list[Policy]) -> str:
        """The only model call: small prompt in, bare JSON out."""
        return stages.decide(self.llm, context, policies, label="compose")

    def _verify(self, draft: str, policies: list[Policy]) -> Decision:
        """Plain code, 0 points: schema and citation checks, Tier-2 fallback."""
        return stages.verify(draft, self.index, policies)
