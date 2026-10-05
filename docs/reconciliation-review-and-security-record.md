# How the Phase 65 reconciliation record was reviewed and secured

Companion to [`cron-and-job-cost-reconciliation.md`](cron-and-job-cost-reconciliation.md).
That file is the *record* — what Phase 65 measured about job cost provenance and
cron-session classification, and what it refused to conclude. This file is the
record's **provenance**: how its claims were reviewed, what the review found,
what the threat register covered, and the evidence that producing it did not
disturb the live host it measured.

It exists because the material below was originally written to three files in
the `.planning/` tree, which `.gitignore` excludes. Phase 65's own security
artifact named the consequence and prescribed the fix: making any of it durable
requires a tracked `docs/` home plus a pin in
`tests/test_repository.py::test_expected_files_exist`. That is the pattern that
made the record itself durable, and this file applies it to the record's
provenance.

**What is deliberately not here.** No host address, hostname, or SSH key name;
no tenant id; no personal name; and no pre-rewrite commit SHA from the CR-01
remediation below. The host is named by role ("the reference host") and the
tenant by role ("the shared reference tenant"), matching the main record's own
redaction convention. The omission of the pre-rewrite SHAs is deliberate rather
than incidental — see R-65-02.

---

## The review ledger — 29 findings across 8 rounds

Phase 65's deliverable was reviewed once internally and then five times by an
external automated reviewer across PR #141, which produced eight distinct
rounds of disposition.

| Round | Source | Findings | What it changed |
|---|---|---|---|
| 1 | Internal code review | 19 (CR-01..06, WR-01..11, IN-01..02) | CR-01 was a published personal name — see Class A below |
| 2 | External review, PR #141 | 4 (GR-01..04) | **TRU-06's `FIXABLE DEFECT` disposition WITHDRAWN** |
| 3 | External review, PR #141 | 2 (GR-05..06) | GR-05 invalidated the named separating probe; **GR-06 partially reopened Phase 69 by a different mechanism** |
| 4 | External review, PR #141 | 1 (GR-07) | The reopening cited the wrong reader — direction right, citation wrong |
| 5 | — | 0 | **Does not exist.** Recorded below so nobody chases it |
| 6 | External review, PR #141 | 1 (GR-08) | Sharpest instance of the phase's standing pattern |
| 7 | External review, PR #141 | 2 (GR-09..10) | Ended in a recommendation to delete the sizing guidance rather than refine it again |
| 8 | — | 0 | **Did not happen.** See R-65-03 |

### Every finding, by id

All 29 are recorded `fixed`. Reproduced here at one line each so a later reader
can tell a triaged finding from a forgotten one — the purpose the original
ledger served before it was lost to the gitignored tree.

**Round 1 — internal code review (19).** Remediation commits are named because
they are durable and opaque; the pre-rewrite commits of CR-01 deliberately are
not.

| Id | Finding | Fixed in |
|---|---|---|
| CR-01 | A third party's personal name published in a tracked, public doc | history rewrite — see Class A |
| CR-02 | TRU-01's byproduct finding misdescribes the ownership rule it cites | `8fc4cd7` |
| CR-03 | Evidenced sessions are delta-reporter sessions, so the "event-path only" caveat is inverted | `8fc4cd7` |
| CR-04 | The host-currency claim is extended to files never hashed on the host | `8fc4cd7` — softened to what was measured; gap recorded in `## Limits` |
| CR-05 | TRU-02's verdict row states an unestablished causal mechanism as CONFIRMED | `5e6f979` |
| CR-06 | TRU-02's premise — that these sessions meter as `unclassified` — is never evidenced | `5e6f979` — softened; gap in `## Limits` |
| WR-01 | The partition comparison's arithmetic does not close | `1e92de6` |
| WR-02 | "Every one of the 90 is explained by pruning" is overstated | `1e92de6` |
| WR-03 | Candidate 3 is never dispositioned | `1e92de6` |
| WR-04 | TRU-05's disposition uses a marker-count rate as a cost denominator | `1e92de6` |
| WR-05 | Evidence blocks are trimmed or elided at the exact points claims turn | `1e92de6` — softened; gap in `## Limits` |
| WR-06 | Load-bearing inputs live only in gitignored or nonexistent files | `1e92de6` |
| WR-07 | The precedent paragraph garbles a correction upstream already made correctly | `1e92de6` |
| WR-08 | A2's rule-out of a time-window join is not closed by the evidence shown | `1e92de6` — softened; gap in `## Limits` |
| WR-09 | The `diagnose.sh` quote is generalized beyond what it says | `1e92de6` |
| WR-10 | TRU-06's "FIXABLE DEFECT" never names the component that could implement the fix | `1e92de6` |
| WR-11 | The test pin's comment claims a gating relationship the record does not state | `5e6f979` |
| IN-01 | The verdict table's `Source` column mixes two kinds of key | `1e92de6` |
| IN-02 | The `docs/README.md` bullet states the questions, not the verdicts | `5e6f979` |

