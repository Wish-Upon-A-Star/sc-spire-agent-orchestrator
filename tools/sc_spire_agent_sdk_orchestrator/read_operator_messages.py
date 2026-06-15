"""Read queued operator messages for the main Codex orchestrator thread."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
MESSAGES = REPO_ROOT / "output" / "agent_orchestrator_runs" / "operator_messages.jsonl"


def read_messages(limit: int) -> list[dict[str, object]]:
    if not MESSAGES.exists():
        return []
    rows: list[dict[str, object]] = []
    for line in MESSAGES.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows[-limit:]


def main() -> int:
    parser = argparse.ArgumentParser(description="Read queued operator messages.")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    rows = read_messages(args.limit)
    if args.json:
        print(json.dumps({"messages": rows}, ensure_ascii=False, indent=2))
        return 0
    if not rows:
        print("No operator messages queued.")
        return 0
    for row in rows:
        print(f"[{row.get('status')}] {row.get('created_at')} target={row.get('target')} thread={row.get('target_thread_id')}")
        print(row.get("message", ""))
        print("")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
