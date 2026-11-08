"""PDF transcription measurement (scratch): crop each math item of claims.json via SyncTeX,
transcribe it with isolated claude -p vision calls, check the transcription against the PDF's
glyphs, and judge it against the true LaTeX source.

usage: measure.py BASE CLAIMS OUT [--ids a,b] [--models haiku,sonnet,opus] [--jobs N] [--no-judge]
"""
import argparse, base64, collections, concurrent.futures as cf, json, os, re, subprocess
import sys, tempfile, unicodedata
from pathlib import Path
import pymupdf

ap = argparse.ArgumentParser()
ap.add_argument("base"); ap.add_argument("claims"); ap.add_argument("out")
ap.add_argument("--ids"); ap.add_argument("--models", default="haiku,sonnet,opus")
ap.add_argument("--jobs", type=int, default=6); ap.add_argument("--no-judge", action="store_true")
ap.add_argument("--judge-model", default="opus")
ap.add_argument("--recheck", action="store_true", help="recompute checks on stored transcriptions; no model calls")
args = ap.parse_args()
BASE = Path(args.base); SRC = BASE / "src"; OUT = Path(args.out); OUT.mkdir(exist_ok=True)
PDF = SRC / "paper.pdf"
TEX_LINES = (SRC / "paper.tex").read_text().splitlines()
PREAMBLE = "\n".join(TEX_LINES[:TEX_LINES.index("\\begin{document}")])

# ---------- locate (SyncTeX) and crop ----------

def boxes(line):
    out = subprocess.run(["synctex", "view", "-i", f"{line}:0:paper.tex", "-o", "paper.pdf"],
                         capture_output=True, text=True, cwd=SRC).stdout
    res = []
    for blk in out.split("Output:")[1:]:
        kv = dict(re.findall(r"^(\w+):(.*)$", blk, re.M))
        p, h, v, W, H = int(kv["Page"]), *(float(kv[k]) for k in "hvWH")
        if H > 40:          # a page- or paragraph-level box, not a line
            continue
        res.append((p, h, v - H, h + W, v + 0.35 * H))   # depth not reported: allow ~1/3 of H
    return res

def regions(item):
    """One clip per page: the largest vertical cluster of the item's line boxes on that page,
    after dropping header/footer bands (SyncTeX ties \\ex/\\label lines to them)."""
    a, b = item["source"]["lines"]
    per_page = collections.defaultdict(list)
    for ln in range(a, b + 1):
        for p, x0, y0, x1, y1 in boxes(ln):
            if y1 < 100 or y0 > 705:
                continue
            per_page[p].append((x0, y0, x1, y1, ln))
    regs = []
    for p, bs in sorted(per_page.items()):
        bs.sort(key=lambda t: t[1])
        clusters, cur = [], [bs[0]]
        for bx in bs[1:]:
            if bx[1] - max(c[3] for c in cur) > 30:
                clusters.append(cur); cur = [bx]
            else:
                cur.append(bx)
        clusters.append(cur)
        best = max(clusters, key=lambda c: (len({t[4] for t in c}), len(c)))
        regs.append((p, len({t[4] for t in best}),
                     (p, min(t[0] for t in best) - 2, min(t[1] for t in best) - 2,
                      max(t[2] for t in best) + 2, max(t[3] for t in best) + 2)))
    # a page whose best cluster has fewer source lines than another page's is a stray hit
    # unless the item really spans pages (its lines split across consecutive pages)
    top = max(n for _, n, _ in regs)
    keep = [r for p, n, r in regs if n == top or n >= 2]
    return keep

# ---------- glyphs ----------

# Fonts without a ToUnicode map: glyph -> symbol ("" = drop: an extensible piece other than
# the one that stands for the delimiter). Calibrated by rendering every \\big..\\Bigg / \\left size
# (cal/cal.tex). Their glyphs get level 0: big operators and delimiters sit off the baseline.
def _cmex():
    t = {}
    for chars, sym in [("\x00\x10\x12\uf8eb", "("), ("\x01\x11\x13!\uf8f6", ")"),
                       ("\x08n\x1a(\uf8f1", "{"), ("\to\x1b)\uf8fc", "}"),
                       ("\x02h\x14\"\uf8ee", "["), ("\x03i\x15#\uf8f9", "]"),
                       ("\nD\x1c*", "⟨"), ("\x0bE\x1d+", "⟩"), ("\x04j\x16$", "⌊"), ("\x05k\x17%", "⌋"),
                       ("\x0c", "|"), ("\r", "‖"), ("\x0e.\x1e,", "/"),
                       ("S[", "⋃"), ("T\\", "⋂"), ("PX", "∑"), ("QY", "∏"), ("RZ", "∫"),
                       ("W_", "⋁"), ("V^", "⋀"), ("LM", "⨁"), ("`a", "∐"),
                       ("z{|}", "⏞"), ("bcd", "ˆ"), ("efg", "˜"), ("pqrst", "√"),
                       ("\uf8ec\uf8ed\uf8f7\uf8f8\uf8f4\uf8f2\uf8f3\uf8fd\uf8fe\uf8ef\uf8f0\uf8fa\uf8fbuv", "")]:
        for c in chars:
            t[c] = sym
    return t