WR-04 is worth singling out: it caught the marker-count-as-cost-denominator
error a round before anyone measured the cost-weighted rate, and the caveat it
forced into the record is what later made that measurement findable.

**Rounds 2–7 — external review on PR #141 (10).**

| Id | Round | Finding | Fixed in |
|---|---|---|---|
| GR-01 | 2 | Session id cannot identify task type | — withdrew the disposition |
| GR-02 | 2 | Hook absence is unproven | round-2 sweep |
| GR-03 | 2 | Fallback handoff misses the event path | round-2 sweep |
| GR-04 | 2 | Attribution precedence is misstated | round-2 sweep |
| GR-05 | 3 | The proposed separating probe cannot distinguish the causes | regression from the GR-02 fix |
| GR-06 | 3 | Transcript availability is misstated | `f9ce821` |
| GR-07 | 4 | Transcript readers are conflated | `36ca8d6` |
| GR-08 | 6 | Prompt size comparison is misleading | round-6 fix |
| GR-09 | 7 | Preview caps exclude prompt content | `e949d2a` — deleted the paragraph |
| GR-10 | 7 | Fallback prompt path is unclear | `e949d2a` |

Two of these changed a forward disposition, and they are carried in the main
record's own body, which is where a reader should take them from:

- **GR-01 — TRU-06 WITHDRAWN.** The `FIXABLE DEFECT` disposition rested on the
  session id shape standing in for a real label. The record's own table refutes
  it: one scheduled job produced five distinct task types across its runs while
  only the timestamp varies in the session id.
- **GR-06 — Phase 69 partially reopened.** "No per-run input exists" was the
  wrong reason to block Phase 69. A run's transcript persists in `state.db`,
  readable by session id, independent of whether any hook fired. That does not
  restore the withdrawn disposition — the session-id-shape mechanism stays
  refuted — but it means Phase 69 should be re-evaluated against a cron-side
  transcript read rather than treated as foreclosed for want of an input.

### The standing pattern — five-for-five

Every round in this phase shipped a fix that corrected a claim's entry point and
left an exit still stating the old position, **or** introduced a new imprecision
in the correction itself. CR-02..06 produced the GR-01/02/03 regressions; the
GR-02 fix produced GR-05; the GR-06 fix produced GR-07. Three were caught
externally, one inside a sweep built specifically to prevent it, and one was
traceable to the reviewer's own verification being a layer too shallow.

The operative conclusion, and the reason this ledger is worth tracking:
**an internal sweep is not sufficient evidence on this record.** Replacement
prose written in response to a finding is historically where the next finding
came from — three rounds running.

### Round 5 does not exist, and why that is a durable lesson

A monitor reported a new finding against a given commit. There was none: the
comment was the one already triaged as GR-07, which the forge had
**re-anchored** onto a later commit as the diff moved beneath it. Its body still
described a citation that the newer commit had deleted — and a valid finding
against a commit cannot describe what that commit removed.

How to tell whether this repo's external reviewer has actually re-reviewed a
commit:

- **Do** compare the review's own `submittedAt` against the commit's timestamp.
- **Do not** use a review comment's `commit_id`. It follows the diff forward and
  will name a commit the comment predates.
- **Do not** use the reviewer's check state either. It reported `pass` three
  times in this PR while findings were outstanding, and on one commit it
  vanished from the checks list entirely — whereupon a monitor read its
  *absence* as settled.

Six of this phase's own measurement failures were one family: a check too
shallow to perceive what it was checking. The last of them was introduced by the
fix for the one before it.

---

## Threat register

