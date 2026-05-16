---
status: partial
phase: 08-job-declaration-prompt-block
source: [08-VERIFICATION.md]
started: 2026-05-15
updated: 2026-05-15
---

## Current Test

[halt-survivability matrix — operator-accepted via spot-check; full 4-run grid deferred]

## Tests

### 1. Halt-survivability 4-run matrix
expected: With `budget-status.json` flipped to `halted: true`, the next agent turn emits the verbatim halt string and makes at most one tool call — the mandated `CANCELLED` job-marker write, and only when an arc was in progress — across 2 session lengths (short ~2K / long ~20K) x 2 model families.
result: partial — operator-accepted 2026-05-15. A live halt-path spot-check on the Mac Studio host (qwen, short session) passed: the agent emitted the exact verbatim halt string, made only the mandatory `budget-status.json` read, called no `execute_code`, and wrote no spurious marker. The full 2x2 grid — long sessions, a second model family, and the mid-arc `CANCELLED`-marker write path — was not run. Recommended before a formal release; not blocking phase closure per operator decision.

## Summary

total: 1
passed: 0
issues: 0
pending: 1
skipped: 0
blocked: 0

## Gaps