FIX = {"stmary": {"J": "⟦", "q": "⟦", "K": "⟧", "y": "⟧"}, "cmex": _cmex()}
# Only presence counts: extensible pieces and repeated vertical segments, whose number
# depends on size.
PRESENCE = {"⏞", "|", "‖"}
EQUIV = {"\u20dd": "○", "◯": "○", "∗": "*", "_": ""}   # \\bigcirc/\\textcircled; \\_ is a rule in CM

def fix_for(font):
    f = font.lower()
    return next((t for k, t in FIX.items() if k in f), None)

def glyphs(page, clip, boxes_out=None):
    """(char, level) for every glyph whose centre is inside clip; level: 0 base, +1 raised, -1 lowered."""
    d = page.get_text("rawdict", clip=clip, sort=True)
    out = []
    for blk in d["blocks"]:
        for line in blk.get("lines", []):
            chars = [(c, s) for s in line["spans"] for c in s["chars"]]
            if not chars:
                continue
            sizes = collections.Counter(round(s["size"], 1) for _, s in chars)
            base = sizes.most_common(1)[0][0]
            ys = collections.Counter(round(c["origin"][1]) for c, s in chars if round(s["size"], 1) == base)
            base_y = ys.most_common(1)[0][0]
            if chars[-1][0]["c"] in "-\u00ad":   # line-end hyphenation
                chars = chars[:-1]
            for c, s in chars:
                x0, y0, x1, y1 = c["bbox"]; cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
                if not (clip.x0 <= cx <= clip.x1 and clip.y0 <= cy <= clip.y1):
                    continue
                ch, table = c["c"], fix_for(s["font"])
                if table is not None:
                    ch = table.get(ch, ch)
                ch = EQUIV.get(ch, ch)
                if "csc" in s["font"].lower() or "caps" in s["font"].lower():   # small caps
                    ch = ch.upper()
                for u in unicodedata.normalize("NFKC", ch):
                    if u.isspace():
                        continue
                    dy = c["origin"][1] - base_y
                    small = s["size"] < 0.9 * base and table is None
                    lvl = 1 if small and dy < -1 else -1 if small and dy > 1 else 0
                    out.append((u, lvl))
                    if boxes_out is not None:
                        boxes_out.append(c["bbox"])
    return out

def render(latex):
    doc = ("\\documentclass[12pt]{article}\\usepackage{amsmath,amssymb,stmaryrd}"
           "\\usepackage[margin=1in]{geometry}\\pagestyle{empty}\\begin{document}\n"
           + latex + "\n\\end{document}\n")
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "t.tex").write_text(doc)
        r = subprocess.run(["pdflatex", "-interaction=nonstopmode", "-halt-on-error", "t.tex"],
                           cwd=d, capture_output=True, text=True, timeout=60)
        if not (Path(d) / "t.pdf").exists():
            err = [l for l in r.stdout.splitlines() if l.startswith("!")][:2]
            return None, "; ".join(err) or "no pdf"
        doc = pymupdf.open(Path(d) / "t.pdf")
        gl = [g for pg in doc for g in glyphs(pg, pg.rect)]
        return gl, None

