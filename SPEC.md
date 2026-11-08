# Sinnmaschine: specification

This file says what the project is for and what it must and must not do.
`TODO.org` tracks progress. If the two disagree, change the code or change
this spec on purpose. Don't let them drift apart quietly.

## 1. Purpose

An author installs the tool and gives it a paper, usually their own
formal-semantics paper. The tool:

1. **extracts** the paper's theoretical definitions and claims;
2. **formalizes** them in Lean, checking with the author at each step that
   the Lean says what the paper means;
3. **exposes errors**: it proves each claim, or it refutes the claim with a
   machine-checked counterexample;
4. **produces an oracle**: an executable Lean model of the theory that the
   author can query with new predictions the paper never states.

The main audience is the author, not a referee. The tool is a collaborator
that makes the theory precise and tells the author where it breaks.

## 2. Users and inputs

- **User**: a semanticist who can read Lean statements with some help but
  shouldn't have to write Lean. The tool never assumes Lean expertise. Every
  question to the user pairs the Lean with a plain-language or LaTeX
  rendering.
- **Source**: one paper, given as
  - LaTeX source: a single file, or a main file with `\input`/`\include`
    and author macros. This is preferred because formulas come through
    exactly.
  - PDF, as a fallback. Formulas and trees read from a PDF are
    unreliable, so every one an extracted item uses is checked (see "PDF
    input" below). Since the user is usually the author, the runner asks
    for the LaTeX source before converting a PDF (an arXiv e-print has
    it too).
- **Optional**: notes from the user, such as "Def 3 is meant
  intensionally" or "ignore §6". These go into every later step.
- **Preprocessing** is deterministic and done by the runner, once, before
  any model call. Its output is saved in the run directory (`source/`) and
  every later stage reads it from there:
  - multi-file LaTeX is flattened (e.g. `latexpand`);
  - author macros are expanded (e.g. `de-macro`, or the runner's own
    expander), keeping the original next to the expanded text so the
    review file can quote the paper as written;
  - a PDF is converted to LaTeX (see "PDF input" below).

  Model calls never do this work themselves, and no LaTeX tool or MCP is
  given to them. The one exception is the transcription calls for PDF
  input, below.

### PDF input

No reader of a PDF is free of errors, so accuracy comes from checking, not
from the choice of reader. For a PDF with a text layer (one produced
directly from LaTeX), the check is deterministic: the text layer has the
exact characters, the model's transcription supplies the structure, and the
two must agree. No local models are used.

1. **Prose from the text layer.** It is exact (e.g. via PyMuPDF or
   `pdftotext`), apart from line-end hyphenation and running headers,
   which the runner removes.
2. **Find the math by font, not by a model.** The text layer records the
   font of every glyph, and math is set in its own fonts (math italic,
   symbol, extension, `stmaryrd`, …). The runner groups math glyphs into
   regions (a display, an example, an inline formula with its line) and
   crops each one, snapped to whole lines.
3. **Transcribe each region** with an isolated vision call (see "The
   transcription calls" below), which returns LaTeX. Results are cached
   per region.
4. **Check each transcription against the text layer.** The runner
   compiles the transcription, reads the glyphs of the result, and
   compares them with the glyphs of the original region:
   - **characters**: the same multiset, after a per-font normalization
     table for fonts without a Unicode map (e.g. the TeX extension font's
     delimiter sizes, calibrated by rendering each size once);
   - **levels**: each glyph raised, lowered or on the baseline, from its
     size and baseline relative to its line;
   - **order**: the two sequences in reading order align with nothing out
     of place. This is what catches swapped arguments (`(x)(y)` for
     `(y)(x)`), which the first two checks cannot see. It applies only to
     linear material: a two-dimensional layout (a tree, a multi-line
     display, a label over a brace) is checked for characters and levels
     only.

   A transcription that fails is retried once with the compiler's error
   (if it failed to compile), then once with a stronger model. One that
   still fails is put to the user at checkpoint 1, with the crop and the
   rendered transcription side by side and the differences listed, but
   only if an extracted item uses it. The rest stay recorded as unchecked.
5. **Trees and diagrams.** In semantics they carry content (LFs,
   derivations, lattices). A vision call transcribes each tree into
   labelled bracket notation; the runner re-renders it (e.g. with
   `forest`) and shows it next to the crop. The node labels are checked
   against the text layer, but the branching is drawn as lines, not
   glyphs, so trees always need the user's confirmation. Figures with no
   formal content are ignored, and the runner says so.
6. **No text layer** (a scanned PDF): nothing deterministic to check
   against, so every formula and tree an extracted item uses goes to the
   user. A commercial OCR service (e.g. Mathpix) sends an unpublished
   paper to a third party, so it is used only with the user's consent.

**What the check cannot see**: anything drawn as a line (fraction bars,
`\overline`, tree branches), and grouping that prints identically. These
are the residual risk on a passed item.

**The transcription calls** are model calls made by the runner during
preprocessing, as an exception to the rule above. They are isolated like
the back-translator (§4, "Blind back-translation"): each sees one crop and
an instruction to transcribe it, nothing else, so it can only transcribe,
not interpret. They get an allowed package list wide enough for what
papers print (e.g. `pifont` for ✓/✗), and no tools: the image is passed
as content. Default model: Sonnet at its default effort, escalating to
Opus on a failed check (see TODO.org, "PDF input", for the measurement
behind this). Their prompts and outputs go in `log/`.

**Disclosure.** The review files and the report say for each item whether
its formulas came from LaTeX source, passed the check, or were confirmed
by the user, and list the checks that don't apply to it (order, for a
two-dimensional layout).

## 3. Outputs

Everything goes in one run directory per paper (currently `runs/<paper>/`).

| Artifact | Contents |
|---|---|
| `source/` | The preprocessed paper (flattened, macros expanded, or converted from PDF) plus the original; for a PDF also block positions, crops and the per-item read check (§2, "PDF input") |
| `claims.json` | Extracted items: id, kind (`definition` / `claim` / `example`), label, verbatim LaTeX, faithful informal statement, analysis (examples: the LF and/or translation the paper assigns), dependencies, concerns, and source location (computed by the runner by finding the verbatim LaTeX in the source, never reported by the model). Approval status is not stored here: it lives in `decisions.json` |
| `Defs.lean` | The theory: types, lexicon, composition rules, model class, definitions, numbered examples and their representations |
| `Concepts.lean` | Notions that claims need but the paper doesn't define as such, built on `Defs.lean` (stage 2b, see "Concepts" in §4) |
| `statements.json` | Per claim: its Lean statement (a closed `Prop`, from stage 3) and notes. Frozen once approved: stage 4 proves or refutes exactly this |
| `claims/<id>.lean` | One file per claim: a theorem `<id>` (proved) or `<id>_false : ¬ …` (refuted, with a counterexample) |
| `General.lean`, `generalizations.json` | Stage 4b results (see "Generalization" in §4): general lemmas, each with the corollary proofs of the claims it covers, the definitions it proposes, and the user's verdict on it |
| `Oracle.lean` (+ CLI wrapper) | The executable oracle (§6) |
| `results.json` | Per claim: outcome, Lean's own rendering of the statement, axioms used, attempts, cost |
| `review/<stage>.md` | One review file per checkpoint halt (§4) |
| `decisions.json` | Every ruling, the user's and the orchestrator's, with its source; the only decision record the runner reads |
| `report.md` | The author-facing summary (§7) |
| `log/` | Every model call, every Lean attempt, and every user decision, so the run can be reconstructed |

A run must be **resumable**. Re-running a step uses decisions the user
already approved and asks again only about things that have changed.

## 4. Pipeline and fidelity checkpoints

There are two layers, kept apart:

- **The runner** (`formalize.py`): runs the stages on its own and **halts**
  at each checkpoint. Its state is saved to disk, and it is restarted with
  `--resume`. It never talks to the user directly.
- **The orchestrator** (a coding agent following instructions shipped
  with the project): launches the runner, reads each halt, makes the
  decisions that are its own, puts the others to the user in the
  conversation, records the answers, and resumes the run.

### Agent and model independence

Nothing in the design depends on a particular agent or model vendor:

- **The runner's model calls** go through one backend interface: a
  prompt, a JSON schema and a **tool allowlist** (empty by default) in,
  schema-valid JSON plus usage (cost, time) out. `claude -p` is one
  backend. Any other must pass the same interface and the acceptance
  suite (§10) before it is supported. The runner validates every reply
  against the schema itself.
- **The orchestrator's instructions** are one plain markdown file in the
  repo. Each agent gets a thin pointer to that file: a Claude Code skill,
  an `AGENTS.md` entry for Codex and similar agents. The pointers hold no
  instructions of their own, so the agents cannot drift apart.
- **Agent features are optional.** Where the agent supports structured
  questions (e.g. multiple choice), the orchestrator uses them. Otherwise
  it asks in plain text. The review file and `decisions.json` are the
  same either way.
- **Checks that need isolation are run by the runner**, as separate
  backend calls, never by the agent's own sub-agents. Code then enforces
  what each call can see, whatever agent drives the run.

### Tools for model calls

By default every model call is text in, JSON out, with no tools. Lean
feedback comes only from the runner's compile-and-retry loop (compile the
whole file, run `audit()`, return the errors, at most N attempts). Tools
are added per stage, by the runner's allowlist, and only where they pay
for themselves.

