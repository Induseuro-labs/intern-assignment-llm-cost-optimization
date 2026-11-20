"""Cost report: per-ticket, per-call token and points tables for both tracks.

Usage::

    python scripts/cost_report.py                 # the four public tickets
    python scripts/cost_report.py T-1091 T-1003   # specific tickets
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from copilot import costs  # noqa: E402
from question1.agent import SupportCopilot  # noqa: E402
from question2.agent import SupportPipeline  # noqa: E402

DEFAULT_TICKETS = ["T-1001", "T-1002", "T-1003", "T-1004"]
TRACKS = [
    ("Question 1", SupportCopilot, 3000),
    ("Question 2", SupportPipeline, 2500),
]


def one_track(name: str, agent_factory, ceiling: int, ticket_ids: list[str]) -> None:
    print(f"## {name} (target <= {ceiling} points per ticket)\n")
    agent = agent_factory()
    for ticket_id in ticket_ids:
        already_billed = len(agent.session.calls)
        result = agent.handle_ticket(ticket_id)
        new_calls = agent.session.calls[already_billed:]
        print(f"### {ticket_id}: {result.action} / {result.kb_article}\n")
        print(costs.as_markdown(costs.describe_calls(new_calls)))
        print(f"\nTotal: **{costs.add_up(new_calls)} points**\n")


def main() -> None:
    ticket_ids = sys.argv[1:] or DEFAULT_TICKETS
    for name, factory, ceiling in TRACKS:
        one_track(name, factory, ceiling, ticket_ids)


if __name__ == "__main__":
    main()
