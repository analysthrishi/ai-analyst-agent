import glob
import json

rows = []
for path in glob.glob("evals/results/*.json"):
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    rows.append((d.get("run_at", ""), d.get("version", path), d["score"], d["total"]))

print(f"{'version':26} {'score':>8}   date")
for run_at, version, score, total in sorted(rows):
    print(f"{version:26} {str(score) + '/' + str(total):>8}   {run_at[:10]}")