def compare(orig, trans):
    """Multiset difference of characters, then of (char, level)."""
    def cap(cnt):
        return collections.Counter({k: (1 if (k if isinstance(k, str) else k[0]) in PRESENCE else n)
                                    for k, n in cnt.items()})
    orig = [(c, 0 if c in PRESENCE else l) for c, l in orig]
    trans = [(c, 0 if c in PRESENCE else l) for c, l in trans]
    co, ct = cap(collections.Counter(c for c, _ in orig)), cap(collections.Counter(c for c, _ in trans))
    lo, lt = cap(collections.Counter(orig)), cap(collections.Counter(trans))
    chars = {"missing": dict(co - ct), "extra": dict(ct - co)}
    levels = {"missing": [f"{c}@{l}" for (c, l), n in (lo - lt).items() for _ in range(n)],
              "extra": [f"{c}@{l}" for (c, l), n in (lt - lo).items() for _ in range(n)]}
    import difflib
    a = [c for c, _ in orig if c not in PRESENCE]; b = [c for c, _ in trans if c not in PRESENCE]
    lcs = sum(m.size for m in difflib.SequenceMatcher(None, a, b, autojunk=False).get_matching_blocks())
    common = sum((collections.Counter(a) & collections.Counter(b)).values())
    out_of_order = common - lcs
    return {"chars_ok": not chars["missing"] and not chars["extra"], "out_of_order": out_of_order,
            "levels_ok": not levels["missing"] and not levels["extra"],
            "chars": chars, "levels": levels}

# ---------- model calls (isolated, as formalize.call_claude) ----------

def claude(content, schema, system, model, effort=None):
    msg = {"type": "user", "message": {"role": "user", "content": content}}
    cmd = ["claude", "-p", "--tools", "", "--no-session-persistence", "--system-prompt", system,
           "--setting-sources", "", "--strict-mcp-config", "--disable-slash-commands",
           "--input-format", "stream-json", "--output-format", "stream-json", "--verbose",
           "--json-schema", json.dumps(schema), "--model", model] + (["--effort", effort] if effort else [])
    with tempfile.TemporaryDirectory() as cwd:
        out = subprocess.run(cmd, input=json.dumps(msg) + "\n", capture_output=True, text=True,
                             cwd=cwd, env=os.environ | {"DISABLE_PROMPT_CACHING": "1"}, timeout=600)
    for line in out.stdout.splitlines():
        ev = json.loads(line)
        if ev.get("type") == "result":
            if ev.get("is_error"):
                raise RuntimeError(ev.get("result"))
            return ev["structured_output"], ev["total_cost_usd"], ev["duration_ms"] / 1000
    raise RuntimeError(out.stderr[-500:] or "no result")

TRANSCRIBE_SYS = "You transcribe images of printed text into LaTeX. You transcribe; you never interpret or correct."
TRANSCRIBE = """Transcribe everything printed in the image(s) into LaTeX, exactly as printed: every symbol, \
subscript, superscript, bracket, and word, in order, including example numbers and labels like (12) or a. \
If several images are given, they are consecutive parts of one passage.
Write a LaTeX document body (no preamble, no \\documentclass) that compiles with only the packages \
amsmath, amssymb and stmaryrd. Use \\llbracket/\\rrbracket for double square brackets. Don't define macros. \
Don't fix anything that looks like an error: transcribe it as printed."""
T_SCHEMA = {"type": "object", "properties": {"latex": {"type": "string"}}, "required": ["latex"]}

JUDGE_SYS = "You compare two LaTeX sources for what they print."
JUDGE = """SOURCE is part of a paper's LaTeX (its preamble, with the paper's macros, is given). \
TRANSCRIPTION was made from an image of the printed region of SOURCE's lines; the image may cut \
off or include a little text at its edges.
List every difference in what the two would PRINT, within the text both cover: a different, \
missing or extra symbol, word, sub/superscript, bracket, or grouping. Ignore fonts (italic vs \
upright included), spacing, line breaks, alignment, environment and layout markup, how a symbol \
is spelled in LaTeX (\\{ vs a set macro), and text at the edges that only one of them covers.
`same` is true if there is no difference.

--- PREAMBLE ---
{pre}

--- SOURCE ---
{src}

--- TRANSCRIPTION ---
{tr}"""
J_SCHEMA = {"type": "object", "properties": {
    "same": {"type": "boolean"},
    "differences": {"type": "array", "items": {"type": "string"}}},
    "required": ["same", "differences"]}

# ---------- main ----------

items = json.loads(Path(args.claims).read_text())
items = items if isinstance(items, list) else items["items"]
items = [i for i in items if "\\(" in i["latex"] or "$" in i["latex"]]
if args.ids:
    want = args.ids.split(","); items = [i for i in items if i["id"] in want]
models = args.models.split(",")
doc = pymupdf.open(PDF)

