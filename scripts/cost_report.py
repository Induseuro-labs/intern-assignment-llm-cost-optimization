"""Print per-ticket, per-call cost breakdowns for both agents.

    python scripts/cost_report.py            # public tickets
    python scripts/cost_report.py T-1091     # specific tickets
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from question1.agent import SupportCopilot  # noqa: E402
from question2.agent import SupportPipeline  # noqa: E402
from shopassist import reporting  # noqa: E402

PUBLIC = ["T-1001", "T-1002", "T-1003", "T-1004"]
TARGETS = {"Question 1": 3000, "Question 2": 2500}


def report(title: str, agent, ticket_ids: list[str]) -> None:
    print(f"## {title} (target <= {TARGETS[title]} points per ticket)\n")
    for ticket_id in ticket_ids:
        first_call = len(agent.session.calls)
        resolution = agent.handle_ticket(ticket_id)
        calls = agent.session.calls[first_call:]
        print(f"### {ticket_id}: {resolution.action} / {resolution.kb_article}\n")
        print(reporting.format_table(reporting.breakdown(calls)))
        print(f"\nTotal: **{reporting.total_points(calls)} points**\n")


def main() -> None:
    ticket_ids = sys.argv[1:] or PUBLIC
    report("Question 1", SupportCopilot(), ticket_ids)
    report("Question 2", SupportPipeline(), ticket_ids)


if __name__ == "__main__":
    main()