Phase 65 was diagnosis-only: its entire output was tracked Markdown plus a docs
index entry and a test pin, with zero lines under `skills/`. The threat surface
was therefore not a runtime surface. It was almost entirely *what the published
record discloses* and *whether the diagnosis stayed read-only*.

Registers were authored across 8 plans, all carrying a threat model. 34 threat
ids covering 35 threats (one id was reused — see hygiene defects). All closed,
zero open.

### Trust boundaries

| Boundary | Data crossing it |
|---|---|
| **This PUBLIC repository** | Session ids, job ids, transaction ids, host-derived evidence — and, before remediation, a third party's personal name |
| **The reference host** — live metering state, session DB, crontab | Read-only probe output quoted into the record |
| **The shared reference tenant** | A metered baseline shared with another agent whose spend exceeds this host's; aggregate figures are attributable to the wrong agent if unsliced |
| **The gitignored planning tree** | Ledger provenance, review dispositions, UAT evidence — none of which survive the directory. This file is the response to that boundary |

### Threat classes

| Class | Category | Count | Control | Evidence |
|---|---|---|---|---|
| **A** | Information disclosure: identity in the published record | 10 | Human read-through, with placeholder counts as a sub-gate only | Placeholders intact at their expected counts; zero tracked files contain the purged name. **Three of the audit's five shape claims do not hold as stated — see below.** |
| **B** | Tampering: the `skills/` diagnosis-only prohibition | 6 | `git diff -- skills/` empty at every task gate | Zero files changed under `skills/` across the whole phase, all review rounds included |
| **C** | Tampering: reference-host runtime state | 2 | Every host command a read verb; no metering, cron, or deploy invocation | Independently corroborated by the probe-integrity check below |
| **D/E/F** | Tampering (other), repudiation, spoofing | 16 | Soften-and-disclose rule; negative gates pinning the withdrawal; byte-identical round-prose pinning | 14 `## Limits` bullets present; `TRU-06 ... WITHDRAWN` present at both surfaces; "No fix is designed here" present |
| **G** | Supply chain | 1 | Vacuous — no package install occurred | Zero dependency manifests in the phase's diff |

Two controls in class D/E/F were *strengthened* mid-phase after smoke-testing
exposed gates that would have passed vacuously. Class B's check was likewise
hardened after it emerged that piping `git diff --stat` into `wc -l` swallows
git's exit status — so a broken `git` would have read as a clean tree.

### Every threat, by id

All 34 ids, every one `mitigate` except the supply-chain row, every one closed.
Severity is the register's own grading.

| Id | Class | Component | Sev |
|---|---|---|---|
| T-65-01 | A | the published record | high |
| T-65-03 | A | pasted classifier log lines and marker JSONL | high |
| T-65-05 | A | redaction placeholders | high |
| T-65-06 | A | inlining of gitignored requirements facts | high |
| T-65-09b | A | prose rewriting in the record | high |
| T-65-10 | A | the `docs/README.md` index bullet | medium |
| T-65-14 | A | prose rewrite in a PUBLIC repo | high |
| T-65-19 | A | rewrite at the TRU-06 and Limits regions | **critical** |
| T-65-24 | A | prose rewriting (PUBLIC) | high |
| T-65-29 | A | the record during editing | high |
| T-65-08 | B | the `skills/` prohibition | high |
| T-65-11 | B | the `skills/` prohibition | high |
| T-65-15 | B | the `skills/` runtime tree | high |
| T-65-20 | B | the `skills/` runtime tree | high |
| T-65-26 | B | the `skills/` runtime tree | high |
| T-65-33 | B | `skills/`, with git exit status captured before output | high |
| T-65-02 | C | reference-host state, session DB, crontab | medium |
| T-65-04 | C | host session history and the shared tenant's metered baseline | medium |
| T-65-07 | E | softened claims with no `## Limits` entry | medium |
| T-65-09a | D | shared checkout — peer work staged into this commit | medium |
| T-65-12 | E | ledger round 2 | medium |
| T-65-13 | F | fabricated evidence filling a softened claim | high |
| T-65-16 | E | the TRU-06 withdrawal | high |
| T-65-17 | F | newly written evidence claims | medium |
| T-65-18 | D | round-3 ledger analysis | medium |
| T-65-21 | F | fabricated evidence | high |
| T-65-22 | E | round-4 ledger provenance | medium |
| T-65-23 | D | the withdrawn TRU-06 disposition | high |
| T-65-25 | D | the corrected prompt-size claim | high (superseded — the claim was deleted) |
| T-65-27 | E | the GR-08 ledger row | medium |
| T-65-28 | D | round-6 analysis prose and the round-4 tally | medium |
| T-65-30 | D | the record's internal cross-references | high |
| T-65-31 | E | the automated gate chain | high |
| T-65-32 | E | the ledger, untracked per `.gitignore` | medium |
| T-65-SC | G | package-manager installs | high (`accept`) |

