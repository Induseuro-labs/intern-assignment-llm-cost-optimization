"""Domain types handed between the pipeline steps.

These are deliberately tiny: each step consumes and produces plain data, so
every step can be unit-tested without a model or a ticket on disk.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Outcome(str, Enum):
    """The four destinations a Tier-1 ticket can be routed to."""

    REFUND = "REFUND"
    REPLACE = "REPLACE"
    SEND_ARTICLE = "SEND_ARTICLE"
    ESCALATE_TIER2 = "ESCALATE_TIER2"

    @classmethod
    def is_allowed(cls, candidate: str) -> bool:
        """True when ``candidate`` is one of the four routing values."""
        return candidate in cls._value2member_map_


@dataclass
class Decision:
    """What the agent decided for one ticket."""

    action: str
    kb_article: str
    customer_reply: str = ""
    model_output: str = ""


@dataclass(frozen=True)
class Policy:
    """One help-center policy document."""

    article_id: str
    text: str


@dataclass(frozen=True)
class TicketContext:
    """Everything the later steps need to know about one ticket.

    Built by the context step (code only): the customer thread, the
    policy-relevant order facts, and the query used for policy lookup.
    """

    ticket_id: str
    thread: str
    order_facts: dict
    lookup_query: str
