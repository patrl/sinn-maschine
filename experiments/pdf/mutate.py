"""Mutation test of the glyph check: plant typical misreadings in transcriptions that pass,
and count which the check catches (bag of chars / levels / order). No model calls."""
import json, re, sys, collections, concurrent.futures as cf
sys.argv = [sys.argv[0], sys.argv[1], sys.argv[2], sys.argv[3], "--recheck"]   # reuse measure.py setup
src = open(sys.argv[0].replace("mutate.py", "measure.py")).read()
src = src[:src.index("if args.recheck:")]          # definitions + preps only
exec(compile(src, "measure.py", "exec"))
by = {p["id"]: p for p in preps}
TWO_D = {"ex25","ex29","ex34","ex41","ex44","ex51","ex52","ex57","c25","c29","c34","c57","c69","c70","c75","ex2"}
rs = [json.loads(l) for l in (OUT / "results.recheck.jsonl").read_text().splitlines()]
good = [r for r in rs if r["model"] == "sonnet" and r["id"] not in TWO_D and r["check"]
        and r["check"]["chars_ok"] and r["check"]["levels_ok"] and r["check"]["out_of_order"] == 0]
MUT = {
    "swap-args (x)(y)":  (r"\((\w)\)\((\w)\)", lambda m: f"({m[2]})({m[1]})" if m[1] != m[2] else None),
    "fn<->arg p(w)":     (r"(?<![\\\w])([a-zA-Z])\((\w)\)", lambda m: f"{m[2]}({m[1]})" if m[1] != m[2] else None),
    "iota->imath":       (r"\\iota\b", lambda m: r"\imath"),
    "forall<->exists":   (r"\\(forall|exists)\b", lambda m: r"\exists" if m[1] == "forall" else r"\forall"),
    "subseteq->supseteq":(r"\\subseteq\b", lambda m: r"\supseteq"),
    "drop subscript":    (r"_(\{[^{}]*\}|\w)", lambda m: ""),
    "sub->sup":          (r"_(\{[^{}]*\}|\w)", lambda m: "^" + m[1]),
    "drop prime":        (r"'", lambda m: ""),
}
def mutate(latex, pat, f):
    for m in re.finditer(pat, latex):
        rep = f(m)
        if rep is not None:
            return latex[:m.start()] + rep + latex[m.end():]
    return None
jobs = [(name, r) for name in MUT for r in good]
def run(job):
    name, r = job
    mutated = mutate(r["latex"], *MUT[name])
    if mutated is None:
        return name, None
    gl, err = render(mutated)
    if gl is None:
        return name, "compile"
    c = compare(by[r["id"]]["orig"], gl)
    return name, ("bag" if not c["chars_ok"] else "levels" if not c["levels_ok"]
                  else "order" if c["out_of_order"] else "MISSED")
tally = collections.defaultdict(collections.Counter)
with cf.ThreadPoolExecutor(8) as ex:
    for name, res in ex.map(run, jobs):
        if res: tally[name][res] += 1
print(f"{len(good)} clean linear transcriptions (sonnet) as base")
for name in MUT:
    t = tally[name]; n = sum(t.values())
    print(f"{name:20} n={n:3}  caught={n - t['MISSED']:3}  missed={t['MISSED']:3}   {dict(t)}")