**Lean MCP** (e.g. `lean-lsp-mcp`) gives a call goal states, diagnostics
while it writes, and lemma search (Loogle / LeanSearch-style).

- **Which stages may use it:** only the stages that write Lean, i.e.
  definitions (stage 2) and prove/refute (stage 4). Stage 3 (stating
  claims) may use it for lemma *search* only, never to try proofs, so
  that whether a statement can be proved doesn't shape how it is stated.
- **Which stages never use it:** extraction, back-translation and
  comparison, and every other check that needs isolation. Hover text,
  docstrings and file outlines would leak the intended meaning to the
  translator.
- **What it does not change:**
  - only the final file decides the outcome. It is compiled from scratch
    and must pass `audit()`. Nothing the MCP reports during the call
    counts;
  - a call with the Lean MCP gets no other tools: no file writes, no
    shell. It returns its Lean as JSON like any other call;
  - a backend without MCP support still works, by falling back to the
    compile-and-retry loop.
- **Prerequisites:** the run directory is a Lake project (§8), so the MCP
  sees `Defs.lean` and the dependencies the way the final compile does;
  the MCP's version is pinned next to the Lean toolchain.
- **When to turn it on.** It is adopted when either trigger fires, and
  kept only if the comparison below favours it:
  1. the run depends on a large library (linglib, Mathlib), where lemma
     names can't be guessed and the alternative is a hand-written cheat
     sheet;
  2. on the acceptance suite or a real paper, the proving stage often
     ends **open** for lack of attempts, or takes more than ~2 attempts
     per claim on average.
