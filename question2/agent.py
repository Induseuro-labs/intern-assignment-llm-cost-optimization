
from __future__ import annotations

import json
from dataclasses import dataclass

from shared.billing import CostSession
from shared.kb import load_article
from shared.llm import ChatMessage, LlmClient
from shared.tools import format_thread, get_order, get_ticket

from question1.agent import parse_resolution


@dataclass
class TicketResolution:
    action: str
    kb_article: str


class SupportPipeline:
    """ShopAssist pipeline: triage, retrieve, compose and audit."""

    def __init__(self, session: CostSession | None = None):
        self.session = session or CostSession()
        self.llm = LlmClient(self.session)

    def handle_ticket(self, ticket_id: str) -> TicketResolution:
        ticket = get_ticket(ticket_id)
        order = get_order(ticket["order_id"])
        thread = format_thread(ticket)

        snapshot = json.dumps(order, separators=(",", ":"))

        # Stage 1: Understand the customer's issue
        triage = self._triage(order)

        # Stage 2: Find the relevant policy
        article_id, article_text = self._retrieve(triage)

        # Stage 3: Generate the final response using AI
        draft = self._compose(
            ticket_id,
            thread,
            snapshot,
            triage,
            article_id,
            article_text,
        )

        # Stage 4: Validate the AI response
        return self._audit(article_id, draft)

    def _triage(self, order: dict) -> str:
        if order.get("product_type") == "subscription":
            return "subscription"

        if order.get("license_revealed"):
            return "digital_license"

        if order.get("customized") and order.get("damage_reported"):
            return "custom_damage"

        if order.get("damage_reported") and not order.get("customized"):
            if int(order.get("delivered_days_ago", 99)) <= 7:
                return "damaged_item"

        if order.get("product_type") == "physical" and not order.get("opened"):
            if int(order.get("delivered_days_ago", 99)) <= 30:
                return "physical_return"

        return "manual_review"

    def _retrieve(self, triage: str) -> tuple[str, str]:
        article_by_case = {
            "subscription": "subscription-cooling-off",
            "digital_license": "digital-license-no-refund",
            "custom_damage": "custom-items-no-replace",
            "damaged_item": "damage-replacement-7-days",
            "physical_return": "returns-within-30-days",
            "manual_review": "returns-within-30-days",
        }

        article_id = article_by_case[triage]
        article_text = load_article(article_id)

        return article_id, article_text

    def _compose(
        self,
        ticket_id: str,
        thread: str,
        snapshot: str,
        triage: str,
        article_id: str,
        article_text: str,
    ) -> str:

        messages = [
            ChatMessage(
                "system",
                "You are ShopAssist. Use the order details and policy "
                "to choose the correct action. Return only JSON with "
                "action, kb_article and customer_reply. "
                "Keep the customer reply short."
            ),
            ChatMessage(
                "user",
                "\n\n".join(
                    [
                        f"TICKET: {ticket_id}",
                        f"THREAD:\n{thread}",
                        f"ORDER_SNAPSHOT:{snapshot}END_SNAPSHOT",
                        f"TRIAGE: {triage}",
                        f"POLICY ARTICLE:\n{article_text}",
                    ]
                ),
            ),
        ]

        return self.llm.chat("compose", messages)

    def _audit(self, article_id: str, draft: str) -> TicketResolution:
        result = parse_resolution(draft)

        valid_actions = {
            "REFUND",
            "REPLACE",
            "SEND_ARTICLE",
            "ESCALATE_TIER2",
        }

        if result.action not in valid_actions:
            raise ValueError("Invalid action returned by AI")

        if result.kb_article != article_id:
            raise ValueError("AI selected an incorrect policy article")

        return TicketResolution(
            action=result.action,
            kb_article=result.kb_article,
        )
