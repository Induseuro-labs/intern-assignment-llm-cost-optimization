"""Pull the decision JSON out of a model completion.

The prompt asks for bare JSON, but a completion that wraps the object in
prose or code fences should still resolve, so every top-level ``{`` is tried
as a decode start and the first object carrying both required keys wins.
"""

from __future__ import annotations

import json

from copilot.model import Decision

_REQUIRED = ("action", "kb_article")
_DECODER = json.JSONDecoder()


class DecisionParseError(ValueError):
    """Raised when a completion carries no usable decision object."""


def parse_decision(text: str) -> Decision:
    """Return the first JSON object in ``text`` that carries a decision."""
    for position, character in enumerate(text):
        if character != "{":
            continue
        try:
            payload, _ = _DECODER.raw_decode(text, position)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and all(key in payload for key in _REQUIRED):
            return Decision(
                action=str(payload["action"]).strip().upper(),
                kb_article=str(payload["kb_article"]).strip(),
                customer_reply=str(payload.get("customer_reply", "")),
                model_output=text,
            )
    raise DecisionParseError(f"No decision JSON in model output:\n{text[:400]}")
