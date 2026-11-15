"""Question 2: triage -> retrieve -> compose -> audit.

Baseline: ~73,500 points per ticket across four model calls. This version keeps
the four stages but only ``compose`` calls the model; see WRITEUP.md.
"""

from __future__ import annotations

from dataclasses import dataclass

from shared.billing import CostSession
from shared.llm import LlmClient
from shopassist import nodes
from shopassist.knowledge import KnowledgeBase, default_knowledge_base
from shopassist.schema import Article, Resolution, TriageResult

__all__ = ["SupportPipeline", "TicketResolution"]


@dataclass
class TicketResolution:
    action: str
    kb_article: str


class SupportPipeline:
    """Same product as Question 1, as an explicit four-stage pipeline."""

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

    def handle_ticket(self, ticket_id: str) -> TicketResolution:
        triage = self._triage(ticket_id)
        articles = self._retrieve(triage)
        draft = self._compose(triage, articles)
        final = self._audit(draft, articles)
        return TicketResolution(final.action, final.kb_article)

    def _triage(self, ticket_id: str) -> TriageResult:
        """Code, 0 points: load ticket + order, derive the retrieval query."""
        return nodes.triage(ticket_id)

    def _retrieve(self, triage: TriageResult) -> list[Article]:
        """Code, 0 points: lexical search over the help-center index."""
        return nodes.retrieve(triage, self.knowledge_base, self.top_k)

    def _compose(self, triage: TriageResult, articles: list[Article]) -> str:
        """The only model call: compact prompt in, bare JSON out."""
        return nodes.compose(self.llm, triage, articles, label="compose")

    def _audit(self, draft: str, articles: list[Article]) -> Resolution:
        """Code, 0 points: schema + citation checks, Tier-2 fallback."""
        return nodes.audit(draft, self.knowledge_base, articles)
