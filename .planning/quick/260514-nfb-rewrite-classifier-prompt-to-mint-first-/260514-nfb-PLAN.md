---
phase: 260514-nfb-rewrite-classifier-prompt-to-mint-first-
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - skills/revenium/plugins/revenium-classifier/classifier.py
  - tests/test_repository.py
autonomous: true
requirements:
  - PROMPT-MINT-FIRST
must_haves:
  truths:
    - "_build_classification_prompt frames the task as 'mint a specific label' first, not 'pick existing then fall back to mint'"
    - "The prompt body contains the literal anchor phrase 'Mint a SPECIFIC, DESCRIPTIVE label' so a regression test can pin the bias direction"
    - "The prompt lists concrete multi-word examples (weekly_pr_review, prod_log_triage, news_summary, sql_query_debug, release_notes_draft) to anchor granularity at 2-4 words"
    - "The prompt names the bland catch-alls (generation, analysis, review, task) on an explicit AVOID line so the LLM stops collapsing everything to 'generation'"
    - "Existing labels are offered for reuse only when they describe the SAME specific work — not 'close enough'"
    - "The regex contract ^[a-z][a-z0-9_]{1,47}$ and the TRIVIAL_BLOCKLIST forbidden tokens (ack, acknowledgment, greeting, confirmation, hello, thanks) remain present in the prompt body"
    - "Surrounding helpers (_classify_via_llm, _validate_label, _read_taxonomy_labels) are byte-unchanged"
    - "Full test suite stays green at the single commit boundary"
  artifacts:
    - path: "skills/revenium/plugins/revenium-classifier/classifier.py"
      provides: "Rewritten _build_classification_prompt function body, mint-first framing"
      contains: "Mint a SPECIFIC, DESCRIPTIVE label"
    - path: "tests/test_repository.py"
      provides: "New regression-guard test asserting the prompt contains the mint-first anchor phrase, the AVOID list, and the regex contract"
      contains: "test_revenium_classifier_prompt_mint_first_bias"
  key_links:
    - from: "skills/revenium/plugins/revenium-classifier/classifier.py::_build_classification_prompt"
      to: "skills/revenium/plugins/revenium-classifier/classifier.py::_classify_via_llm"
      via: "call site at line 250 — _classify_via_llm calls _build_classification_prompt(message, response_preview, labels)"
      pattern: "_build_classification_prompt\\("
    - from: "tests/test_repository.py::test_revenium_classifier_prompt_mint_first_bias"
      to: "skills/revenium/plugins/revenium-classifier/classifier.py::_build_classification_prompt"
      via: "direct import + call, assertions on returned string"
      pattern: "_build_classification_prompt"
---

<objective>
Rewrite the body of `_build_classification_prompt` in
`skills/revenium/plugins/revenium-classifier/classifier.py` so the LLM is biased
toward minting a specific, descriptive snake_case label instead of collapsing
every output-producing turn to the bland seed label `generation`.

Purpose: Live evidence from Mac Studio shows 12/16 markers in the last 24h
landed on `generation`, and the seed taxonomy hasn't grown in days. The
current prompt's "Pick the single best-fitting existing label by exact match.
If NONE fit, mint a new label" wording makes the LLM treat the existing
labels as a near-exhaustive lookup table, so it almost never mints. After the
D-07 fix (260514-n8e) the classifier now fires on every session, so this
prompt bias is fully exposed and is the only thing standing between us and
useful per-task-type spend attribution.

Output: One commit modifying two files — the prompt body rewrite plus a new
regression-guard unit test that pins the mint-first framing, the concrete
examples list, the AVOID catch-all list, the regex contract, and the
blocklist. The two existing prompt-adjacent tests
(`test_revenium_classifier_llm_label`, `test_revenium_classifier_llm_blocklist_fallthrough`)
must continue to pass unchanged because they only mock `call_llm`'s return
value — they do not assert on the prompt text.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@CLAUDE.md
@skills/revenium/plugins/revenium-classifier/classifier.py
@tests/test_repository.py
@.planning/quick/260514-n8e-remove-d-07-trivial-skip-from-classifier/260514-n8e-SUMMARY.md

<interfaces>
<!-- Key facts the executor needs without re-exploring the codebase. -->

