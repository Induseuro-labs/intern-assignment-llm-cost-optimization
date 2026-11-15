"""Extract the decision JSON from a model completion."""

from __future__ import annotations

import json

from shopassist.schema import Resolution

_REQUIRED_KEYS = ("action", "kb_article")
_DECODER = json.JSONDecoder()


class ResolutionParseError(ValueError):
    """The completion held no usable decision object."""


def parse_resolution(text: str) -> Resolution:
    """Return the first JSON object in ``text`` that carries a decision.

    The model is asked for bare JSON, but the parser also accepts an object
    wrapped in prose or code fences so a chatty completion still resolves.
    """
    for start, char in enumerate(text):
        if char != "{":
            continue
        try:
            data, _ = _DECODER.raw_decode(text, start)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and all(key in data for key in _REQUIRED_KEYS):
            return Resolution(
                action=str(data["action"]).strip().upper(),
                kb_article=str(data["kb_article"]).strip(),
                customer_reply=str(data.get("customer_reply", "")),
                raw_completion=text,
            )
    raise ResolutionParseError(f"No decision JSON in model output:\n{text[:400]}")
