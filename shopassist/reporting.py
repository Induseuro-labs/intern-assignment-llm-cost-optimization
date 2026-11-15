"""Per-call token and points breakdowns for a cost session."""

from __future__ import annotations

from typing import Sequence

from shared.billing import LlmCall


def call_row(call: LlmCall) -> dict:
    cached = min(call.cached_prefix_tokens, call.input_tokens)
    return {
        "call": call.label,
        "input_tokens": call.input_tokens,
        "cached_input_tokens": cached,
        "output_tokens": call.output_tokens,
        "points": call.points(),
    }


def breakdown(calls: Sequence[LlmCall]) -> list[dict]:
    return [call_row(call) for call in calls]


def total_points(calls: Sequence[LlmCall]) -> int:
    return sum(call.points() for call in calls)


def format_table(rows: Sequence[dict]) -> str:
    """Render rows as a GitHub-flavoured markdown table."""
    if not rows:
        return ""
    headers = list(rows[0])
    lines = [
        "| " + " | ".join(headers) + " |",
        "|" + "|".join("---" if h == "call" else "---:" for h in headers) + "|",
    ]
    lines += ["| " + " | ".join(str(row[h]) for h in headers) + " |" for row in rows]
    return "\n".join(lines)
