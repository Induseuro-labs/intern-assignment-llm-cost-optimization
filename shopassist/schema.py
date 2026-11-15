"""Typed domain objects passed between pipeline stages."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Action(str, Enum):
    """Every outcome a Tier-1 ticket can be routed to."""

    REFUND = "REFUND"
    REPLACE = "REPLACE"
    SEND_ARTICLE = "SEND_ARTICLE"
    ESCALATE_TIER2 = "ESCALATE_TIER2"

    @classmethod
    def is_valid(cls, value: str) -> bool:
        return value in cls._value2member_map_


@dataclass
class Resolution:
    """The model's decision for one ticket."""

    action: str
    kb_article: str
    customer_reply: str = ""
    raw_completion: str = ""


@dataclass(frozen=True)
class Article:
    """One help-center policy."""

    article_id: str
    body: str


@dataclass(frozen=True)
class TriageResult:
    """Everything later stages need to know about a ticket."""

    ticket_id: str
    thread: str
    order_facts: dict
    search_query: str