- **How to adopt it:** the proving stage is run on the same papers with
  and without the MCP, and compared on outcomes, attempts, cost and time.
  The MCP is enabled for a stage only if outcomes are at least as good
  and the cost is acceptable. The comparison is recorded in `TODO.org`,
  and the allowlist per stage is part of the run's config so a run can
  always be repeated without it.

### Who decides

Only the author can say what the paper *means*, so these decisions are
**the user's**:

1. **Interpretive choices** in definitions: wherever the paper is
   underspecified or open to more than one reading (e.g. "MON↓ 'defined
   analogously' read as …", "domain may be empty", "D_t = Bool").
2. **Statement fidelity**: whether each claim's Lean statement says what
   the paper claims.
3. **Coverage**: whether extraction missed or invented a definition,
   claim or example.
4. **Anything that would change an approved statement**: weakening it,
   adding a hypothesis, or redoing an approved item.

Everything else is **the orchestrator's**: Lean errors, retries, proof
strategy, audit failures, and how the formalization is organized. Each
call it makes is logged, and appears in the report (§7) under "the
agent's decisions" for the user to approve or overturn afterwards.

### Checkpoints

| # | Stage | Halts for the user on |
|---|---|---|
| 1 | **Extract** definitions, claims, and examples (numbered sentences + their LFs or translations), including claims stated only in running text | Coverage, and each informal `statement` |
| 2 | **Formalize definitions** (`Defs.lean`) | Each interpretive choice, listed separately with the alternative readings |
| 2b | **Concepts** (`Concepts.lean`), per batch of claims, before stating them | Each new notion: its definition, and the interpretive choice it makes |
| 3 | **State claims** (statement only, no proof yet) | Each statement's fidelity. *This is the key fidelity checkpoint*: a faithful statement that turns out false is a finding, and an unfaithful statement is a bug |
| 4 | **Prove / refute** | Nothing, unless the prover wants to change a statement (rule 4 above). Outcomes are reported, with each refutation's counterexample in the paper's own terms |
| 4b | **Generalize** (optional) | Each proposed result: is it meaningful and worth keeping? Nothing downstream depends on this stage, so a rejected result costs nothing |
| 5 | **Oracle** | A few sample queries whose answers the user already knows, as a sanity check |

### Concepts (stage 2b)

Some claims need notions that `Defs.lean` doesn't have: the paper uses
them without defining them as such. Examples from the first real paper:
"the LFs of sentence (3a)" (a derivation relation from a surface string to
its LFs) and "a pair-list reading". A statement can't define them itself:

- **Statements contain no definitions.** A statement is a single term over
  the reviewed vocabulary: no `def`, `inductive` or other commands.
  (`let` and `fun` inside the term are allowed, but they can't express
  recursive or inductive notions.)
- Why: a definition is an interpretive choice (a "derivation" relation is
  a theory of movement), which is the user's to review at a checkpoint,
  not hidden inside one statement. A definition can make a claim trivially
  true ("PL reading" too narrow → "no PL reading" holds by definition).
  And claims sharing a notion must share one definition, or they can
  disagree without anyone noticing.

So new notions get their own stage, before stating a batch of claims:

1. The model reads the batch's claims with `Defs.lean` and lists the
   notions they need that Defs doesn't have. It defines each **once**, in
   `Concepts.lean` (built on `Defs.lean`, same namespace), with notes on
   each interpretive choice and the alternative readings, as for Defs.
   Notions already in Defs are reused, never redefined.
2. **Checkpoint 2b**: the user reviews each new notion, as at checkpoint 2.
   Blind back-translation covers each definition here too.
3. `state` then sees Defs + Concepts. The no-definitions rule for
   statements is unchanged.

`Concepts.lean` grows batch by batch; an approved notion is frozen like a
statement. Back-translating a statement shows the translator Concepts as
well as Defs (stripped the same way). An approval records the hashes of
the definitions the statement depends on, so changing a notion voids the
approval of every statement that uses it.

### Generalization (stage 4b)

After prove/refute, an optional stage looks for stronger and more compact
results than the paper states. It **adds** results and never replaces
anything: approved statements, `claims/<id>.lean` and outcomes stay as
they are. Four operations, from safest to riskiest:

1. **Strengthen a proved claim**: drop hypotheses the proof doesn't use,
   or replace a specific example by a class of examples (e.g. a claim
   about the Hamblin set of (13) becomes one about every LF of the form
   *which-N λx. … ?*).
2. **Merge claims**: several claims are instances of one general lemma.
3. **Generalize a refutation**: the weakest added hypothesis under which
   the refuted claim holds. This is a suggested repair, so §9 applies: it
   is a separate proposal the user can accept, never a change to the claim.
4. **Simplify definitions**: a more compact definition in `Defs.lean` or
   `Concepts.lean`.

Rules, enforced by the runner:

- **Each original is a corollary.** A general result comes with a proof of
  each approved statement it claims to cover, derived from the general
  result (e.g. `theorem c13 : <approved statement> := gen_c13 ex13 …`).
  This is how Lean checks that a generalization covers the original and
  didn't quietly change it. Without these proofs, a result is not accepted.
- **Simplified definitions need an equivalence proof.** A new definition is
  accepted only with a theorem that it is equivalent to the old one
  (`old ↔ new`, or `old = new`). With that proof, existing approvals carry
  over without another review. Without it, the definition is only a
  proposal, and adopting it sends it back to checkpoint 2, voiding the
  approvals that depend on the old one.
- **New notions are concepts.** A generalization that needs a new notion
  (e.g. "LFs of the form which-N …") gets it from the concepts stage and
  checkpoint 2b, not from a definition of its own. The `audit()` rules for
  claim files apply to `General.lean`.
- **Screened for vacuity and triviality.** The runner checks with the
  oracle's bounded search (§6) that a result's hypotheses can all be true
  at once, and flags results that hold by unfolding definitions alone.

At **checkpoint 4b** the user judges whether each result is meaningful and
worth keeping. This is not a fidelity check, since these results are not
the paper's claims. Blind back-translation (below) is reused to explain
each general statement in plain English, but no comparison with the paper
is made, because there is nothing in the paper to compare it with.

Build order: first a mechanical pass with no model calls, which deletes
each hypothesis and replaces each specific constant by a variable, then
recompiles the existing proof. Then model-proposed generalizations, with
the corollary check. Simplifying definitions comes last.

### The review file

At each halt the runner writes `runs/<paper>/review/<stage>.md`. It has
one entry per pending item, containing:

- the paper's verbatim LaTeX and where it occurs;
- the Lean, as Lean's own `#check` rendering;
- the **blind back-translation** and its **comparison** with the paper
  (see "Blind back-translation" below);
- **example models** (stages 2–3): small models with what the definitions
  or the claim compute on them, from the executable fragment (e.g. "with
  no linguists, *every linguist sneezed* is **true**"). This lets the user
  check a reading without reading Lean;
- the orchestrator's **recommendation** and the reason for it;
- a `decision:` line: `approve`, `reject: <comment>`, or `choose: <reading>`.

### Blind back-translation

This is a required fidelity check at stages 2 and 3, for every definition
and every claim statement. It runs before the review file is written.

1. **Translate, at two depths.** A separate backend call made by the
   runner (not by the orchestrator) reads the Lean. It is given the item's Lean code, the parts of `Defs.lean`
   that the item uses, and a short glossary of identifiers (`sneezed`,
   `linguist`, …). It writes plain English in the register of a semantics
   paper, saying exactly what the Lean says: quantifier scope,
   hypotheses, the direction of entailment, edge cases such as an empty
   domain. It is told not to guess the intended meaning. It writes:
   - a **surface** reading, in the paper's own vocabulary (e.g. "(2)
     entails (3)");
   - an **unfolded** reading, with the definitions the item uses
     (lexicon, LFs, composition, entailment) expanded down to truth
     conditions over models (e.g. "in every model, if every linguist
     sneezed then some linguist sneezed").

   *As built (2026-11-06):* the translator gets the whole stripped
   `Defs.lean` rather than a slice of it, so its identifier names and types
   serve as the glossary; and it does the unfolding itself (mechanical
   unfolding in Lean is not built yet). The comparer gets the claim's LaTeX
   and the verbatim LaTeX of the paper's definitions and examples (from
   `claims.json`), not the extractor's paraphrases.

   The unfolded reading is what makes the check bite on claims. A claim
   stated in terms of `Defs.lean` matches the paper trivially at the
   surface, even when the definitions underneath are wrong. Where
   possible the runner unfolds the statement mechanically in Lean
   (`unfold` / `simp only` on the paper's definitions) and passes the
   result to the translator. Otherwise the translator unfolds it from the
   definitions it was given. For a definition, the two readings may
   coincide.
2. **Isolation.** The translator never sees the paper, `claims.json`, the
   informal `statement`, the formalizer's notes or comments, or the
   conversation. Comments are stripped from the Lean it receives. Only
   this isolation makes it a check: a translator who knows the intended
   claim tends to read it into the Lean. The runner builds the
   translator's prompt itself, so the isolation is enforced by code.
   Isolation covers two channels, and both must be closed:
   - **Content.** The prompt holds only the item's Lean (comments
     *and docstrings* stripped, since docstrings cite the paper's labels),
     the parts of `Defs.lean` it uses (stripped the same way), and the
     glossary. The glossary is generated mechanically from the Lean
     (identifier names and types), never from docstrings or the paper. The
     translator gets the statement, not the theorem name or claim id (an id
     like `every_entails_some` is itself a paraphrase).
   - **Process.** The backend's own context is a second channel. An agent
     CLI started in the repo picks up the repo path and name, git status
     and recent commit messages, project memory, `CLAUDE.md`/`AGENTS.md`,
     settings and hooks, MCP server instructions and skills (all observed
     with `claude -p` run from the repo), and commit messages and memory
     routinely describe the intended claims and planted errors. So the
     translator call (like every model call) runs from a fresh, empty,
     neutrally named temp directory (not one under a path that names the
     project), with a minimal system prompt, no tools, settings, MCP
     servers, skills or session persistence. Account-level context the
     CLI attaches regardless (e.g. the user's email) is acceptable: it
     says nothing about the paper.
   - **Checked, not assumed.** The acceptance suite (§10) plants a canary
     string in everything the translator must not see (the paper,
     `claims.json` statements and notes, Lean comments and docstrings, a
     commit message, memory) and asserts it appears in neither the
     translator's prompt nor its output; and a probe call through the same
     backend path asks the model to report its context, which must show
     no repo path, git information, memory or project files.
3. **Compare.** A second backend call reads both readings next to the paper's
   LaTeX (and, for the unfolded reading, the paper's own definitions).
   It lists every difference, each as one line, and classes it as:
   - **substantive**: the truth conditions differ, i.e. there is a model,
     or a reading of the paper, on which one is true and the other false
     (an added or missing hypothesis, a different quantifier or scope, a
     narrower or wider domain, a reversed direction). Where it can, it
     gives that model;
   - **choice**: the paper is ambiguous or underspecified at this point,
     and the formalization takes one reasonable reading; the comparison
     names the other reading. (E.g. "in any model where ann is a linguist,
     (2) entails (1)", where the paper's entailment quantifies over all
     models.) This surfaces the ambiguity without calling it an error;
   - **wording**: phrasing, notation, or order differ but the truth
     conditions are the same.

   If there is no difference, the result is "none found".
4. **Use.** Only a **substantive** difference flags the item. A
   **choice** is put to the user as a question about the reading (rule
   "Ambiguity is surfaced, not resolved" below) but doesn't flag the item. A flagged
   item is never approved automatically, not even under `--auto`. The
   orchestrator recommends redoing it or puts it to the user. Wording
   differences are shown in the review file but neither flag the item
   nor ask anything of the user. This keeps the flags rare enough that
   the user doesn't learn to approve without reading. Both readings and
   the comparison appear verbatim in the review file and are saved to
   `log/`.

The back-translation is evidence for the user, not a verdict. A clean
comparison does not replace the user's approval at checkpoint 3.

The orchestrator takes the user through the file in the conversation,
using multiple-choice questions where an item has a fixed set of readings
and the agent supports them.
The user may also edit the file directly. Either way, decisions go into
`runs/<paper>/decisions.json`, which is the only record the runner reads.

Rules:

- **Nothing downstream is built on output that hasn't been approved.**
- **Statements are frozen after stage 3.** The prove/refute stage may not
  change an approved statement. If the model thinks the statement is wrong,
  it halts and sends the case back to checkpoint 3. It may not weaken the
  statement, add hypotheses, or "fix" the claim on its own.
- **Ambiguity is surfaced, not resolved.** When the paper is underspecified,
  the review lists the readings and asks. Nothing is picked silently.
- **Per-item granularity.** A decision such as "approve all" covers a whole
  batch, and individual items can still be ruled on separately. Only
  rejected items and the items that depend on them are redone.
- **Recorded decisions are reused.** A resumed or re-run run does not ask
  about an item again unless the item has changed.
- A non-interactive mode (`--auto`) lets the orchestrator take its
  recommendation on every item, for testing and CI. Its output is then
  marked *unreviewed* everywhere it appears.

## 5. Exposing faulty claims

The paper may be wrong. Finding that out is a main goal of the tool, not a
failure mode.

- Every formalized claim ends in exactly one outcome:
  - **proved**: theorem `<id>` holds;
  - **refuted**: theorem `<id>_false : ¬ <claim>` holds, with an explicit
    countermodel the user can read;
  - **open**: neither direction could be established within budget. The
    oracle's bounded search result (§6) is reported alongside;
  - **blocked**: depends on a rejected or failed item.
- If the tool cannot prove a claim, it never reports it as true or as
  false. **open** is a valid, honest result.
- **Faithfulness beats provability.** Claims are formalized against the
  paper's *definitions* (e.g. the lexicon), not against the paper's own
  derived intermediate results. If the paper mis-derives a truth condition,
  the claims that rely on the mis-derivation must come out refuted, not
  inherit the error.
- For each refutation, the report traces the error back where possible:
  which definition, step, or earlier false claim is at fault (e.g. "(3) ⊨
  (6) rests on Prop 4, which is false").
- **No cheating** (already enforced by `audit()`, and must stay enforced):
  - only the axioms `propext`, `Classical.choice`, and `Quot.sound`;
  - no `sorry`, `admit`, `axiom`, `native_decide`, `unsafe`,
    `implemented_by`, or `extern`;
  - claim files may not add or shadow definitions;
  - the expected theorem name must exist with the approved statement.

## 6. The oracle

An executable model of the theory that the user can query with arbitrary
predictions.

- **Queries** use the paper's own vocabulary and examples, not raw Lean.
  At minimum:
  - the truth value of a sentence/LF in a given model;
  - whether a set of premises entails a conclusion, or whether sentences
    are contradictory;
  - whether a stated truth condition matches the computed one;
  - new sentences/LFs built from the lexicon, not just the paper's numbered
    examples.
- **Answers** are one of:
  - **counterexample found**: a concrete model, printed readably. This is a
    real refutation;
  - **no counterexample up to size n**: a *bounded* check, and it must be
    labelled as bounded, never as "valid";
  - **proved**: when a matching theorem exists in `claims/`.
- **Single source of truth.** The oracle's interpreter *is* the `Defs.lean`
  semantics, or is proved equivalent to it. It must never be possible for
  `#eval` and a theorem to disagree about the same claim.
  (`examples/toy/Fragment.lean` is a prototype of this.)
- **Usable without the agent.** Once the run is built, the user can query
  the oracle offline (via `lake exe oracle …` or a `#eval` scratch file),
  with no model calls. Optionally, the agent can turn a natural-language
  query into an oracle query, show it to the user for confirmation, and
  then run it.

## 7. Report

`report.md`, for the author:

- one row per claim: label, where it is in the paper, outcome, link to the
  Lean file;
- every refutation with its countermodel in the paper's notation and the
  traced source of the error;
- every interpretive choice made at checkpoint 2, with what the user chose;
- the agent's decisions (§4), each one open to approval or reversal;
- **open** claims with their bounded-check status;
- accepted generalizations (stage 4b): each general result, the claims it
  covers, and proposed repairs of refuted claims, kept apart from the
  paper's own claims;
- unreviewed items (from `--auto`) clearly marked.

## 8. Installation and runtime

- Installed by the user as a command-line runner plus the orchestrator
  instructions and their per-agent pointers (§4). The runner works without
  an agent (`--auto`, or editing review files by hand), so it can be tested
  on its own.
- Requires: a Lean toolchain (pinned version), and access to a supported
  model backend (§4). Optional: `lean-lsp-mcp`, pinned, for the stages
  that allow it (§4, "Tools for model calls"); LaTeX and PDF
  preprocessing tools (§2).
- **Supported** means the acceptance suite (§10) has passed with that
  backend and agent. So far the only backend is `claude -p` and the only
  target agent is Claude Code; the README says the project is tested only
  with Claude.
- The Lean side is a Lake project per run. Defs are compiled once and
  imported, not pasted into each file.
- Mathlib or linglib may be used as a dependency, with the version pinned.
  Core Lean stays the default until a paper needs more.
- Each run records its cost and time per stage.

## 9. Non-goals

- Not a referee or reviewer: it doesn't judge whether the theory is *good*,
  only what follows from it.
- Doesn't formalize empirical judgements, data, or prose argumentation,
  except where the paper turns them into theoretical claims.
- Doesn't silently repair the paper. Suggested fixes, such as "Prop 4
  holds if 'some' is replaced with 'every'", are allowed only as clearly
  separate proposals the user can accept.
- No guarantee of full coverage of every paper. Unsupported constructs are
  reported as such, not approximated.

## 10. Acceptance tests

`examples/toy/` is the regression suite. `EXPECTED.md` is the answer key
and is never shown to the pipeline.

- Extract finds all 14 claims, including the 5 that appear only in running
  text.
- 10 claims proved, the 4 planted errors refuted with the counterexamples
  listed in `EXPECTED.md`.
- Prediction 4 is proved *from the lexicon*, not from the mis-derived TC
  of (4).
- The oracle reproduces every ✓/✗ in `EXPECTED.md`, and answers at least
  one query about a sentence that is not in the paper.
- Blind back-translation catches unfaithful formalizations without
  crying wolf. On deliberately unfaithful variants:
  - claim statements: (2) ⊨ (3) with a non-emptiness hypothesis added (on
    the restrictor: toy models always have a non-empty domain),
    Prop 4 with `some` replaced by `every`, a TC with the scope of
    negation flipped;
  - definitions, where only the unfolded reading can show the error: a
    lexicon entry for *every* with existential import, an LF for (4) with
    negation scoped wrongly. The claim statements that use them are left
    unchanged;

  every variant must get a substantive flag. On the faithful toy
  formalization, no item may get a substantive flag. Wording differences
  are allowed.
- The translator is isolated (§4, "Blind back-translation"): canary
  strings planted in the paper, `claims.json`, Lean comments and
  docstrings, a commit message and memory appear in neither its prompt nor
  its output, and a context probe through the same backend path shows no
  repo path, git information, memory or project files.
- The cheat suite (fake model returning `axiom`, `native_decide`, shadowing
  defs, `sorry`) is rejected in full.

`examples/toy-fol/` is a second toy paper in a different style: no LFs or
composition rules, only intuitive first-order translations (two sentences
with surface and inverse scope readings). On it:

- Extract finds 6 examples (two with two readings), the definition, and all
  9 claims, including the 4 in running text, and flags the translation
  given only indirectly.
- `Defs.lean` transcribes the translations as given (no invented LF type or
  composition rules) and keeps the paper's non-empty domain.
- 5 claims proved and the 4 planted errors refuted with the countermodels
  in its `EXPECTED.md`; a claim about "both readings" is stated for both.

PDF input (§2): on the PDF of a paper whose LaTeX is in the suite, every
formula and tree an extracted item uses either matches the LaTeX or is put
to the user; none passes the check while differing from the source. Planted
misreadings (swapped arguments, ı for ι, ∀/∃, dropped or moved
subscripts, dropped primes) in correct transcriptions are all caught. The
transcription calls pass the same canary and context-probe checks as the
translator.

Before calling the project usable, add at least one real published
semantics paper with a hand-checked answer key.

## 11. Decided

- **Generated fragment, not a fixed library** (2026-11-05, for now): the
  model writes each paper's representations, model notion and
  interpretation in `Defs.lean`, because papers use very different
  conventions, and not all have LFs: many give intuitive translations into
  first-order logic or another representation language. Rule: whatever
  the paper specifies as a *procedure* (composition rules, a semantics for
  its logic, translation rules) is implemented once, generically, and every
  example's meaning is computed through it, never written by hand; whatever
  the paper *assigns* per sentence (an intuitive translation) is its
  analysis and is transcribed as given. Truth conditions the paper derives
  from either are claims. Every numbered example is a `def` named by its id. Cost: the
  interpreter is checked per paper (checkpoint 2, back-translation) rather
  than once, and the oracle is rebuilt per paper. Revisit if a family of
  papers shares enough machinery to justify a library.

## 12. Open decisions

- **Proofs about the executable interpreter**: how proofs and the
  `Bool`-valued `#eval` semantics are connected (one `Decidable`
  semantics, or two semantics plus an equivalence theorem).
- **Web review page** (later, maybe): the paper annotated in place, with
  pending items marked at their passages, built from the same review files
  and `decisions.json`. Only worth building if reviewing in the
  conversation turns out to be too painful for long papers.
- **Locating items in a PDF**: the measurement located items with SyncTeX,
  which a user's PDF doesn't have. How the runner maps an extracted item
  to its regions (matching its prose against the text layer) is untested,
  and SyncTeX itself mislocated claims about single tree nodes.
