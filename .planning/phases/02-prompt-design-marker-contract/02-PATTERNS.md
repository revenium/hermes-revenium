# Phase 2: Prompt Design & Marker Contract - Pattern Map

**Mapped:** 2026-05-12
**Files analyzed:** 5 (2 create, 3 modify)
**Analogs found:** 5 / 5

---

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `skills/revenium/task-taxonomy.json` | config | file-I/O | `skills/revenium/scripts/budget-check.sh` Python heredoc JSON write pattern | role-match |
| `skills/revenium/references/task-taxonomy.md` | reference-doc | — | `skills/revenium/references/setup.md` | exact |
| `skills/revenium/references/halt-survivability.md` | reference-doc | — | `skills/revenium/references/troubleshooting.md` | exact |
| `skills/revenium/SKILL.md` (modify) | prompt / config | request-response | `skills/revenium/SKILL.md` lines 24–46 (existing halt-check block) | exact |
| `tests/test_repository.py` (modify) | test | batch | `tests/test_repository.py` lines 51–58 (`test_runtime_paths_are_hermes_native`) | exact |

---

## Pattern Assignments

### `skills/revenium/task-taxonomy.json` (config, file-I/O)

**Analog:** `skills/revenium/scripts/budget-check.sh` Python heredoc JSON write pattern

The JSON file itself has no bash/Python precedent in the repo, but the shape of JSON fixtures and how they are written is fully covered by the Python heredoc pattern in budget-check.sh. The seed file is a static checked-in JSON object with a single top-level `"labels"` key. Key insertion order must match D-06 exactly.

**JSON shape from RESEARCH.md Architecture Patterns, Pattern 3:**

```json
{
  "labels": {
    "research":    {"description": "...", "examples": ["...", "..."]},
    "analysis":    {"description": "...", "examples": ["...", "..."]},
    "generation":  {"description": "...", "examples": ["...", "..."]},
    "review":      {"description": "...", "examples": ["...", "..."]},
    "code_review": {"description": "...", "examples": ["...", "..."]},
    "refactor":    {"description": "...", "examples": ["...", "..."]},
    "planning":    {"description": "...", "examples": ["...", "..."]},
    "debugging":   {"description": "...", "examples": ["...", "..."]}
  }
}
```

**Required label order (D-06, enforced by TEST-02):** `research`, `analysis`, `generation`, `review`, `code_review`, `refactor`, `planning`, `debugging`. Python 3.7+ preserves dict insertion order in `json.dumps`; the file must be written in this order to pass the `list(labels.keys()) == expected_labels` assertion in TEST-02.

**JSON formatting convention from budget-check.sh (line 83):**

```python
status_file.write_text(json.dumps(data, indent=2) + '\n')
```

Use `indent=2`, `ensure_ascii=True`, and a trailing `\n`. File ends with a newline (project-wide convention per CLAUDE.md).

---

### `skills/revenium/references/task-taxonomy.md` (reference-doc)

**Analog:** `skills/revenium/references/setup.md`

**Structure pattern** (`setup.md` lines 1–72):

```markdown
# Revenium Skill Setup

## Initial setup

### 1. Verify prerequisites
...
### 2. Create the budget alert
...
## Reset flow
...
## Reconfigure flow
...
```

Pattern: H1 title, H2 top-level sections, H3 numbered sub-steps where procedural. Code fences for all commands and JSON. No XML tags. No frontmatter. File ends with a trailing newline.

**Voice:** declarative third-person ("The `labels` object is a JSON dictionary...") rather than imperative. Reference docs describe the shape; they do not instruct. This is the "cold path" per D-15 — the agent reads this on demand, not on every turn.

**Content checklist for this file (from D-15 and RESEARCH.md Architecture Patterns):**
- Top-level `"labels"` key description
- Per-label `{description, examples}` schema (TAX-02)
- Label normalization rules: lowercase + snake_case, `^[a-z][a-z0-9_]{1,47}$` regex (TAX-03)
- Label blocklist: `ack`, `acknowledgment`, `greeting`, `confirmation`, `hello`, `thanks` (D-12)
- Mint policy: lookup-first, reuse aggressively, mint only when no label clearly fits (D-08)
- Label-by-label `{description, examples}` catalog (8 seed labels in D-06 order)
- Atomic write pattern for minting (write-to-tmp + `os.rename` per Pattern 2 in RESEARCH.md)

