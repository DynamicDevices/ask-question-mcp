"""EOD MCQ log summary for Hansei (Alex 2026-08-02).

Usage::

    ask-mcq-eod              # today
    ask-mcq-eod --date 2026-08-02
    ask-mcq-eod --json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime

from ask_question_mcp.mcq_log import summarize_day


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="ask-mcq-eod",
        description="Summarise today's MCQ decision log for EOD Hansei.",
    )
    parser.add_argument(
        "--date",
        help="YYYY-MM-DD (default: today local)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print full JSON summary",
    )
    parser.add_argument(
        "--freeform-only",
        action="store_true",
        help="Only list freeform / cancel / unexpected rows",
    )
    args = parser.parse_args(argv)
    day = None
    if args.date:
        day = datetime.strptime(args.date, "%Y-%m-%d").astimezone()
    summary = summarize_day(day)
    if args.json:
        out = {
            k: summary[k]
            for k in (
                "path",
                "total",
                "freeform_count",
                "cancelled_count",
                "unexpected_count",
                "policy_count",
                "freeform",
                "cancelled",
                "unexpected",
                "policy",
            )
        }
        if not args.freeform_only:
            out["all"] = summary["all"]
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0

    print(f"MCQ log: {summary['path']}")
    print(
        f"total={summary['total']}  freeform={summary['freeform_count']}  "
        f"cancelled={summary['cancelled_count']}  "
        f"unexpected={summary['unexpected_count']}  "
        f"policy={summary.get('policy_count', 0)}"
    )
    policy_rows = summary.get("policy") or []
    if policy_rows and not args.freeform_only:
        print("\nPOLICY decisions (highest risk — review in EOD Hansei):")
        for r in policy_rows:
            ts = r.get("ts", "?")
            agent = r.get("agent") or "-"
            title = r.get("title") or "-"
            chosen = r.get("chosen_label") or r.get("chosen_id") or (
                "CANCEL" if r.get("cancelled") else "?"
            )
            print(f"- {ts} [{agent}] {title} → {chosen}")
    focus = summary["unexpected"] if args.freeform_only else summary["unexpected"]
    if not focus:
        if not policy_rows:
            print("(no freeform/cancel/unexpected rows)")
        return 0
    print("\nFreeform / cancel / unexpected (review in EOD Hansei):")
    for r in focus:
        ts = r.get("ts", "?")
        agent = r.get("agent") or "-"
        title = r.get("title") or "-"
        q = (r.get("question") or "")[:120]
        if r.get("cancelled"):
            print(f"- {ts} [{agent}] CANCEL {title}: {q}")
            if r.get("cancel_reason"):
                print(f"    reason: {r['cancel_reason']}")
        else:
            ff = r.get("freeform_text") or r.get("chosen_label") or r.get("chosen_id")
            print(f"- {ts} [{agent}] {title}: {q}")
            print(f"    → {ff}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
