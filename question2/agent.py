from __future__ import annotations

import json
from dataclasses import dataclass

from shared.billing import CostSession
from shared.kb import article_ids, load_article
from shared.llm import ChatMessage, LlmClient
from shared.tools import get_order, get_ticket

from question1.agent import TicketResolution as _Draft
from question1.agent import parse_resolution

ACTIONS = ("REFUND", "REPLACE", "SEND_ARTICLE", "ESCALATE_TIER2")

# Actions each help-center article can justify, taken from the article wording
# (data/kb). ESCALATE_TIER2 (human review) is always a safe outcome. An article
# missing from this table permits nothing, so Audit fails closed.
ARTICLE_ALLOWED_ACTIONS: dict[str, frozenset[str]] = {
    # "not eligible for automated replacement; route to Tier 2 for manual review"
    "custom-items-no-replace": frozenset({"ESCALATE_TIER2"}),
    # "qualify for a free replacement shipment"
    "damage-replacement-7-days": frozenset({"REPLACE", "ESCALATE_TIER2"}),
    # "not refundable after the license key ... has been revealed" (deny, send policy)
    "digital-license-no-refund": frozenset({"SEND_ARTICLE", "ESCALATE_TIER2"}),
    # "may be refunded within 30 days of delivery"
    "returns-within-30-days": frozenset({"REFUND", "ESCALATE_TIER2"}),
    # "prorated refund if cancelled within 30 days ... After day 30, no automatic refund"
    "subscription-cooling-off": frozenset({"REFUND", "SEND_ARTICLE", "ESCALATE_TIER2"}),
}


@dataclass
class TicketResolution:
    action: str
    kb_article: str


class SupportPipeline:
    """Same product as Question 1 — triage, retrieve, compose, audit.

    Cost notes:
      * The decision depends only on the order facts, so every model call carries
        the ORDER_SNAPSHOT block (compact JSON, same facts) plus only what that
        stage needs. The full help-center blob is never sent to the model.
      * RETRIEVE is a lookup in the help center (data/kb), not a model call: it
        validates the article triage proposed and loads its actual content.
      * AUDIT is a rule-based check, not a model call: it validates the composed
        answer, checks that its action is permitted by the cited article's policy
        (ARTICLE_ALLOWED_ACTIONS), and checks it against triage and retrieval.
        Anything that fails is escalated to Tier 2.
    """

    def __init__(self, session: CostSession | None = None):
        self.session = session or CostSession()
        self.llm = LlmClient(self.session)
        self.last_trace: dict = {}

    def handle_ticket(self, ticket_id: str) -> TicketResolution:
        ticket = get_ticket(ticket_id)
        order = get_order(ticket["order_id"])
        snapshot = json.dumps(order, separators=(",", ":"))

        triage = self._triage(snapshot)
        retrieved = self._retrieve(triage)
        draft = self._compose(snapshot, triage, retrieved)
        final = self._audit(triage, retrieved, draft)
        parsed = parse_resolution(final)
        return TicketResolution(parsed.action, parsed.kb_article)

    # TRIAGE (model call): propose an action and the governing article.
    def _triage(self, snapshot: str) -> _Draft | None:
        prompt = "\n".join(
            [
                "Triage: classify this support case from the order facts.",
                f"Actions: {', '.join(ACTIONS)}",
                f"Articles: {', '.join(article_ids())}",
                "Return JSON with action, kb_article.",
                f"ORDER_SNAPSHOT:\n{snapshot}\nEND_SNAPSHOT",
            ]
        )
        completion = self.llm.chat("triage", [ChatMessage("user", prompt)])
        self.last_trace = {"triage": completion}
        try:
            return parse_resolution(completion)
        except (ValueError, KeyError):
            return None

    # RETRIEVE (help-center lookup, no model call): validate the proposed article
    # against the knowledge base and load its actual content.
    def _retrieve(self, triage: _Draft | None) -> dict:
        article_id = triage.kb_article if triage else ""
        if article_id not in article_ids():
            retrieved = {"article_id": None, "content": "", "policy": "", "rejected": article_id}
        else:
            content = load_article(article_id)
            lines = content.strip().splitlines()
            body = " ".join(line for line in lines if line and not line.startswith("#"))
            retrieved = {
                "article_id": article_id,
                "content": content,
                "policy": body.replace("**", ""),
                "rejected": None,
            }
        self.last_trace["retrieve"] = retrieved
        return retrieved

    # COMPOSE (model call): final resolution from order facts + retrieved policy.
    def _compose(self, snapshot: str, triage: _Draft | None, retrieved: dict) -> str:
        proposal = f"{triage.action} / {triage.kb_article}" if triage else "none"
        policy = (
            f"{retrieved['article_id']}: {retrieved['policy']}"
            if retrieved["article_id"]
            else "none found"
        )
        prompt = "\n".join(
            [
                "Compose the final resolution for this support case.",
                f"Triage proposal: {proposal}",
                f"Policy {policy}",
                "Return JSON with action, kb_article, customer_reply.",
                f"ORDER_SNAPSHOT:\n{snapshot}\nEND_SNAPSHOT",
            ]
        )
        completion = self.llm.chat("compose", [ChatMessage("user", prompt)])
        self.last_trace["compose"] = completion
        return completion

    # AUDIT (rule-based, no model call): accept the draft only if it is valid, its
    # action is permitted by the cited article's policy, and it is consistent with
    # retrieval and triage; otherwise escalate to Tier 2.
    def _audit(self, triage: _Draft | None, retrieved: dict, draft: str) -> str:
        try:
            res = parse_resolution(draft)
        except (ValueError, KeyError):
            res = None
        checks = {
            "draft_parses": res is not None,
            "action_allowed": bool(res) and res.action in ACTIONS,
            "article_exists": bool(res) and res.kb_article in article_ids(),
            "article_matches_retrieval": bool(res) and res.kb_article == retrieved["article_id"],
            "action_permitted_by_policy": bool(res)
            and res.action in ARTICLE_ALLOWED_ACTIONS.get(res.kb_article, frozenset()),
            "agrees_with_triage": bool(res)
            and triage is not None
            and (res.action, res.kb_article) == (triage.action, triage.kb_article),
        }
        passed = all(checks.values())
        self.last_trace["audit"] = {"passed": passed, "checks": checks}
        if passed:
            return draft
        # Cite only the article Retrieve verified, and only if its policy entry
        # explicitly permits escalation; never fall back to the unverified draft.
        retrieved_id = retrieved["article_id"]
        fallback_article = (
            retrieved_id
            if retrieved_id
            and "ESCALATE_TIER2" in ARTICLE_ALLOWED_ACTIONS.get(retrieved_id, frozenset())
            else ""
        )
        return json.dumps(
            {
                "action": "ESCALATE_TIER2",
                "kb_article": fallback_article,
                "customer_reply": "A specialist will follow up shortly.",
            }
        )
