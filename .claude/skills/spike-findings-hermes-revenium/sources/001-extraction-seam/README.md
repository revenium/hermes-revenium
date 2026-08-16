---
spike: 001
idea: portable-task-classifier
name: extraction-seam
type: standard
validates: "Given classifier.py, when the pure classification core is split from Hermes I/O behind injected LLM/taxonomy/logger protocols, then the Hermes plugin still passes its full 324-test suite through the library"
verdict: VALIDATED
related: [2026-08-13-plugin-interface-expansion]
tags: [refactor, python, library, extraction]
---

# Spike 001: Extraction Seam

## What This Validates

**Given** `skills/revenium/plugins/revenium-classifier/classifier.py` (1166 lines, welded to
Hermes' session DB, marker files, profile layout, and auxiliary LLM client),
**when** the pure classification core is extracted into a stdlib-only package whose host
dependencies are injected (model client, taxonomy store, logger, host name),
**then** the Hermes plugin delegating to that package still passes the project's full
324-test suite, unmodified.

The bar is deliberately "behavior-preserving refactor", not "a library that works". If
extraction requires changing Hermes' observable behavior, it stops being a refactor and
becomes a rewrite of a load-bearing production component — a different, much larger ask.

## Research

No external library research was warranted: the question is about *this* codebase's internal
structure, not about a dependency choice. Prior art consulted instead:

- `.planning/spikes/2026-08-13-plugin-interface-expansion/FINDINGS.md` — establishes what the
  Hermes host can hand a classifier (`post_api_request` is a complete per-call metering event;
  prompt sections freeze per session; auxiliary usage is unmetered).
- `CLAUDE.md` "Classification pipeline (markers)" and the two `run_classification_async`
  invariants (never raises; per-session path resolution).
- `tests/test_repository.py` and `tests/test_phase28_classifier_reject_log.py` — the actual
  behavioral contract.

**Approach comparison:**

| Approach | Evidence it produces | Cost | Verdict |
|----------|---------------------|------|---------|
| Read the code and reason about the seam | An opinion | Minutes | Insufficient — the seam's cost is in the details |
| Extract + differential-test the pure functions | Return-value equivalence on inputs *I* chose | ~1h | Necessary, not sufficient (see Trail step 4) |
| Extract + graft into plugin via `sys.path`, run repo's classifier tests | Equivalence on inputs *maintainers* chose | +30m | Misleading alone — most plugin coverage runs the file from disk |
| Extract + graft the real file in place, run all 324 tests + mutation-check the seams | Whether the refactor actually survives, and which seams are covered at all | +1h | **Chosen** |

## How to Run

```bash
cd .planning/spikes/001-extraction-seam

python3 verify_purity.py         # library imports stdlib only, no host identifiers, works with no FS/DB
python3 differential_test.py     # 4697 comparisons, library vs original, must be 0 mismatches
python3 analyze_split.py         # AST measurement of portable vs host-bound
python3 graft_test.py            # 15 classifier tests via sys.path graft
python3 in_place_graft.py        # full 324-test suite against the real file, grafted
python3 in_place_graft.py --mutate=validate_job   # sabotage one seam; suite must go red
```

`in_place_graft.py` refuses to run unless `skills/` is git-clean, restores the original file in
a `finally` block, and verifies the restore by sha256 plus `git status`.

## What to Expect

- `verify_purity.py` → `purity: PASS (0 problems)`
- `differential_test.py` → `4697 comparisons, 0 mismatches`
- `in_place_graft.py` → `Ran 324 tests ... OK`, then `restore verified: True`
- Each `--mutate=` run → the suite goes red, *or* the mutant survives, which is itself the
  finding (that seam has no test coverage).

## Investigation Trail

**1. Measured the seam instead of guessing at it.** `analyze_split.py` classifies every
top-level function by AST according to what it touches (session DB / marker files / profile
paths / halt state → HOST; taxonomy files → TAXONOMY; `call_llm` → LLM; nothing → PURE).

**2. Built the library, extracting the PURE + LLM surface verbatim.** `revenium_classify/`
is four modules — `labels.py` (grammar, validation, job normalization), `prompts.py`
(prompt construction), `taxonomy.py` (a two-method `TaxonomyStore` protocol with file-backed
and in-memory implementations), `engine.py` (the orchestration that takes an injected client).

**3. First surprise: the prompts are host-specific text, not generic logic.** All three
prompt strings hardcode "Hermes" ("You are classifying a **Hermes** session turn…"). A shared
library therefore cannot have one prompt — it needs a `host` parameter. Defaulting it to
`"Hermes"` keeps extraction byte-identical for the existing plugin, but it means **every
non-Hermes host runs a different prompt and can therefore produce different labels.** That is
not a code problem; it is the taxonomy-governance problem, and it hands spike 003 its premise.

**4. Differential test passed — and was insufficient.** 4697 comparisons across the label
grammar (including 4000 fuzzed strings), the job-array parser (including fence variants and
600 fuzzed strings), job validation (including injection-shaped inputs), both prompts, and
taxonomy ordering/mint-back: 0 mismatches. Then the in-place run against the real suite failed
2 tests. The differential compared **return values only**. It could not see that
`tests/test_phase28_classifier_reject_log.py` asserts the job-type rejection lands on the
**`revenium_classifier` logger specifically**, with the value rendered through lazy `%r` so a
newline in raw LLM output cannot forge a second log record (T-28-07, a log-injection defense).
My library logged to its own `revenium_classify` channel — return-identical, contract-breaking.

**Extraction constraint recorded:** the log channel is part of the host contract. The library
takes an injected `logger`. Any future extraction of this code must treat observability
identity as API, not as an implementation detail.

**5. First mutation attempt produced a false result — and the bug was mine.** All five mutants
"survived", which would have meant the tests never touched the seam. The harness was at fault:
it never replicated `main()`'s `sys.path.append(PLUGIN_DIR)`, so the repo's own
`_setup_plugin_env` inserted the real plugin ahead of the mutant and the sabotage was never
loaded. Rewritten to mutate in clean subprocesses. **A green mutation result is a claim about
your harness before it is a claim about your code.**

**6. Second surprise: the `sys.path` graft can only reach part of the suite.** Much of the
plugin's coverage executes the file from its real path via bash/subprocess, which no
`sys.path` trick can intercept. Hence `in_place_graft.py`, which patches the real file with a
verified restore. This is the only configuration in which "324 tests pass" means anything.

**7. Mutation-tested the seams against the full suite** to find out which parts of the
extracted surface the project can actually detect a regression in.

## Results

**Verdict: VALIDATED — but the portable core is about a quarter of the module, and the seam
costs four injection points.**

### The extraction works, and the project's own tests say so

| Evidence | Result |
|----------|--------|
| `verify_purity.py` | PASS — no non-stdlib imports, no host identifiers in executable code, classifies with no filesystem and no session DB |
| `differential_test.py` | 4697 comparisons, **0 mismatches** vs the original |
| `in_place_graft.py` (real file, grafted) | **324 tests, OK**; restore verified by sha256 + `git status` |

### Mutation sweep — every seam is covered by real tests

Each mutant sabotages one grafted function; the full suite must go red. All seven died:

| Seam | 15-test subset | Full 324-test suite |
|------|----------------|---------------------|
| `validate_label` | KILLED (3) | — |
| `classification_prompt` | KILLED (1) | — |
| `job_prompt` | survived | **KILLED (1)** |
| `taxonomy_labels` | survived | **KILLED (1)** |
| `persist_label` | survived | **KILLED (1)** |
| `parse_job_array` | survived | **KILLED (7)** |
| `validate_job` | survived | **KILLED (11)** |

The subset/full-suite gap is the reusable lesson: five of seven seams are guarded *only* by
tests that execute the plugin from its real path. Any future extraction validated with an
in-process graft alone would have shipped with five unguarded seams and a green board.

### The measured split

`analyze_split.py`, run against a clean tree:

```
PURE       7 fns    209 lines   20.3%
LLM        2 fns     73 lines    7.1%
HOST      18 fns    748 lines   72.6%
portable: 282 lines (27.4%)   host-bound: 748 lines (72.6%)
```

Honest caveat: `run_classification` (31 lines) is counted PURE because it touches only
`asyncio`, but it wraps a HOST function. True portable core is ~251 lines, **~24%**.

So three quarters of `classifier.py` is Hermes-shaped by construction — session-DB transcript
reads, root-delegator walk, multiplex profile path resolution, atomic marker writes, dedupe
gates, halt check. None of that transfers to a LiteLLM guardrail or Claude Code, because those
hosts have different session models, different storage, and different identity.

### What a library would actually be

Four injection points, all discovered rather than designed up front:

1. **model client** — `call_llm`-shaped callable (Hermes' auxiliary client, or the host's own)
2. **taxonomy store** — two methods, `labels()` / `record()`; file-backed or in-memory (or, per
   spike 003, remote)
3. **logger** — because `tests/test_phase28_classifier_reject_log.py` pins the channel *and*
   the lazy-`%r` rendering as a log-injection defense
4. **host name** — because the prompts hardcode "Hermes"

### Answering the actual question

Extracting is *feasible* and behavior-preserving. Whether it is *worthwhile* rests on what the
other three quarters cost each new host — spike 002 — and on whether three hosts minting labels
against three vocabularies produces one analytics story or three — spike 003. The library is
real but small; the interesting risk has moved downstream, which is exactly what a spike is
for.

### Surprises worth carrying forward

- **Return-value equivalence is not behavioral equivalence.** The log channel was contract.
- **A green mutation sweep is a claim about your harness first.** My first sweep was a false
  negative caused by `sys.path` ordering in my own script.
- **In-place grafting races everything else that reads the tree.** My first `analyze_split.py`
  run silently measured a grafted file (duplicate function rows were the tell). Any repeat of
  this technique should hold a lock or run in a worktree.