def prep(item):
    regs = regions(item)
    imgs, orig = [], []
    for k, (p, x0, y0, x1, y1) in enumerate(regs):
        page = doc[p - 1]; clip = pymupdf.Rect(x0, y0, x1, y1)
        bb = []
        g = glyphs(page, clip, bb)
        if bb:   # snap to the glyphs inside, so no half-cut line shows at the edges
            clip = pymupdf.Rect(min(b[0] for b in bb) - 1.5, min(b[1] for b in bb) - 1.5,
                                max(b[2] for b in bb) + 1.5, max(b[3] for b in bb) + 1.5)
            g = glyphs(page, clip)
        f = OUT / f"{item['id']}.{k}.png"
        page.get_pixmap(clip=clip, dpi=200).save(f)
        imgs.append(f); orig += g
    src = "\n".join(TEX_LINES[item["source"]["lines"][0] - 1: item["source"]["lines"][1]])
    return {"id": item["id"], "regions": regs, "imgs": imgs, "orig": orig, "src": src}

def run(p, model):
    content = [{"type": "image", "source": {"type": "base64", "media_type": "image/png",
                "data": base64.b64encode(f.read_bytes()).decode()}} for f in p["imgs"]]
    content.append({"type": "text", "text": TRANSCRIBE})
    effort = "low" if model == "haiku" else None
    t, cost, secs = claude(content, T_SCHEMA, TRANSCRIBE_SYS, model, effort)
    gl, err = render(t["latex"])
    retried = None
    if err:      # one retry with the compiler's error, as the tool would do
        retried = err
        content[-1] = {"type": "text", "text": TRANSCRIBE + "\n\nYour previous transcription:\n"
                       + t["latex"] + "\n\ndid not compile: " + err + "\nFix it."}
        t, c2, s2 = claude(content, T_SCHEMA, TRANSCRIBE_SYS, model, effort)
        cost += c2; secs += s2
        gl, err = render(t["latex"])
    rec = {"id": p["id"], "model": model, "latex": t["latex"], "cost": cost, "secs": secs,
           "compile_error": err, "retried_after": retried}
    rec["check"] = compare(p["orig"], gl) if gl is not None else None
    if not args.no_judge:
        j, jc, _ = claude([{"type": "text", "text": JUDGE.replace("{pre}", PREAMBLE).replace("{src}", p["src"]).replace("{tr}", t["latex"])}],
                          J_SCHEMA, JUDGE_SYS, args.judge_model)
        rec["judge"] = j; rec["judge_cost"] = jc
    return rec

preps = [prep(i) for i in items]
if args.recheck:
    by = {p["id"]: p for p in preps}
    rs = [json.loads(l) for l in (OUT / "results.jsonl").read_text().splitlines()]
    def re1(r):
        gl, err = render(r["latex"])
        r = dict(r, compile_error=err)
        r["check"] = compare(by[r["id"]]["orig"], gl) if gl is not None else None
        return r
    with cf.ThreadPoolExecutor(args.jobs) as ex:
        rs = list(ex.map(re1, rs))
    (OUT / "results.recheck.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rs))
    print(f"rechecked {len(rs)}"); sys.exit()
(OUT / "regions.json").write_text(json.dumps(
    [{k: (v if k != "imgs" else [str(x) for x in v]) for k, v in p.items() if k != "orig"} for p in preps],
    indent=1, ensure_ascii=False))
print(f"{len(preps)} items, {sum(len(p['regions']) for p in preps)} regions; models {models}", flush=True)
res_path = OUT / "results.jsonl"
done = set()
if res_path.exists():
    done = {(r["id"], r["model"]) for r in map(json.loads, res_path.read_text().splitlines())}
jobs = [(p, m) for p in preps for m in models if (p["id"], m) not in done]
with cf.ThreadPoolExecutor(args.jobs) as ex, res_path.open("a") as fh:
    futs = {ex.submit(run, p, m): (p["id"], m) for p, m in jobs}
    for f in cf.as_completed(futs):
        iid, m = futs[f]
        try:
            r = f.result()
        except Exception as e:
            print(f"{iid} {m}: ERROR {e}", flush=True); continue
        fh.write(json.dumps(r, ensure_ascii=False) + "\n"); fh.flush()
        ck = r["check"]
        print(f"{iid:14} {m:6} check={'compile-err' if ck is None else ('ok' if ck['chars_ok'] and ck['levels_ok'] else 'chars' if not ck['chars_ok'] else 'levels')}"
              f" judge={'-' if 'judge' not in r else ('same' if r['judge']['same'] else 'DIFF')} ${r['cost'] + r.get('judge_cost', 0):.3f}",
              flush=True)