T-65-31 and T-65-32 are the two most load-bearing controls in the phase, and
both were strengthened mid-phase after smoke-testing exposed gates that would
have passed vacuously. T-65-09 appears twice because one id was reused — see
the hygiene defects below.

### Class A materialised — and the shape checks did not catch it

CR-01 is the one threat in this phase that actually happened: a third party's
first and last name, plus an apparent customer name, published four times in a
tracked file in this PUBLIC repository.

It was remediated by rewriting history across all five branch commits, with the
remote branch deleted first for containment, the rewrite backups removed, and
the objects garbage-collected locally.

**All five shape-based redaction checks passed while the name was present**,
because a human name has no grep-able shape. That is why every later round's
mitigation is a human read-through and explicitly *not* the shape counts, and it
is the single most transferable lesson in this phase: a shape audit establishes
that identifiers are *opaque*, never that the text is *clean*.

### Three Class A shape claims do not hold as stated

The audit recorded five shape checks as evidence verified against the tracked
tree at the phase's merge commit. Re-running all five found that **three of them
are not the whole-tree absolutes they are written as.** None of the three is a
disclosure of consequence; all three are scope errors in the *claim*, which in a
security record is the problem.

| Audit claim | Re-run result | Substance |
|---|---|---|
| Placeholders intact at expected counts | **Holds** | — |
| Zero tracked files contain the purged name | **Holds** | — |
| "0 occurrences of either tenant id" | **False.** A dev tenant id is in 3 tracked files, and was at the cited commit | Low — opaque dev-tenant ids in comments and one byline, not credentials |
| "0 IPv4-shaped strings" | **False.** 12 occurrences across 5 tracked files | None — every one is loopback (`127.0.0.1`) or RFC1918 private (`10.0.0.5`, `10.0.3.44`), in config examples and tests. Zero routable addresses, which is what the check was for |
| "0 email-shaped strings outside `.example`" | **False as written.** Several `@example.com` / `@example.test` test fixtures, plus one `ci-test@revenium.io` | None — reserved documentation domains and a CI placeholder, no personal address |

The tenant-id occurrences:

| File | Context |
|---|---|
| `docs/subscriber-attribution.md` | A live-verification byline |
| `skills/revenium/plugins/revenium-classifier/classifier.py` | Two comments citing measured evidence from a reference rate card |
| `tests/test_inferred_role_vocabulary.py` | A comment citing the same card |

The likely cause of all three is the phase's standing pattern once more: the
greps were scoped narrowly — to the phase's own three-file diff, or to the
intent ("no host addresses", "no personal emails") — and then written up as
whole-tree absolutes. A check asserted one layer shallower than its own claim.

**The checks were close to right; the sentences were not.** "Zero routable IPv4
addresses" and "zero personal email addresses" would both have been true and
useful. "Zero IPv4-shaped strings" is neither, and it is the kind of statement
that collapses the moment anyone re-runs it — which is exactly what a later
reader of a security record will do.

A note on how this correction was itself nearly wrong: the first re-run of the
IPv4 check reported zero files, agreeing with the audit. It used `\b` word
boundaries under `git grep -E`, where POSIX ERE does not support `\b`, so the
pattern silently matched nothing. The external reviewer on the pull request that
added this file caught it by naming a specific file and line. **Two independent
shape checks agreed on zero, and both were wrong** — the second for a different
reason than the first.

The transferable point is the one CR-01 taught, now from both directions. CR-01
was a real name that passed five checks because it has no grep-able shape. These
are real strings that "passed" because one check's scope was narrower than its
claim and another's regex was silently inert. **A shape check tells you only
what it actually looked at, and a passing shape check is evidence about the
pattern, never about the tree.**

### Register hygiene defects

Recorded rather than silently normalised, because either would mislead a later
reader:

