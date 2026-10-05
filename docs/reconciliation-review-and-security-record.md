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

Every finding is recorded `fixed`. The two that changed a forward disposition
are already carried in the main record's own body, which is where a reader
should take them from:

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
| **A** | Information disclosure: identity in the published record | 10 | Human read-through, with placeholder counts as a sub-gate only | Placeholders intact at their expected counts; zero tracked files contain the purged name; zero IPv4-shaped strings; zero email-shaped strings outside `.example`. **One of the audit's five evidence claims does not hold — see below.** |
| **B** | Tampering: the `skills/` diagnosis-only prohibition | 6 | `git diff -- skills/` empty at every task gate | Zero files changed under `skills/` across the whole phase, all review rounds included |
| **C** | Tampering: reference-host runtime state | 2 | Every host command a read verb; no metering, cron, or deploy invocation | Independently corroborated by the probe-integrity check below |
| **D/E/F** | Tampering (other), repudiation, spoofing | 16 | Soften-and-disclose rule; negative gates pinning the withdrawal; byte-identical round-prose pinning | 14 `## Limits` bullets present; `TRU-06 ... WITHDRAWN` present at both surfaces; "No fix is designed here" present |
| **G** | Supply chain | 1 | Vacuous — no package install occurred | Zero dependency manifests in the phase's diff |

Two controls in class D/E/F were *strengthened* mid-phase after smoke-testing
exposed gates that would have passed vacuously. Class B's check was likewise
hardened after it emerged that piping `git diff --stat` into `wc -l` swallows
git's exit status — so a broken `git` would have read as a clean tree.

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

### One Class A evidence claim does not hold — found while writing this file

The security audit recorded, as evidence verified against `main` at the
phase's merge commit, that the tracked tree contained "0 occurrences of either
tenant id". **That claim is false, and was false at the commit it cited.**
Re-running the check while writing this file found a dev tenant id in three
tracked files at that exact commit, all three still present today:

| File | Context |
|---|---|
| `docs/subscriber-attribution.md` | A live-verification byline |
| `skills/revenium/plugins/revenium-classifier/classifier.py` | Two comments citing measured evidence from a reference rate card |
| `tests/test_inferred_role_vocabulary.py` | A comment citing the same card |

The most likely cause is the phase's standing pattern once more: the grep was
almost certainly scoped to the phase's own three-file diff — where zero is
correct — and then written up as a whole-tree claim. A check asserted one layer
shallower than its own evidence.

**Severity is low, but not zero.** These are opaque dev-tenant identifiers in
comments and a byline, not credentials, and "keep identifiers raw" is a
defensible convention precisely when they are opaque. No access follows from
knowing them. What is not acceptable is a *false evidence claim* in a security
record, which is why it is corrected here rather than carried forward: the four
other Class A checks were re-run while writing this file and all four do hold.

The transferable point is the same one CR-01 taught, pointing the other way:
a shape check that passes tells you only what it actually looked at. CR-01 was a
real name that passed five checks because it had no shape; this was a real
identifier that "passed" because the check's scope was narrower than its claim.

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
| **R-65-02** | Class A residual | After the history rewrite, the forge may still retain the orphaned objects server-side, addressable by SHA. Removing them requires a support request to the forge operator, which is outside this repository's control | **OPEN — needs a human.** This is also why no pre-rewrite SHA is named anywhere in this file |
| **R-65-03** | Review coverage | The merged deliverable's final revision was never covered by the external reviewer that found 29 defects in its predecessors, 7 of them in replacement prose written for earlier findings | **OPEN.** Closing it means requesting a review of the record as it stands on `main`, not re-reading PR #141 |

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
4. **The metering log *was* appended to during the window** — the one honest
   qualification. The appends are the cron's own "prior tick still active,
   skipping this minute" lines plus shadow-computation lines that ship nothing.
   No classifier lines appear there at all, because the classifier logs to a
   Python logger that lands in the gateway's journal, and that journal is the
   instrument TRU-02's evidence actually read. An append-only torn read can at
   worst truncate the line being written; it cannot manufacture the *absence* of
   lines written earlier, which is what the TRU-02 conclusion rests on.

Why no write occurred despite per-minute firing: one long-running pass held
`cron.lock` for essentially the whole window, so nearly every minute boundary
was a no-op skip. This matches the known multi-hour pass duration on that host.
Secondary check: zero job-ledger lines in the window.

Every command used was a read verb. Nothing under the Hermes home was written.

---

## Limits of this file

- **It is a summary, not the primary artifact.** The per-finding rows, the
  per-threat-id table, and the full round-by-round analysis were authored at
  roughly five times this length. What is preserved here is every finding's
  disposition in aggregate, every threat class and its control, every accepted
  risk, and every lesson that transfers. Individual finding bodies are not
  reproduced.
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
- **The Class A shape checks were re-run while writing this file; the rest of
  the evidence was transcribed, not re-verified.** Four of the five Class A
  checks were re-executed against the current tracked tree and hold; the fifth
  does not, and is corrected above. Every other evidence claim in this
  file — the `skills/` emptiness across the phase, the `## Limits` count, the
  per-round finding counts, the probe-integrity observations — is carried over
  from the phase's own artifacts as written. A reader who needs one of those to
  be load-bearing should re-run it rather than cite this file.
- **The tenant-id occurrences are recorded, not remediated.** Removing them
  touches `skills/` and a test module, which is out of scope for a docs-only
  change and would require its own gate. It remains an open decision.