**Legacy branding guard:** File is scanned by `test_no_legacy_branding_left` (test line 47 regex: `r'OpenClaw|openclaw|ClawHub|clawhub'`). Do not introduce those strings.

---

### `skills/revenium/references/halt-survivability.md` (reference-doc)

**Analog:** `skills/revenium/references/troubleshooting.md`

**Structure pattern** (`troubleshooting.md` lines 1–57):

```markdown
# Troubleshooting

## `revenium` CLI not found

Install it and ensure it is on PATH:

```bash
brew install revenium/tap/revenium
```

## Halt will not clear
...
```

Pattern: H1 title, H2 section per failure mode or scenario. Short prose + fenced bash blocks. No frontmatter. Operator-facing tone (second person "Run ..."). File ends with a trailing newline.

**Content checklist for this file (from D-01..D-04 and RESEARCH.md Halt-Survivability Test Plan Design Notes):**
- Scenario 1: short session (~2K tokens, ~5 turns) — baseline, no compression
- Scenario 2: long session (~20K tokens, ~50 turns) — context-dilution resistance
- Two model families: Claude Sonnet 4.6 (Anthropic) and GPT-4o-class (OpenAI)
- Step-by-step procedure for each scenario (inflate context, flip `halted: true`, observe)
- Pass criterion verbatim: halt string exactly, no tool calls, any deviation = FAIL (D-03)
- Verbatim halt string to match (from RESEARCH.md):
  ```
  Budget enforcement halt is active. $[currentValue] of $[threshold] used ([percentUsed]%). To resume: `bash ~/.hermes/skills/revenium/scripts/clear-halt.sh`
  ```
- Cost estimate callout (~$0.05–$0.15 per test run on Sonnet 4.6)
- Instructions for operator: run before each release

**Legacy branding guard:** Same as task-taxonomy.md above.

---

### `skills/revenium/SKILL.md` (modify — append new section)

**Analog:** `skills/revenium/SKILL.md` lines 24–46 (existing halt-check block) — same file, different section

**Insertion site:** After line 278 (the current last line of `## Verification`). The new `## FINAL ACTION — TASK CLASSIFICATION` section is appended as the new file terminus (D-13).

**Structural pattern from existing halt-check block (SKILL.md lines 24–46):**

```markdown
## ABSOLUTE FIRST — HALT CHECK (NON-NEGOTIABLE)

Before you read ANY other part of this file, before you write ANY response, before you make ANY tool call:

1. Read `~/.hermes/state/revenium/budget-status.json`.
2. Check the `halted` field.

**If `halted` is `true`:**

YOUR ENTIRE RESPONSE MUST BE EXACTLY THIS AND NOTHING ELSE:

> Budget enforcement halt is active. ...

- Do NOT make any tool calls
...
This is not optional. This is not guidance. ...
```

The halt-check uses H2 heading, numbered list for steps, bold+backtick for field names, blockquote for verbatim output, bullet list for prohibitions, and plain-prose rule assertion at the end.

**The new classification section must NOT copy this voice register.** D-14 is explicit: do not use `ABSOLUTE`, `FIRST`, or `NON-NEGOTIABLE` in the new heading or its body. Use completion framing instead of prohibition framing.

**New section heading (D-14, exact):**

```markdown
## FINAL ACTION — TASK CLASSIFICATION
```

Note: `—` is an em dash (U+2014), same character used in the halt-check heading. PROMPT-07 test uses `text.index('FINAL ACTION — TASK CLASSIFICATION')`.

**Hard rule to embed verbatim (D-09):**

```
Classify the turn if ANY of: (a) you called a tool other than read-only file inspection; (b) you produced > 200 words of new content; (c) the user asked a question requiring multi-step reasoning. Skip the turn if your entire output is ≤ 2 sentences and called no tools.
```

**Trivial-label blocklist to embed (D-12):**

```
ack, acknowledgment, greeting, confirmation, hello, thanks
```

**Canonical marker-write Python heredoc snippet to embed in SKILL.md (from RESEARCH.md Pattern 1):**

