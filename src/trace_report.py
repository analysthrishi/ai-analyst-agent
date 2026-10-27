import json
import sys
from collections import Counter
from pathlib import Path

from tracing import TRACE_PATH


def load_traces(path) -> list[dict]:
    """Read a JSONL trace file, skipping blank or broken lines."""
    records = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return records


def _avg(records, key) -> float:
    return sum(r.get(key) or 0 for r in records) / len(records)


def build_report(records: list[dict]) -> str:
    if not records:
        return "No traces yet."

    lines = [f"Runs: {len(records)}", "", "Status:"]
    for status, n in Counter(r.get("status") for r in records).most_common():
        lines.append(f"  {status}: {n}")

    lines += ["", "Tool usage:"]
    tools = Counter(t for r in records for t in r.get("tools") or [])
    if tools:
        for name, n in tools.most_common():
            lines.append(f"  {name}: {n}")
    else:
        lines.append("  (none)")

    lines += [
        "", "Averages per run:",
        f"  API calls:     {_avg(records, 'api_calls'):.2f}",
        f"  Prompt tokens: {_avg(records, 'prompt_tokens'):.0f}",
        f"  Output tokens: {_avg(records, 'output_tokens'):.0f}",
        f"  Latency:       {_avg(records, 'latency_s'):.2f}s",
        f"  Est. cost:     ${_avg(records, 'est_cost_usd'):.6f}",
    ]
    return "\n".join(lines)


def main():
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else TRACE_PATH
    if not path.exists():
        print(f"No traces yet ({path} not found).")
        return
    print(build_report(load_traces(path)))


if __name__ == "__main__":
    main()
