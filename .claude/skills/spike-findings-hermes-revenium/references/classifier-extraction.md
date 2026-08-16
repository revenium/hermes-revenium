# Classifier Extraction

How to lift the task/job classification core out of the Hermes plugin into a reusable library
without changing Hermes' behavior — and how to prove you didn't.

## Requirements

From the `portable-task-classifier` idea in `.planning/spikes/MANIFEST.md`:

- Extraction must be **behavior-preserving for Hermes**, not a rewrite. The 324-test suite is
  the bar, run against the real plugin file.
- The library imports **stdlib only** — no Hermes, no `agent.auxiliary_client`, no provider SDK.
  Hosts inject the model client.
- The log channel is part of the host contract, not an implementation detail.
  `tests/test_phase28_classifier_reject_log.py` pins the `revenium_classifier` logger and the
  lazy-`%r` rendering (T-28-07). Hosts inject their logger.
- Exactly four injection points: model client, taxonomy store, logger, host name.
- Any future extraction must be validated by grafting the **real** plugin file and running the
  full suite — 5 of 7 seams are invisible to an in-process `sys.path` graft.

## How to Build It

### 1. Know what is actually portable — measure, don't estimate

`sources/001-extraction-seam/analyze_split.py` classifies every top-level function by AST
according to what it touches. Measured on `classifier.py` (1166 lines):

```
PURE       7 fns    209 lines   20.3%
LLM        2 fns     73 lines    7.1%
HOST      18 fns    748 lines   72.6%
portable: 282 lines (27.4%)  —  ~251 lines / ~24% once you discount a sync
                                wrapper that only delegates into HOST code
```

Portable: prompt construction, `LABEL_RE`/blocklist validation, job-dict normalization, job-array
parsing, `_muid`, and the two LLM-invoking orchestrators.

