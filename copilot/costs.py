"""Cost tables: turn a cost session's calls into token/points rows and text."""

from __future__ import annotations

from typing import Sequence

from shared.billing import LlmCall

_COLUMN_ORDER = ("call", "input_tokens", "cached_input_tokens", "output_tokens", "points")


def describe_call(call: LlmCall) -> dict:
    """One summary row for a single model call."""
    billed_as_cached = min(call.cached_prefix_tokens, call.input_tokens)
    return {
        "call": call.label,
        "input_tokens": call.input_tokens,
        "cached_input_tokens": billed_as_cached,
        "output_tokens": call.output_tokens,
        "points": call.points(),
    }


def describe_calls(calls: Sequence[LlmCall]) -> list[dict]:
    return [describe_call(call) for call in calls]


def add_up(calls: Sequence[LlmCall]) -> int:
    """Sum of the points of every call."""
    return sum(call.points() for call in calls)


def as_markdown(rows: Sequence[dict]) -> str:
    """Render rows as a GitHub-flavoured markdown table (numbers right-aligned)."""
    if not rows:
        return ""
    header = "| " + " | ".join(_COLUMN_ORDER) + " |"
    divider = "|" + "|".join("---" if c == "call" else "---:" for c in _COLUMN_ORDER) + "|"
    body = [
        "| " + " | ".join(str(row[column]) for column in _COLUMN_ORDER) + " |"
        for row in rows
    ]
    return "\n".join([header, divider, *body])
