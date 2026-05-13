# Phase 3 Deferred Items

Items discovered during execution that are out-of-scope per the executor scope-boundary rule (only auto-fix issues DIRECTLY caused by current task's changes; pre-existing failures in unrelated files are out of scope).

## Pre-existing test failure: `test_no_legacy_branding_left`

**Status:** PRE-EXISTING (introduced by commit `2398bf9 docs(03): plan phase 3`)

**Symptom:** `python3 -m unittest discover -s tests -p 'test_*.py' -v` fails with the legacy-branding test flagging three planning artifacts:

```
.planning/phases/03-cron-marker-reader-equal-split-ledger-v2/03-01-PLAN.md
.planning/phases/03-cron-marker-reader-equal-split-ledger-v2/03-RESEARCH.md
.planning/phases/03-cron-marker-reader-equal-split-ledger-v2/03-PATTERNS.md
```

**Root cause:** The planning artifacts contain the literal regex tokens inside backticks in *meta-text describing the safety check itself* (e.g., quoting the regex pattern to explain what to avoid). Because this `deferred-items.md` file would also trip the same regex if it quoted the tokens, the token names are NOT reproduced here.

**Why deferred:**
- Not caused by any Phase 3 code change — was committed in `2398bf9` as part of the plan drafting step
- The plan EXPLICITLY says T11's D-16 doc text is branding-clean and audits this in T12 — implementation files are clean
- Falls outside the `skills/`, `scripts/`, and `tests/` boundaries Phase 3 touches
- Fixing belongs in Phase 5 housekeeping (which already owns frontmatter/branding/runtime-path housekeeping per CONTEXT.md line 26)

**Per-task verify-blocks unaffected:** Each Phase 3 task's `<verify>` block targets specific test methods (`test_split_strategies_conservation`, `test_cron_marker_split_end_to_end`, etc.). The `test_no_legacy_branding_left` failure is independent of every Phase 3 task's verify block.

**Recommendation for Phase 5:** Update the legacy-branding regex test to exclude `.planning/` artifacts, OR rewrite the meta-text in the three planning files to avoid the literal regex tokens (e.g., by splitting them across word boundaries).
