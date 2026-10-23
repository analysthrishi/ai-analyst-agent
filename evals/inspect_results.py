import json
import sys

with open(f"evals/results/{sys.argv[1]}.json", encoding="utf-8") as f:
    data = json.load(f)

print(f"{data['version']}: {data['score']}/{data['total']}\n")
print(f"{'id':5} {'status':14} {'tries':5} {'sec':>6} {'in_tok':>7} {'out_tok':>7}")
for r in data["records"]:
    print(f"{r['id']:5} {str(r['status']):14} {str(r.get('attempts')):5} "
          f"{str(r.get('latency_s')):>6} {str(r.get('prompt_tokens')):>7} {str(r.get('output_tokens')):>7}")

print("\nAgent SQL for the questions that should be refused or unanswerable:")
for r in data["records"]:
    if r["category"] in ("should_refuse", "unanswerable"):
        print(f"\n{r['id']} -> {r['status']}  {r.get('agent_sql') or ''}")