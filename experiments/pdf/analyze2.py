"""Judge-free summary: per model and item class, check pass rate, compile errors, cost;
review.md lists every failing (item, model) with its diff and transcription."""
import collections, json, sys
from pathlib import Path
out = Path(sys.argv[1])
rs = [json.loads(l) for l in (out / "results.jsonl").read_text().splitlines()]
TREES = {"ex25", "ex29", "ex34", "ex41", "ex44", "ex51", "ex52", "ex57"}
NODES = {"c25", "c29", "c34", "c57"}   # claims about one tree node: SyncTeX mislocates them
cls = lambda i: "tree" if i in TREES else "node" if i in NODES else "other"
ok = lambda r: r["check"] is not None and r["check"]["chars_ok"] and r["check"]["levels_ok"]
models = [m for m in ["haiku", "sonnet", "opus"] if any(r["model"] == m for r in rs)]
print(f"{'model':7} {'class':6} {'n':>3} {'pass':>4} {'chars':>5} {'levels':>6} {'compile':>7} {'$/item':>7}")
for m in models:
    for c in ["other", "tree", "node"]:
        xs = [r for r in rs if r["model"] == m and cls(r["id"]) == c]
        if not xs: continue
        print(f"{m:7} {c:6} {len(xs):3} {sum(map(ok, xs)):4} "
              f"{sum(r['check'] is not None and not r['check']['chars_ok'] for r in xs):5} "
              f"{sum(r['check'] is not None and r['check']['chars_ok'] and not r['check']['levels_ok'] for r in xs):6} "
              f"{sum(r['check'] is None for r in xs):7} {sum(r['cost'] for r in xs)/len(xs):7.4f}")
by = collections.defaultdict(dict)
for r in rs: by[r["id"]][r["model"]] = r
both = sorted(i for i, d in by.items() if cls(i) == "other" and all(m in d and not ok(d[m]) for m in models))
print("other items failing for every model:", len(both), both)
print(f"total ${sum(r['cost'] for r in rs):.2f}")
with (out / "review.md").open("w") as fh:
    for r in sorted(rs, key=lambda r: (r["id"], r["model"])):
        if ok(r) or cls(r["id"]) != "other": continue
        c = r["check"]
        fh.write(f"## {r['id']} {r['model']}\n")
        fh.write(f"compile error: {r['compile_error']}\n" if c is None else
                 f"chars: {json.dumps(c['chars'], ensure_ascii=False)}\nlevels: {json.dumps(c['levels'], ensure_ascii=False)}\n")
        fh.write("```\n" + r["latex"] + "\n```\n\n")