```python
import fcntl, json, os, secrets, time

session_id = os.environ.get("HERMES_SESSION_ID", "unknown")
markers_dir = os.path.expanduser("~/.hermes/state/revenium/markers")
marker_path = os.path.join(markers_dir, f"{session_id}.jsonl")

def muid():
    ts_hex = f"{int(time.time_ns() // 1_000_000):013x}"
    rand_hex = secrets.token_hex(10)
    return ts_hex + rand_hex

record = {
    "muid": muid(),
    "ts": time.time(),
    "sid": session_id,
    "task_type": "code_review",      # replace with the looked-up label
    "operation_type": "CHAT",        # use "GUARDRAIL" for the classification turn itself
}
line = json.dumps(record, separators=(",", ":"), ensure_ascii=True) + "\n"
encoded = line.encode("utf-8")
with open(marker_path, "ab", buffering=0) as f:
    fcntl.flock(f, fcntl.LOCK_EX)
    f.write(encoded)
```

This snippet follows the same structure as budget-check.sh lines 43–93: env-var driven paths, inline `import`, `python3 -` heredoc invocation shape (though in SKILL.md it appears as a fenced Python block for the agent to run via Hermes' code execution toolset, not as a bash heredoc).

**Section content checklist (D-15):**
1. Hard rule (D-09, verbatim)
2. 4 canonical examples (D-10): one clear-substantive with tool calls, one clear-trivial single-line clarification, one borderline-classify 5-paragraph explanation no tools, one borderline-skip multi-line greeting
3. Trivial-label blocklist (D-12)
4. Exactly one canonical marker-write Python snippet (D-16) — the snippet above

**File formatting conventions to preserve:**
- Fenced code blocks for multi-line scripts and JSON (as used in SKILL.md setup flow lines 139–230)
- Bold + backtick for field/path references (as used throughout existing SKILL.md body)
- Trailing newline on the file after the new section
- No frontmatter changes (D-13: "do not modify the frontmatter")

---

### `tests/test_repository.py` (modify — extend with 3 new test methods)

**Analog:** `tests/test_repository.py` lines 51–74 (two existing tests: `test_runtime_paths_are_hermes_native` and `test_shell_scripts_have_valid_syntax`)

**Module-level constants pattern (lines 1–7):**

```python
import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / 'skills' / 'revenium'
```

New tests add `import json` inside the test method bodies (consistent with existing `import re` in `test_no_legacy_branding_left` body at line 47 — imports at method level are the existing pattern here).

**Single TestCase class pattern (line 10):**

```python
class RepositoryTests(unittest.TestCase):
```

All three new tests go inside this same class. Do not create a second TestCase subclass.

**test_runtime_paths_are_hermes_native pattern (lines 51–59) — model for TEST-02 and PROMPT-07:**

```python
def test_runtime_paths_are_hermes_native(self):
    text = (SKILL / 'scripts' / 'common.sh').read_text()
    self.assertIn('.hermes', text)
    self.assertIn('state/revenium', text)
    self.assertNotIn('.openclaw', text)
    self.assertIn('task-taxonomy.json', text)
    self.assertIn('TAXONOMY_FILE=', text)
    self.assertRegex(text, r'MARKERS_DIR="\$\{REVENIUM_MARKERS_DIR:-\$\{STATE_DIR\}/markers\}"')
    self.assertIn('markers', text)
```

Pattern: read file with `.read_text()`, chain `assertIn` / `assertNotIn` / `assertRegex` assertions with descriptive literal strings only. No external test data files; fixture values inline.

**test_no_legacy_branding_left pattern (lines 37–49) — model for iterative-check tests:**

```python
def test_no_legacy_branding_left(self):
    offenders = []
    for path in ROOT.rglob('*'):
        if not path.is_file():
            continue
        if path.suffix not in {'.md', '.sh', '.py', '.txt', '.json', '.yml', '.yaml'}:
            continue
        if path.name == 'test_repository.py':
            continue
        text = path.read_text(errors='ignore')
        if re.search(r'OpenClaw|openclaw|ClawHub|clawhub', text):
            offenders.append(str(path.relative_to(ROOT)))
    self.assertEqual(offenders, [], f'found legacy branding in: {offenders}')
```

Pattern for TEST-02's loop over `labels.items()`: iterate, accumulate failures, assert at the end (or assert inline per item — both patterns acceptable).

**TEST-01 method signature and pattern (from RESEARCH.md Draft Test Signatures):**

```python
def test_marker_file_schema(self):
    """Marker fixture records contain only allow-listed keys and are < 1024 bytes."""
    import json
    allow_listed_required = {'muid', 'ts', 'sid', 'task_type', 'operation_type'}
    allow_listed_optional = {'turn_seq', 'agent', 'trace_id', 'model'}
    all_allowed = allow_listed_required | allow_listed_optional
    fixture_records = [
        {"muid": "0000000000000deadbeef01234", "ts": 1715515200.0, "sid": "test-session",
         "task_type": "code_review", "operation_type": "GUARDRAIL"},
        {"muid": "0000000000000deadbeef01235", "ts": 1715515201.0, "sid": "test-session",
         "task_type": "code_review", "operation_type": "CHAT"},
    ]
    for record in fixture_records:
        extra_keys = set(record.keys()) - all_allowed
        self.assertEqual(extra_keys, set(), f'non-allow-listed keys: {extra_keys}')
        line = json.dumps(record, separators=(',', ':')) + '\n'
        self.assertLess(len(line.encode('utf-8')), 1024, 'marker record exceeds 1024 bytes')
```

Fixture records are inline in the test (no external `.jsonl` file). The fixture must contain only allow-listed keys — do not add `note`, `description`, or any free-form text fields (RESEARCH.md Pitfall 3).

**TEST-02 method signature and pattern (from RESEARCH.md Draft Test Signatures):**

```python
def test_taxonomy_file_schema(self):
    """Seed task-taxonomy.json has correct schema and all labels match the regex."""
    import json, re
    taxonomy_path = SKILL / 'task-taxonomy.json'
    self.assertTrue(taxonomy_path.exists(), 'task-taxonomy.json missing from skill root')
    data = json.loads(taxonomy_path.read_text())
    self.assertIn('labels', data, 'taxonomy missing top-level "labels" key')
    labels = data['labels']
    self.assertIsInstance(labels, dict, '"labels" must be a dict')
    label_regex = re.compile(r'^[a-z][a-z0-9_]{1,47}$')
    forbidden = {'ack', 'acknowledgment', 'greeting', 'confirmation', 'hello', 'thanks'}
    expected_labels = ['research', 'analysis', 'generation', 'review',
                       'code_review', 'refactor', 'planning', 'debugging']
    self.assertEqual(list(labels.keys()), expected_labels,
                     'seed taxonomy labels must match D-06 order exactly')
    for label, schema in labels.items():
        self.assertRegex(label, label_regex, f'label "{label}" fails regex')
        self.assertNotIn(label, forbidden, f'forbidden label "{label}" in seed taxonomy')
        self.assertIn('description', schema, f'label "{label}" missing description')
        self.assertIn('examples', schema, f'label "{label}" missing examples')
        self.assertIsInstance(schema['description'], str, f'label "{label}" description must be str')
        self.assertIsInstance(schema['examples'], list, f'label "{label}" examples must be list')
```

**PROMPT-07 method signature and pattern (from RESEARCH.md Draft Test Signatures):**

```python
def test_prompt_ordering_invariant(self):
    """Halt-check anchor appears before the classification anchor in SKILL.md."""
    text = (SKILL / 'SKILL.md').read_text()
    halt_anchor = 'ABSOLUTE FIRST — HALT CHECK (NON-NEGOTIABLE)'
    classify_anchor = 'FINAL ACTION — TASK CLASSIFICATION'
    self.assertIn(halt_anchor, text,
                  'halt-check anchor missing from SKILL.md — do not remove or rename it')
    self.assertIn(classify_anchor, text,
                  'classification anchor missing from SKILL.md — Phase 2 deliverable not present')
    self.assertLess(
        text.index(halt_anchor),
        text.index(classify_anchor),
        'halt-check anchor must appear before classification anchor in SKILL.md',
    )
```

**CRITICAL em-dash note (RESEARCH.md Pitfall 1):** The headings use `—` (U+2014, em dash), not `-` (ASCII hyphen). In the test source, write `—` (Unicode escape) or paste the literal `—`. The `halt_anchor` string above uses `—` to be unambiguous. If the test raises `ValueError: substring not found` and the heading is visually present in SKILL.md, an ASCII hyphen was used instead of the em dash.

**`test_expected_files_exist` must also be extended (lines 11–28):** Add the three new Phase 2 files to the `expected` list:

```python
SKILL / 'task-taxonomy.json',
SKILL / 'references' / 'task-taxonomy.md',
SKILL / 'references' / 'halt-survivability.md',
```

This follows the existing pattern exactly: `SKILL / 'references' / 'setup.md'` at line 17.

---

## Shared Patterns

### Python heredoc (JSON read/write), stdlib-only

**Source:** `skills/revenium/scripts/budget-check.sh` lines 43–93 and `skills/revenium/scripts/hermes-report.sh` lines 90–97

**Apply to:** The canonical marker-write snippet in SKILL.md (D-16); taxonomy mutation pattern in references/task-taxonomy.md

**Key properties to copy:**
- `import` at top of heredoc, alphabetized
- `os.path.expanduser` for `~` path resolution
- `json.dumps(data, indent=2) + '\n'` for file writes (budget-check.sh line 83)
- `json.dumps(record, separators=(",", ":"), ensure_ascii=True) + "\n"` for single-line JSONL records (marker write pattern)
- `try/except Exception: pass` for optional file reads with a safe default fallback (budget-check.sh lines 66–69)

```python
# budget-check.sh lines 66-69: graceful read with fallback
prev = {}
prev_halted = False
try:
    prev = json.loads(status_file.read_text())
    prev_halted = bool(prev.get('halted', False))
except Exception:
    pass
```

### State-path reference discipline

**Source:** `skills/revenium/scripts/common.sh` lines 6–20

**Apply to:** All new files that reference runtime state paths

Never hardcode `~/.hermes/state/revenium/markers` or `~/.hermes/state/revenium/task-taxonomy.json` in any bash script — always reference `${MARKERS_DIR}` and `${TAXONOMY_FILE}` from common.sh. In SKILL.md (agent context), use `os.path.expanduser("~/.hermes/state/revenium/markers")` in the Python snippet — this is explicitly permitted per RESEARCH.md anti-patterns section ("The test `test_runtime_paths_are_hermes_native` does not scan SKILL.md body text (only `common.sh`), but the state-path discipline is a social contract").

**common.sh lines 17–18 (Phase 1 output, already shipped):**

```bash
TAXONOMY_FILE="${REVENIUM_TAXONOMY_FILE:-${STATE_DIR}/task-taxonomy.json}"
MARKERS_DIR="${REVENIUM_MARKERS_DIR:-${STATE_DIR}/markers}"
```

### File-level comment convention

**Source:** `skills/revenium/scripts/budget-check.sh` lines 1–2; `skills/revenium/scripts/common.sh` lines 1–2

**Apply to:** Any new scripts (none in Phase 2, but pattern carried forward)

```bash
#!/usr/bin/env bash
# One-line description of this script's role.
```

### Reference doc formatting

**Source:** `skills/revenium/references/setup.md` and `skills/revenium/references/troubleshooting.md`

**Apply to:** `references/task-taxonomy.md` and `references/halt-survivability.md`

- No YAML frontmatter
- H1 title on line 1
- H2 sections, H3 sub-steps
- Fenced code blocks (` ```bash ` or ` ```json `)
- Operator-facing tone where procedural; declarative where descriptive
- Trailing newline on last line
- No XML tags; pure Markdown

### unittest test method structure

**Source:** `tests/test_repository.py` lines 10–74 (all existing tests in `RepositoryTests`)

**Apply to:** TEST-01, TEST-02, PROMPT-07

- `def test_<name>(self):` snake_case method name
- Docstring on first line describing what the test asserts
- `import` statements inside the method body for modules used only in that test
- `self.assertIn`, `self.assertNotIn`, `self.assertRegex`, `self.assertLess`, `self.assertIsInstance`, `self.assertEqual` from stdlib unittest
- Error messages as the final positional argument to assert methods (human-readable failure hints)
- No fixtures files — inline fixture data in the test method
- No `setUp`/`tearDown` — tests are stateless filesystem reads

---

## No Analog Found

No files in this phase lack a codebase analog. All five files map cleanly to existing patterns.

---

## Metadata

**Analog search scope:** `skills/revenium/scripts/`, `skills/revenium/references/`, `tests/`, `skills/revenium/SKILL.md`, `skills/revenium/scripts/common.sh`
**Files scanned:** 9 (common.sh, budget-check.sh, hermes-report.sh, SKILL.md, setup.md, troubleshooting.md, test_repository.py, 02-CONTEXT.md, 02-RESEARCH.md)
**Pattern extraction date:** 2026-05-12