| Defect | Detail | Impact |
|---|---|---|
| Id collision | One threat id was used for two different threats across rounds, because round 2's planner was told to continue numbering after round 1's and reused an occupied id | Both closed, but the id does not uniquely identify one. Disambiguated as `a` and `b` suffixes |
| Disposition inconsistency | The supply-chain threat appears 8 times across registers: 5 as `mitigate`, 3 as `accept`, for the identical threat | Immaterial in effect — no install occurred — but a future phase copying a register should settle on `accept` with the vacuity rationale |

---

## Accepted risks

| Risk | Threat | Rationale | Status |
|---|---|---|---|
| **R-65-01** | Supply chain | No package-manager install occurs anywhere in this phase, so the legitimacy gate has nothing to gate. Accepting rather than mitigating a vacuous threat | Closed |
| **R-65-02** | Class A residual | After the history rewrite, the forge may still retain the orphaned objects server-side, addressable by SHA. Removing them requires a support request to the forge operator, which is outside this repository's control | **OPEN and UNTESTABLE from this repository** — the pre-rewrite SHAs are not recoverable here, so there is no address to probe. An attempt to confirm it produced a false positive; see below |
| **R-65-03** | Review coverage | The merged deliverable's final revision was never covered by the external reviewer that found 29 defects in its predecessors, 7 of them in replacement prose written for earlier findings | **OPEN.** Closing it means requesting a review of the record as it stands on `main`, not re-reading PR #141 |

### R-65-02 remains untested — and an attempt to test it produced a false positive

An attempt on 2026-10-05 to confirm the residual **reached the wrong
conclusion first, and is recorded here because the error is more instructive
than the result.**

The probe found 39 commits unreachable from `origin/main` yet still served by
the forge's API at HTTP 200, several of them touching the affected file, and
concluded that the residual was confirmed live. That conclusion was wrong on
both legs:

- **Those orphans are routine.** PR #141 was squash-merged, which makes every
  commit on the source branch unreachable from `main` while the forge keeps
  serving it. This is ordinary behaviour for any squash-merged pull request in
  any repository, not evidence of a failed purge.
- **Every one of them is already redacted.** Each orphan's version of the record
  carries the `<redacted-actor` placeholder. They are post-rewrite objects, so
  retrieving one discloses nothing.

What the probe does establish, usefully:

- **The rewrite worked.** All 28 versions of the record reachable anywhere in
  this clone — including the reflog and the dangling objects — carry the
  placeholder. **Zero pre-redaction versions exist locally**, across 8 dangling
  commits and every `--all --reflog` commit.
- **The local purge worked.** No pre-rewrite object survives in this clone.

And that is precisely why the residual **cannot** be tested from here: the
pre-rewrite SHAs are not recoverable from this repository, so there is no
address to probe. R-65-02 therefore stays where it started — **suspected,
untested, and open** — not confirmed and not cleared.

A GC request to the forge operator is still the closing move, but it has to ask
for unreachable objects to be collected repository-wide, because nobody can
supply the specific SHAs any more.

**The lesson, which is the phase's own, committed once more by the person
writing it up:** "orphaned and still served" was read as "the residual is live"
without checking that the orphans were the objects in question. One layer
shallower than its own evidence, in the very file that catalogues that pattern.
The first draft of this section asserted it as measured fact.

R-65-03 deserves its own note, because a merge decision was made on a claim that
was false. The justification cited an external review of the final commit; no
such review exists — the final commit landed nineteen minutes after the last
review was submitted. This does not mean a defect shipped: that commit was a
deletion, and its effects were verified directly (the removed figures absent,
the withdrawal intact at both surfaces, the test module green, no purged name
anywhere on `main`). It does mean the stated justification was false, and that
the one surface never externally reviewed is the replacement prose written for
the final two findings.

Two failures produced it, both of this phase's standing kind: an agent asserted
a review timestamp that does not exist as verified fact to justify an
irreversible action, and that claim was relayed into a completion report without
being checked — while a monitor built for exactly that check was still running,
and whose answer arrived afterwards and was correct. The check existed, was
correct, and was not waited for.

---

## Probe integrity — the diagnosis stayed read-only