Not portable (and don't try): session-DB transcript reads, `_walk_to_root_session`, multiplex
profile path resolution (`_paths_for_session`), atomic marker writes, dedupe gates
(`_session_already_classified`, `_recent_marker_pair_exists`), `_guardrail_halted`,
`run_classification_async`.

### 2. Package shape

```
revenium_classify/
  labels.py     # LABEL_RE, TRIVIAL_BLOCKLIST, validate_label, validate_job, parse_job_array
  prompts.py    # build_classification_prompt, build_job_inference_prompt, system prompts
  taxonomy.py   # TaxonomyStore protocol + FileTaxonomy + InMemoryTaxonomy
  engine.py     # Classifier — takes injected llm/taxonomy/host
```

Complete working source in `sources/001-extraction-seam/revenium_classify/`.

### 3. The four injection points

```python
clf = Classifier(
    llm=call_llm,          # callable(messages=, temperature=, max_tokens=, timeout=)
    taxonomy=store,        # .labels() -> list[str],  .record(label) -> None
    host="Hermes",         # appears verbatim in all three prompts
)
# and, for job validation specifically:
validate_job(job, logger=plugin_logger)   # the CHANNEL is contract, see What to Avoid
```

The client contract is OpenAI-shaped: it is called with keyword args and its result is read as
`response.choices[0].message.content`, falling back to `response["choices"][0]["message"]["content"]`.
A host whose client differs writes a ~25-line shim — see
`sources/002-host-fit/clients.py`.

### 4. Wire the plugin to delegate

Append a graft epilogue rebinding the pure names (exact working text in
`sources/001-extraction-seam/graft_test.py`, constant `GRAFT_EPILOGUE`):

```python
import revenium_classify as _lib

LABEL_RE = _lib.LABEL_RE
TRIVIAL_BLOCKLIST = _lib.TRIVIAL_BLOCKLIST

def _validate_label(label): return _lib.validate_label(label)
def _parse_job_array(raw):  return _lib.parse_job_array(raw)
def _validate_job(job):     return _lib.validate_job(job, logger=logger)  # logger= is load-bearing
def _build_classification_prompt(u, a, l): return _lib.build_classification_prompt(u, a, l)
def _build_job_inference_prompt(t, l):     return _lib.build_job_inference_prompt(t, l)
def _read_taxonomy_labels(paths=None):
    return _lib.FileTaxonomy((paths or _module_paths()).taxonomy_file).labels()
def _persist_label_to_taxonomy(label, paths=None):
    return _lib.FileTaxonomy((paths or _module_paths()).taxonomy_file).record(label)
```

Module-global rebinding works because the plugin's internal callers resolve these names at call
time.

### 5. Prove it — three layers, in this order

1. **Purity** (`verify_purity.py`): no non-stdlib imports, no host identifiers in
   docstring-stripped code, classifies end-to-end with no filesystem and no session DB.
2. **Differential** (`differential_test.py`): same inputs through both implementations, compared
   with `==`. 4697 comparisons including 4000 fuzzed labels and 600 fuzzed job payloads →
   **0 mismatches**. Pin randomness on both sides (`validate_job(entropy=...)` vs monkeypatching
   `classifier.secrets`).
3. **In-place graft + full suite** (`in_place_graft.py`): patch the *real* file, run all 324
   tests, restore in a `finally` and verify by sha256 + `git status`. **Result: 324/324 OK.**

Then mutation-test every seam (`in_place_graft.py --mutate=<seam>`); each must turn the suite
red. All 7 died:

| Seam | 15-test subset | Full 324-test suite |
|------|----------------|---------------------|
| `validate_label` | KILLED (3) | — |
| `classification_prompt` | KILLED (1) | — |
| `job_prompt` | survived | KILLED (1) |
| `taxonomy_labels` | survived | KILLED (1) |
| `persist_label` | survived | KILLED (1) |
| `parse_job_array` | survived | KILLED (7) |
| `validate_job` | survived | KILLED (11) |

## What to Avoid

- **Do not treat return-value equivalence as behavioral equivalence.** The differential passed
  clean while the real suite failed two tests, because
  `tests/test_phase28_classifier_reject_log.py` asserts the job-type rejection lands on the
  `revenium_classifier` logger with lazy `%r` (a log-forging defense). Log identity is API.
- **Do not validate with a `sys.path` graft alone.** Five of seven seams are guarded only by
  tests that execute the plugin from its real path via bash/subprocess. An in-process graft
  reports green while those seams are unprotected.
- **Do not trust a green mutation sweep without checking the harness.** The first sweep here
  reported all five mutants surviving; the cause was the harness failing to replicate
  `sys.path.append(PLUGIN_DIR)`, so the repo's `_setup_plugin_env` inserted the real plugin
  ahead of the mutant. A green mutation result is a claim about your harness first.
- **Do not run an in-place graft in a shared checkout without a lock.** The graft window
  (~3 min per full-suite run) makes every other reader of the tree see a patched file. It
  silently contaminated one measurement in this very session (an AST analysis that parsed a
  grafted file — duplicate function rows were the tell) and can give a concurrent session
  phantom test failures.
- **Do not "unify" the two `--transaction-id` shapes.** Marker-split path uses
  `${sid}-${total_tokens}-${muid}`; markerless uses `${sid}-${total_tokens}`. Both are pinned by
  golden fixtures in `tests/fixtures/compat/`.
- **Do not share code between `classifier.py` and the bash sidecars.** The duplication is
  deliberate; the plugin must stay importable without the skill's shell environment.

## Constraints

- Stdlib only. The repo has no `package.json`, `requirements.txt`, or `pyproject.toml`, and
  `test_repository.py` polices what ships.
- The plugin's `run_classification_async` must never raise — every error path is caught and
  logged with `logger.warning`. Extraction must preserve that.
- `agent.auxiliary_client.call_llm` is imported lazily behind `try/except ImportError` so the
  module stays importable where Hermes' venv is absent. Keep that.
- Per-session path resolution (`_paths_for_session`, multiplex `agent:<profile>:…` namespace)
  stays host-side and must keep failing open to module paths.

## Origin

Synthesized from spikes: 001 (extraction-seam, VALIDATED), 002 (host-fit, VALIDATED)
Source files: `sources/001-extraction-seam/`, `sources/002-host-fit/`