Current function signature and call site (from classifier.py):

```
def _build_classification_prompt(user_msg: str, assistant_resp: str, labels: list) -> str:
    ...

# Called from _classify_via_llm at line ~250:
prompt = _build_classification_prompt(
    context.get("message", "") or "",
    response_preview,
    labels,
)
```

The function MUST keep this exact signature and return type. Only the body
changes.

The two existing prompt-adjacent tests at tests/test_repository.py:1235 and
:1287 mock `handler.call_llm` and assert on resulting marker contents — they
do NOT inspect the prompt text and will not regress when the prompt body
changes.

The legacy-branding guard (`test_no_legacy_branding_left`) greps every
.py/.md/.sh/.txt/.json/.yml/.yaml for forbidden product names. The new
example labels (`weekly_pr_review`, `prod_log_triage`, `news_summary`,
`sql_query_debug`, `release_notes_draft`) and the AVOID-list nouns
(`generation`, `analysis`, `review`, `task`) are generic English and safe.

`TRIVIAL_BLOCKLIST` and `LABEL_RE` at the top of classifier.py are
byte-unchanged by this work — the prompt body just continues to reference
them. From classifier.py (do not modify):

```
LABEL_RE = re.compile(r"^[a-z][a-z0-9_]{1,47}$")
TRIVIAL_BLOCKLIST = {"ack", "acknowledgment", "greeting", "confirmation", "hello", "thanks"}
```
</interfaces>
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: Rewrite _build_classification_prompt body to mint-first + add regression-guard test</name>
  <files>skills/revenium/plugins/revenium-classifier/classifier.py, tests/test_repository.py</files>
  <behavior>
    - The new prompt body, when concatenated, MUST contain the literal substring "Mint a SPECIFIC, DESCRIPTIVE label" (verbatim, case-sensitive).
    - The new prompt body MUST contain each of these concrete example labels exactly once: `weekly_pr_review`, `prod_log_triage`, `news_summary`, `sql_query_debug`, `release_notes_draft`.
    - The new prompt body MUST contain the explicit AVOID line naming the four bland catch-alls: `generation`, `analysis`, `review`, `task`.
    - The new prompt body MUST retain the regex contract literal `^[a-z][a-z0-9_]{1,47}$` and the forbidden-labels line listing `ack, acknowledgment, greeting, confirmation, hello, thanks` (preserving the D-09 enforcement that `_validate_label` already does post-hoc).
    - The new prompt body MUST retain the labels-block cap (≤1024 chars + truncation suffix) and the user/assistant preview cap (≤800 chars each), so the whole prompt still fits ~2 KB per D-06.
    - The new prompt body MUST frame reuse as a narrow exception ("only if they describe the SAME specific work"), not a default action.
    - `_build_classification_prompt`'s call signature `(user_msg: str, assistant_resp: str, labels: list) -> str` is byte-unchanged.
    - Helpers `_classify_via_llm`, `_validate_label`, `_read_taxonomy_labels`, `TRIVIAL_BLOCKLIST`, and `LABEL_RE` are byte-unchanged.
    - New test `test_revenium_classifier_prompt_mint_first_bias` in tests/test_repository.py imports the classifier module, calls `_build_classification_prompt("u", "a", ["generation", "code_review"])`, and asserts each of the contract items above appears in the returned string. It also asserts the function still returns a string ≤ 4096 chars to keep the prompt-size invariant.
    - The two existing tests `test_revenium_classifier_llm_label` (line 1235) and `test_revenium_classifier_llm_blocklist_fallthrough` (line 1287) pass unchanged with no edits required, because they mock `call_llm`'s return value and never inspect the prompt argument.
    - Full suite `python3 -m unittest discover -s tests -p 'test_*.py' -v` is green at the end of this single commit.
  </behavior>
  <action>
    Replace the body of `_build_classification_prompt` in `skills/revenium/plugins/revenium-classifier/classifier.py` (currently lines 219-239) with a mint-first prompt that incorporates all four behavior changes spelled out in the project description: (1) frame the task as "Mint a SPECIFIC, DESCRIPTIVE label" first, not "pick existing then fall back to mint"; (2) include the concrete example list `weekly_pr_review`, `prod_log_triage`, `news_summary`, `sql_query_debug`, `release_notes_draft` to anchor granularity at 2-4 words joined by underscores; (3) add an explicit "AVOID bland catch-all labels like generation, analysis, review, task when a more specific label fits" line; (4) reframe the existing-labels block as "you MAY reuse if (and only if) they describe the SAME specific work" rather than "Pick the single best-fitting existing label". Preserve the labels_block cap (≤1024 chars), the user/asst preview caps (≤800 chars each), the regex contract `^[a-z][a-z0-9_]{1,47}$`, and the forbidden-labels line for `ack, acknowledgment, greeting, confirmation, hello, thanks`. Do not touch the function signature, the docstring's reference to D-06+D-09 (update it to mention the mint-first bias), or any other function in the file. Use the target prompt shape from the task description as the reference — minor wording polish is fine but all four key changes must land. Then add a new test method `test_revenium_classifier_prompt_mint_first_bias` to the same `TestCase` class that owns `test_revenium_classifier_llm_label` (around line 1235 — add the new method immediately above or below it). The new test imports the classifier module via the same `importlib.reload` + plugin-env pattern the surrounding tests already use (or just imports it directly if no env setup is required for a pure-string function — pick the lighter approach; the prompt function reads no state), calls `_build_classification_prompt("user message text", "assistant response text", ["generation", "code_review", "research"])`, captures the returned string, and asserts: the literal substring "Mint a SPECIFIC, DESCRIPTIVE label" appears; each of the five example labels appears; the substring `generation` appears in an AVOID context (assert the AVOID line is present); the regex `^[a-z][a-z0-9_]{1,47}$` appears; the substring `ack` appears (forbidden-labels line); and `len(result) <= 4096` so the prompt-size invariant is pinned. Do NOT modify `test_revenium_classifier_llm_label` or `test_revenium_classifier_llm_blocklist_fallthrough` — they pass unchanged. Commit message: `feat(classifier): rewrite _build_classification_prompt to mint-first bias`.
  </action>
  <verify>
    <automated>cd /Users/johndemic/Development/projects/revenium/hermes-revenium &amp;&amp; python3 -m py_compile skills/revenium/plugins/revenium-classifier/classifier.py &amp;&amp; python3 -m unittest discover -s tests -p 'test_*.py' -v 2>&amp;1 | tail -5</automated>
  </verify>
  <done>
    `py_compile` exits 0 for `skills/revenium/plugins/revenium-classifier/classifier.py`. Full suite shows OK with the new test count = previous_count + 1. Both `test_revenium_classifier_llm_label` and `test_revenium_classifier_llm_blocklist_fallthrough` pass unchanged. The new `test_revenium_classifier_prompt_mint_first_bias` passes. `grep -c 'Mint a SPECIFIC, DESCRIPTIVE label' skills/revenium/plugins/revenium-classifier/classifier.py` returns `1`. `grep -c 'weekly_pr_review' skills/revenium/plugins/revenium-classifier/classifier.py` returns `1`. `grep -c 'Pick the single best-fitting existing label' skills/revenium/plugins/revenium-classifier/classifier.py` returns `0` (old framing removed). Single commit on main with message starting `feat(classifier):` and touching exactly two files.
  </done>