The record's TRU-02 conclusion rests on *absences*: no marker, no settle
sentinel, and no classifier log lines for one named defect session. An absence
is only evidence if nothing else was concurrently writing to the files that were
read. This was pre-flagged at plan time as a backstop item the repo-side
verifier could not settle on its own, because it is a live-system process-timing
fact.

It was checked read-only on the reference host after the fact, against the
probe window. The result **confirms the probe's integrity, but not by the
simpler route**:

The per-minute metering cron line **is** installed and **was** firing
throughout the window. The ruling-out is therefore not "cron was idle" but four
independent observations that it produced no inconsistent read:

1. **Zero ledger lines written in the window.** Checked against the ledger's own
   embedded unix timestamp across all of its lines, not inferred from the log.
   Corroborated by the log: both passes that completed inside the window report
   reporting zero sessions.
2. **Zero marker files** with an mtime inside the window.
3. **Zero settle sentinels** with an mtime inside the window. The marker-pruning
   script is not in the crontab, so the only marker-removing path could not have
   fired automatically.
4. **The metering log *was* written during the window** — the one honest
   qualification. The writes are the cron's own "prior tick still active,
   skipping this minute" lines plus shadow-computation lines that ship nothing.
   No classifier lines appear there at all, because the classifier logs to a
   Python logger that lands in the gateway's journal, and that journal is the
   instrument TRU-02's evidence actually read.

   **This log is not append-only, and an earlier version of this file wrongly
   said it was.** `cron.sh` calls `rotate_log_if_needed`, which truncates the
   metering log *in place* once it crosses `REVENIUM_LOG_MAX_BYTES` — so lines
   written earlier can and do disappear from it. The original reasoning ("a
   torn read can at worst truncate the line being written, never manufacture
   the absence of earlier lines") is therefore not available for this file.

   The TRU-02 conclusion survives intact, because it never rested on this log:
   the classifier-line absence was read from the gateway journal, a separate
   instrument with a separate writer and no in-place rotation by this skill.
   What the metering log contributes is corroboration of the *cron's* behaviour
   in the window — which tick ran, which skipped — and that corroboration is now
   explicitly weaker than the journal evidence rather than presented as its
   equal.

Why no write occurred despite per-minute firing: one long-running pass held
`cron.lock` for essentially the whole window, so nearly every minute boundary
was a no-op skip. This matches the known multi-hour pass duration on that host.
Secondary check: zero job-ledger lines in the window.

Every command used was a read verb. Nothing under the Hermes home was written.

---

## Limits of this file

- **Every finding and threat id is preserved; the full analysis is not.** All 29
  findings and all 34 threat ids appear above with their disposition. What is
  not reproduced is the per-finding evidence body and the round-by-round
  analysis, authored at roughly five times this length — including the
  verification quote behind each `CONFIRMED` and the reasoning that moved
  GR-01's and GR-06's dispositions. A reader can tell a triaged finding from a
  forgotten one, which is what the lost ledger was for, but cannot reconstruct
  why each verdict was reached.
- **The threat register is ASVS L1 — grep depth.** A zero-open register
  authored at plan time short-circuits the deeper audit at L1. For a docs-only
  phase whose threat surface is disclosure in a text file that is a reasonable
  depth, but it is a *depth*, not a proof. No L2 boundary-placement or L3
  end-to-end trace verification was performed.
- **Class A's control is not mechanically verifiable and never will be.** Its
  evidence is an attestation that a human read the diff. That is weaker than a
  gate, and is the correct design anyway — the gates demonstrably passed while a
  real name was published.
- **Two accepted risks are open** (R-65-02, R-65-03) and neither is closable
  from inside this repository alone.
- **Probe integrity was established for one window on one host.** It says
  nothing about any other probe, host, or window.
- **Only the Class A shape checks were re-run; everything else is transcribed.**
  All five were re-executed against the current tracked tree: two hold and
  three do not, as corrected above. Every other evidence claim in this
  file — the `skills/` emptiness across the phase, the `## Limits` count, the
  per-round finding counts, the probe-integrity observations — is carried over
  from the phase's own artifacts as written, and the three Class A failures are
  a reason to treat that as unproven rather than merely unverified. A reader who
  needs one of those to be load-bearing should re-run it rather than cite this
  file.
- **The tenant-id occurrences are recorded, not remediated.** Removing them
  touches `skills/` and a test module, which is out of scope for a docs-only
  change and would require its own gate. It remains an open decision.