</task>

<task type="auto">
  <name>Task 2: Write quick-task SUMMARY</name>
  <files>.planning/quick/260514-nfb-rewrite-classifier-prompt-to-mint-first-/260514-nfb-SUMMARY.md</files>
  <action>
    Write `.planning/quick/260514-nfb-rewrite-classifier-prompt-to-mint-first-/260514-nfb-SUMMARY.md` using the standard summary template. Include: one-liner stating the prompt was rewritten to mint-first bias; "What Shipped" section listing the two modified files with brief change descriptions; "Why This Change Was Needed" citing the Mac Studio 12/16-marker live evidence and the D-07 fix exposing the bias; "Files Touched" table; "Verification" section listing the four green-check commands (py_compile, full suite, grep for "Mint a SPECIFIC", grep for "weekly_pr_review"); "Decisions Made" section noting the choice to ship a single atomic T01 (code + regression test together) rather than splitting; "Follow-ups / Out of Scope" section noting that real-world bias verification will come from the next 24-48h of cron markers on Mac Studio — not part of this commit. Frontmatter must include `phase: 260514-nfb-rewrite-classifier-prompt-to-mint-first-`, `plan: 01`, `status: complete`, `requirements: [PROMPT-MINT-FIRST]`, `files_modified` listing the two files from T01, `completed_date` (today's date), and the T01 commit hash. Commit message: `docs(260514-nfb): summarize mint-first prompt rewrite`.
  </action>
  <verify>
    <automated>test -f /Users/johndemic/Development/projects/revenium/hermes-revenium/.planning/quick/260514-nfb-rewrite-classifier-prompt-to-mint-first-/260514-nfb-SUMMARY.md &amp;&amp; head -20 /Users/johndemic/Development/projects/revenium/hermes-revenium/.planning/quick/260514-nfb-rewrite-classifier-prompt-to-mint-first-/260514-nfb-SUMMARY.md</automated>
  </verify>
  <done>
    SUMMARY.md exists at the expected path with valid YAML frontmatter (phase, plan, status, requirements, files_modified, completed_date, commits). Body covers what shipped, why, files, verification, decisions, and follow-ups. Second commit on main with message starting `docs(260514-nfb):` and touching exactly one file (the SUMMARY).
  </done>
</task>

</tasks>

<verification>
- `python3 -m py_compile skills/revenium/plugins/revenium-classifier/classifier.py` exits 0.
- `python3 -m unittest discover -s tests -p 'test_*.py' -v` passes green with test count = baseline + 1 (the new `test_revenium_classifier_prompt_mint_first_bias`).
- `grep -c 'Mint a SPECIFIC, DESCRIPTIVE label' skills/revenium/plugins/revenium-classifier/classifier.py` returns `1`.
- `grep -c 'Pick the single best-fitting existing label' skills/revenium/plugins/revenium-classifier/classifier.py` returns `0` (old framing gone).
- `grep -c 'weekly_pr_review' skills/revenium/plugins/revenium-classifier/classifier.py` returns `1`.
- `git log --oneline -2` shows two commits: `feat(classifier): rewrite _build_classification_prompt to mint-first bias` then `docs(260514-nfb): summarize mint-first prompt rewrite`.
- `_classify_via_llm`, `_validate_label`, `_read_taxonomy_labels`, `TRIVIAL_BLOCKLIST`, and `LABEL_RE` are byte-unchanged (verified by `git diff HEAD~2 -- skills/revenium/plugins/revenium-classifier/classifier.py` showing changes only inside `_build_classification_prompt`).
</verification>

<success_criteria>
- Prompt is mint-first: "Mint a SPECIFIC, DESCRIPTIVE label" appears verbatim in the prompt body, the old "Pick the single best-fitting existing label" framing is gone.
- Concrete example anchor list (`weekly_pr_review`, `prod_log_triage`, `news_summary`, `sql_query_debug`, `release_notes_draft`) is present so the LLM has a granularity target.
- Explicit AVOID line names the four bland catch-alls (`generation`, `analysis`, `review`, `task`).
- Existing-labels block is reframed as "MAY reuse if (and only if) they describe the SAME specific work" — reuse is the narrow exception, not the default.
- Regex contract `^[a-z][a-z0-9_]{1,47}$` and the TRIVIAL_BLOCKLIST forbidden labels remain in the prompt body.
- Surrounding helpers and globals are byte-unchanged.
- Regression guard test `test_revenium_classifier_prompt_mint_first_bias` is in place and would catch a future revert to bland framing.
- Both pre-existing classifier tests at lines 1235 and 1287 pass unchanged.
- Full suite green at both commit boundaries.
- Two-commit history on main: T01 (feat) + T02 (docs SUMMARY).
</success_criteria>

<output>
After completion, the SUMMARY at
`.planning/quick/260514-nfb-rewrite-classifier-prompt-to-mint-first-/260514-nfb-SUMMARY.md`
captures the prompt rewrite, the four behavior changes, and the live-evidence
motivation. The next 24-48h of cron markers on Mac Studio will provide the
real-world bias-shift evidence; that observation is not part of this commit
and lives in the SUMMARY's "Follow-ups" section.
</output>
