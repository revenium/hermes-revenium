# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions are the git tags on
this repository.

> `hermes skills install` resolves this repository's default branch, not its tags. A tag is
> a release marker; it does not gate what installs.

## [Unreleased]

### Added

- The evaluator's inferred role now reaches Revenium, and a role learned over time keeps it
  `jobs outcome --metadata` carries the role as `basis.role` (60 characters at
  most, before `basis.hours_saved`) on a reportable record only; a candidate record carries
  no `assumptions`, so no role. The sidecar's `basis` sentence and the narrative fields stay local. With no `rateCard`
  configured, the built-in `llm` evaluator now sees a learned role card: `role-taxonomy.json`,
  seeded with about 24 common roles and grown by the classifier. The prompt lists the known
  roles most-used first and asks the model to copy one verbatim or propose a new short title.
  The returned role is matched case-insensitively to a stored spelling, so `senior software
  engineer` is always `Senior Software Engineer`; junk such as `n/a` or `AI agent` is blanked
  and the card stops growing at 200 roles. After 3 observations in a currency the prompt also
  shows the role's typical rate as a consistency anchor. That rate is a prompt hint only, never
  a priced card: it changes no `evidence_class`, reportability or value, and early guesses can
  reinforce themselves through it. A configured `rateCard`, a disabled evaluation and any
  evaluator other than `llm` are unchanged. Existing installs need the updated classifier and
  the seed: re-run `install.sh` from a fresh clone, or run bootstrap with `--update` (a plain
  bootstrap run skips the fetch when the skill is already installed). Without the seed, the
  card learns from empty.

### Changed

- `jobs outcome --metadata` is now `schema_version` 2, and the evidence class
  `MODEL_ESTIMATED_DEMO` is renamed `MODEL_ESTIMATED`. This is a hard switch with no
  dual-emit: every new job's `outcomeMetadata` in Revenium is v2, and jobs reported before
  this change keep their v1 blob. Version 1 was one flat list of about thirty keys; version 2
  groups them into `value`, `basis`, `costs` and `estimator`, in a fixed order:
  `schema_version`, `source`, `status`, `session`, `failure_reason`, `outcome_basis`,
  `corrected`, `correction_sequence`, `value`, `basis`, `costs`, `estimator`,
  `metadata_truncated`. The object is still compact JSON of at most 4096 bytes, and the byte
  ceiling now sheds nested paths (the value tier first, then provenance) and never leaves an
  empty group. The key map:

  | v1 key | v2 path |
  |---|---|
  | `assessment_schema_version` | `schema_version` (always `2`) |
  | `reportability_status` | `status` |
  | `double_counting_group` | `session` |
  | `value_low`, `value_base`, `value_high` | `value.low`, `value.base`, `value.high` |
  | the `--outcome-value` sent | `value.reported` (new) |
  | `net_value` | not forwarded; `value.net` is now `value.reported` less `costs.subtracted` |
  | `attribution_fraction`, `attribution_basis` | `value.attribution.fraction`, `value.attribution.basis` |
  | `evidence_class` | `basis.evidence` |
  | `economic_mechanism` | `basis.mechanism` |
  | `assumptions.inferred_role`, `.estimated_hours_saved`, `.assumed_loaded_rate` | `basis.role`, `basis.hours_saved`, `basis.hourly_rate` |
  | `confidence` | `basis.confidence` |
  | `study_id`, `study_version` | `basis.study.id`, `basis.study.version` (newly sent) |
  | `supplied_costs` | `costs.subtracted` |
  | `cost_coverage.unknown`, `.known_zero`, `.excluded` | `costs.not_counted`, `costs.known_zero`, `costs.ai_cost` (`metered_separately`) |
  | the currency | `value.currency` (newly sent) |
  | `evaluator`, `model` | `estimator.name`, `estimator.model` |
  | `inference_provider`, `inference_address_class` | `estimator.provider`, `estimator.endpoint` |
  | `prompt_version`, `taxonomy_version`, `policy_version`, `evaluator_version` | `estimator.versions.prompt`, `.taxonomy`, `.policy`, `.evaluator` |
  | `corrected`, `correction_sequence` | unchanged |

  Dropped from the wire: `bounds_source` and `evidence_class_authority` (both stay in the
  sidecar) and `cost_coverage.included` (it always equalled the keys of `costs.subtracted`).
  `value.net` is `value.reported` less the subtracted costs, not v1's base-derived
  `net_value`, so it is never above the reported value; it appears only when a value was
  reported and a non-zero cost was subtracted. `schema_version` is written
  whenever assessment content is present; a blob with no assessment record (a `FAILED` arc's
  `source` and `failure_reason`, for instance) is byte-identical to before. `basis.evidence`
  says who priced the value, and `basis.hours_saved` and `basis.hourly_rate` are always the
  model's assumptions. Revenium will show `MODEL_ESTIMATED_DEMO` on jobs reported before
  this change and `MODEL_ESTIMATED` on new ones. A sidecar already on disk with the old
  label is read as `MODEL_ESTIMATED`, gated and reported identically, and the wire always
  carries the new label. The `jobs outcome-update` metadata written by
  `correct-assessment.sh` moves to the same schema in the next entry below. Anything that
  reads `outcomeMetadata` and keys on the v1 names needs the table above.
- Operator corrections now ship `schema_version` 2 metadata too. `correct-assessment.sh`
  sent v1 flat keys to `jobs outcome-update --metadata`, so the two verbs spoke different
  schemas and a reader had to decode both. The correction blob is now compact JSON in a fixed
  order, with absent members omitted: `schema_version` (`2`), `corrected` (`true`),
  `correction_sequence`, then `value` (`reported`, the exact `--outcome-value` the call sends,
  with `currency` and `attribution` as `fraction` and `basis`), `basis.mechanism`, and
  `prior` (`low`, `base`, `high`, `currency`: what the correction superseded). A
  mechanism-only correction sends no `--outcome-value`, so it has no `value` group. The key
  map is `assessment_schema_version` and `sequence` to `schema_version` and
  `correction_sequence`, `prior_value_low`/`_base`/`_high` and `prior_currency` to
  `prior.low`/`.base`/`.high`/`.currency`, `economic_mechanism` to `basis.mechanism`,
  `attribution_fraction` and `attribution_basis` to `value.attribution.fraction` and `.basis`,
  and the `--outcome-value` and `--outcome-currency` sent to `value.reported` and
  `value.currency` (both newly sent). Corrections already filed in Revenium keep the v1 keys;
  `schema_version` tells the two apart. The local sidecar correction record is unchanged.
  Whether Revenium replaces or merges `metadata` on an update is not documented, so a reader
  should treat each revision's metadata as that revision's own.

- The cron tick no longer re-derives every historical session every minute. `hermes-report.sh`
  and the shadow pass of `api-event-report.sh` visited every session with tokens on every
  tick, and a long-finished session cost 5–8 `python3` spawns per visit just to conclude there
  was nothing to do. On a desktop host with ~1,200 sessions and ~700 spool files one tick ran
  about 15 minutes, so the per-minute schedule skipped most minutes. Each script now keeps a
  cross-tick cache (`reporter-memo.jsonl`, `event-shadow-memo.jsonl`) of sessions that were a
  pure no-op, keyed on everything that no-op depended on: the session's state.db row, its
  marker, owner and spool files, both scripts, the mode switches, and the ledgers not having
  been replaced or truncated. Measured on a copy of that host's state: `hermes-report.sh` 200s
  → 7s, `api-event-report.sh` 172s → 5s, with the log, every CLI call and every shadow row
  identical to a full pass. A job marker on a token-stable session still reaches `jobs
  create`, and an outcome that is still pending is never cached. Set
  `REVENIUM_REPORTER_MEMO=disabled` to turn the caches off; deleting either file just costs
  one full pass.
- `tool-event-report.sh` reads every spool file in one `python3` pass instead of one per file.
  Each per-file pass re-read the whole TOOL ledger to build its pre-filter, so 676 spool files
  against a 3.2 MB ledger took 55s of every tick; it now takes about 1s. Rows, order and the
  per-row ledger guard are unchanged, and a malformed line still ends only its own file.
- `FAILED` and `CANCELLED` job outcomes now send `--outcome-type UNSUCCESSFUL`. They
  previously sent no outcome type, so Revenium left every failed or cancelled job's Outcome
  Type at `PENDING` indefinitely. `SUCCESS` still sends `CONVERTED`, and the value flags
  stay `SUCCESS`-only.
- A `CANCELLED` job outcome that is not a guardrail halt now explains itself. It ships a
  fixed `failure_reason` (the arc ended without checkable evidence of success or failure, so
  it was reported as `CANCELLED` by default) and `outcome_basis: undetermined` in
  `--metadata`, because an uncertain arc and a halted one were otherwise indistinguishable on
  the wire. A halt cancellation (`guardrail-halt-*` id, job type `interrupted`) ships exactly
  as before, and the classifier's rule to use `CANCELLED` when uncertain is unchanged. The
  reason rides in `--metadata` until a CLI release exposes the server's `outcomeReason`
  field (V2-13).

- A classification now ships one completion, not two. The classifier writes every
  classification as a `GUARDRAIL` marker followed by a `CHAT` marker, and the reporter
  equal-split the session delta across both: two half-cost rows that each carried the full
  session `--request-duration`, which the Revenium trace timeline showed as two near-identical
  rows (one ent trace: two $0.070 / 1.11 min rows for one 49,796-token session). The reporter
  now folds an adjacent, both-unreported `GUARDRAIL`+`CHAT` pair that agree on session,
  task type, trace, job and agent into the `CHAT` marker and ships one `--operation-type CHAT`
  completion carrying the whole delta. The `CHAT` type matches what the event path and the
  markerless path already ship. Nothing in the skill reads a `GUARDRAIL` row back from
  Revenium: budget-rule filters scope on agent, model, provider, organization, credential,
  product, subscriber and task type, never operation type, and the per-field token and cost
  sums are unchanged, so budget counters and halts behave as before. A dashboard you built
  yourself on `operationType = GUARDRAIL` will stop receiving new rows. Idempotency is
  preserved: the absorbed `GUARDRAIL` muid is ledgered by the same call (its own line, before
  the shipped muid's), so it is never reported again, and a session already half-reported
  under the old scheme finishes correctly (a `CHAT` whose `GUARDRAIL` twin is already
  ledgered ships alone; a `GUARDRAIL` whose `CHAT` twin is already ledgered ships alone as
  `CHAT`). A `GUARDRAIL` marker with no `CHAT` twin passes through unchanged. The S2
  `window=` figure counts classifications, so it reads half what it used to for the same
  session. No change to the classifier or its markers.

- The later turns of a classified session now carry its latest task type and its job. The
  classifier labels a session once, so after that first pair was reported every later delta
  shipped `--task-type unclassified` with no `--agentic-job-id` (one ent session: a single
  marked row at 480,675 tokens, then five unclassified rows to 515,535). Job cost was
  understated, job ROI inflated and task analytics lost the label. A later delta of a session
  that has classification markers now ships with that session's latest one (its task type,
  `CHAT`, its trace) and the job the reporter would link for it: a root's own latest job, a
  subagent's root job. A `guardrail-halt-*` job is never the link. Accepted bias: an unrelated
  later turn is charged to the earlier job, which understates that job's ROI rather than
  overstating it. A job is linked only while it is live: its `jobs create` is ledgered, and it
  is open or its outcome was reported recently enough: within
  `REVENIUM_OPEN_SESSION_MAX_IDLE_SECONDS` (one day) while the row's session is still open,
  within `REVENIUM_JOBS_STALE_SECONDS` (600 seconds) once it has ended. A live check on
  2026-10-18 showed Revenium adds a completion linked 13 minutes after the outcome to the
  closed job's cost without reopening or duplicating it; the nameless pending rows an earlier
  replay produced were links to jobs Revenium had never been told about, which the
  ledgered-create check refuses. On one ent profile the open-session window links about 69% of
  later-turn tokens, against 7.5% for 600 seconds alone. Beyond the window, for a guardrail-halt
  job and for a job that was never created, the row ships unlinked and the task type still
  carries; the log says why, once per job (`Carried completion shipping WITHOUT
  --agentic-job-id`). The window is decided in one function (`_carry_link_window`). Transaction ids and ledger lines keep their shape
  (`<session>-<total>` and an `unclassified-<digits>` muid, which now means that no marker
  muid was consumed), so re-running the cron never double-reports. A session with no
  classification at all meters exactly as before. Rows already shipped are unchanged, with no
  backfill. No change to the classifier or its markers.

### Added

- `llmOutcomeEvaluation.reportModelEstimates` lets an install report the `llm` evaluator's
  estimates (`MODEL_ESTIMATED`) to Revenium. The evidence-class gate added in v1.8
  withheld every model estimate's value with no way to turn that off, so an install without
  rate cards, revenue cards or confirmations could never send a job value. The key must be
  a literal `true` and works only with `experimentalReportEstimates: true`; when it is off, nothing
  changes. `revenium jobs roi` shows a reported estimate with the same weight as a
  measurement. See [Reporting the estimate's value](skills/revenium/references/config-schema.md#reporting-the-estimates-value-egv-18).
- `REVENIUM_MODEL_ALIASES` maps a gateway's model alias (e.g. LiteLLM's `model-default`) to
  the model it serves, so completions metered behind a gateway carry a model and provider
  Revenium can price. See [Configuration](docs/configuration.md#model-aliases).

- Traces are named. Every Revenium trace read "Unnamed trace" because the reporter never sent
  `--trace-name`. It now sends the title Hermes gave the trace's root session; with no title
  (or a Hermes without the column), the root's latest job name (a guardrail-halt job never
  counts), else its first task type. The title comes first because Revenium names a trace
  from the first row that carries a name, and the title exists within a second of the
  session starting while the classifier's markers land minutes later: on ent a root's first
  six rows shipped before its markers and the trace stayed unnamed. Sent on main-loop,
  markerless, subagent and
  auxiliary rows alike, so every row in a trace carries the same name. A trace with nothing
  to name it by sends none. Sent only when the installed `revenium` CLI advertises the flag
  (probed with `supports_flag`, independent of `--trace-type`); an older CLI meters exactly
  as before. The event path (`api-event-report.sh`) names its traces the same way.
- The trace dependency graph is connected. Nothing sent `--parent-transaction-id`, so every
  auxiliary and subagent row was an orphan node. An auxiliary row now links to the main-loop
  transaction its own session most recently shipped (its root's, for an auxiliary-only
  session), and a subagent's completion to its root's most recent one. The id is rebuilt from
  the ledger, so it names a transaction Revenium already accepted. A subagent is visited
  before its root, so on the first tick that sees both the child ships unlinked rather than
  waiting: a missing edge is cosmetic and holding the completion would delay budget
  visibility. Sent only when the CLI advertises the flag; neither new flag enters a
  transaction id, a ledger key or the reporter memo. The event path does not send
  `--parent-transaction-id`: its rows are per API call with no session-level anchor to link
  to, and a guessed edge would be worse than none.

### Fixed

- A job's Value was occasionally missing in Revenium because the outcome evaluator's answer
  left out `confidence` (2 of 98 jobs over 14 days on the reference host). The validator
  rejected the answer and nothing asked again, so the miss was permanent. The classifier now
  asks the evaluator once more with the same prompt. A valid second answer is used; anything
  else keeps today's record. No completion budget changed, no confidence is defaulted or
  inferred, and an answer that carries a confidence is handled exactly as before. The cost is
  at most one extra evaluator call, only for those answers. Existing installs need the updated
  classifier plugin: re-run `install.sh` from a fresh clone, or `install-plugin.sh` per profile.
- A subagent's spend now ships linked to its root session's job instead of unlinked. A subagent
  is classified, and becomes ready to meter, when its own turn ends, which is well before its
  root session's turn ends and the root's job marker (the only source of the job id) is
  written. The reporter had nothing to link, so it shipped the completion with no
  `--agentic-job-id`, and a shipped completion cannot be linked to a job afterwards. On ent,
  82% of subagent tokens since the classifier stabilised (9.06M of 11.01M; 35% of the whole
  history) shipped this way, so job cost omitted most delegated work and job ROI was inflated.
  The reporter now holds a subagent while its root session is still running, has no job
  record and has not reached a session boundary, bounded by the same
  `REVENIUM_UNCLASSIFIED_MAX_HOLD_SECONDS` (default 7200, counted from the root's start; `0`
  disables it), and ships it once the root's job exists. A pair marker on the root does not
  release it, because on a long root the pair can land mid-turn and the job twenty minutes
  later. The trade-off: a subagent's spend reaches Revenium, and budget rules, when its root's
  job marker lands rather than when the subagent ends (replayed on ent: median 10 minutes,
  p90 20, at most 27 since 2026-10-10; with the 7200s cap, 84.8% of all leaked tokens recovered,
  p99 57 minutes). The root's own spend is already held to the same moment. Installs without
  the plugin, roots that go idle, finish without a job or pass the cap, and Hermes versions
  without `parent_session_id` keep today's timing. Auxiliary rows and rows already shipped are
  unchanged.
- A session whose first turn runs past the settle window is no longer metered before its
  classifier marker lands. The settle fallback measured age from `started_at`, so a turn
  longer than 600 seconds (typically a Hermes cron job) was treated as having no classifier
  while it was still running, and each tick shipped its growing delta as `unclassified` with
  no `--agentic-job-id`. Only the last delta reached the job, which made its cost a few cents
  and its ROI absurd (on ent, `reconcile_slack_gmail_todos_e00c` showed 1,713,686% with 2,306
  of 219,680 tokens linked; 15.4% of classified-session tokens shipped this way). The reporter
  now holds a live, markerless session while a healthy classifier is registered, bounded by
  the new `REVENIUM_UNCLASSIFIED_MAX_HOLD_SECONDS` (default 7200; `0` disables the hold). The
  trade-off: a long first turn's spend reaches Revenium, and budget rules, when the turn ends
  or the cap passes rather than minute by minute. Installs without the plugin keep today's
  timing. Rows already shipped stay unlinked.
- The economics contract the outcome-metrics stage declares for a job type with none no longer
  carries a monetization rule. The 1.0 USD per-unit rate made Revenium compute every job's
  Value as rate x units = $1.00, ignoring the reported `outcomeValue` and skewing ROI (on ent,
  removing it from the `research` contract made job `ai_agent_cost_announcements_f6eb` show
  $95.62). The four metrics, `unitMetricKey` and `unitLabel` are unchanged, and validation of
  existing contracts never required monetization. Forward only: contracts declared by older
  versions keep the $1 rate, because the skill only creates absent contracts. Re-set each with
  `revenium jobs types economics set <type> --file <doc-without-monetization> --yes`, a
  whole-document replace.
- A classification now yields one job, not one per arc the model reported. The reporter
  attributes a completion to the first job marker after its task marker, and a session's one
  classification is written before any job, so every completion bound to job #1 and any
  further job owned nothing: Revenium showed it with "No traces found for this job", no total
  cost and no value (one ent session wrote a CANCELLED scan job and a SUCCESS skill-update job
  from a single classification; the second never had a trace). The classifier now keeps the
  first valid job's id, type and failure reason and names the other arcs in its job name
  (`Scan X (also: Update the radar skill)`, at most 120 serialized bytes, trailing names
  dropped whole). Its status is the first arc's: a sibling that was not a clear `SUCCESS`
  does not demote it, and a sibling's `SUCCESS` never promotes a `CANCELLED` or `FAILED`
  first arc. This also stops the sibling's separate evaluator call, which had nothing of its
  own to value. It applies to the
  built-in model path and to a registered classification implementation alike. A single-arc
  verdict is untouched. Forward only: a session already written with several jobs keeps them
  (its `CANCELLED` jobs are still re-judged), and the reporter still creates a Revenium job for
  every job marker in a file. The re-judge prompt now shows a job name up to 120 bytes rather
  than 80, so a folded name is not cut mid-word.
- A job is no longer written `CANCELLED` for work that finished, and a re-judge that finds
  nothing is no longer silent (diagnosed on the `ent` profile, 2026-10-14: a one-shot run that
  finished a research task and a writing task shipped its one folded job `CANCELLED`, with no
  value, and the log held no re-judge line). The session-end hooks were not at fault: both
  `on_session_end` and `on_session_finalize` ran in that session and each made the re-judge's
  model call, but a re-judge that moved nothing logged nothing, so that looked like neither
  having run. Three changes. The job-inference prompt cut the transcript with
  `transcript[:6000]`, so a transcript over 6000 characters lost its last stretch, the final
  answer included (7958 characters in the incident, its 977-character answer gone), and the
  model, whose uncertain verdict is `CANCELLED`, said so; on that host 186 of 271 long
  sessions were `CANCELLED` at first pass against 10 of 28 short ones. The prompt now keeps
  the head and the tail, as the re-judge already did (a transcript within 6000 characters is
  untouched). A folded job no longer drops to `CANCELLED` because another arc was not a clear
  `SUCCESS`: it keeps the first arc's status, and the re-judge prompt says a folded job's
  status is its main goal's. And every re-judge now logs
  `job re-judge for sid=... checked N job(s), verdicts: ...`; an answer with no usable
  verdict logs a warning carrying the model's escaped, shortened words; the fold line lists
  the per-arc statuses. A `CANCELLED` outcome already shipped is still final.
- A session is no longer labelled `unclassified` for good because the task-label model call
  failed once (`ent`, 2026-10-14, session `20261014_165924_2f9664`: the provider's stream
  produced nothing for 10 seconds, Hermes' retries hit a connection error, and the session's
  completion shipped `task_type=unclassified` while the job call seven seconds later
  succeeded; 5 of ~258 sessions on that host in two weeks). A failed call (an exception or a
  timeout) now writes no marker and skips job inference for that trigger, so the next one (a
  later turn, `on_session_end`, `on_session_finalize`) classifies the session and infers its
  job together; a job written without a task marker above it would own no completion. A
  label the model answered but the validator rejects still writes `unclassified` once, and a
  session no trigger can classify still ships as `unclassified`. The label call's timeout
  rises from 10 to 20 seconds, the job call's budget.
  The session-end hooks hold the reporter's `.ready` sentinel back after such a failure, so a
  cron tick between `on_session_end` and `on_session_finalize` cannot ship the session before
  the retry; a second failure releases it, and the settle window still releases a session
  that no hook does.
- The reporter writes a collapsed pair's ledger lines (the absorbed `GUARDRAIL` muid, then
  the shipped `CHAT` muid) in one append. Two appends could be split by a crash, leaving the
  absorbed muid newest, and a later subagent or auxiliary row would name a transaction that
  never went out as its `--parent-transaction-id`. Adjacent subagents of one root now share
  one parent lookup per tick instead of each starting `python3` to scan the ledger, and the
  transcript reader caps each message as it reads it rather than holding whole tool results.
- A job's final answer is no longer cut to 500 characters before the classifier judges it
  (`ent`, 2026-10-14, the same two-goal run after the fix above: the re-judge said `FAILED`,
  "only two announcements, and the second link is truncated", about an answer that had all
  three with full links). The transcript reader cut every message to 500 characters, so a
  result delivered in one longer message lost its end in every prompt that read it. The
  session's last assistant message now keeps up to 2500 characters; every other message
  stays at 500, and the prompt budgets are unchanged. The value evaluator's transcript is
  also clipped head and tail now, like the job and re-judge prompts, instead of head-only.
- The outcome-metrics stage no longer reports a brand-new job's transient 404 as a failure.
  The append call (and the economics `set`) now pass `--output json`. Without it the CLI
  printed its error as a coloured box rather than a JSON body, so the not-found and
  throttle checks never matched and the not-yet-queryable 404 logged `append failed` with
  `failed=1`. It now counts as `deferred`/`not_found` and retries next tick, as intended.
  Nothing was lost: every affected job appended on a later tick.
- `install-plugin.sh` no longer corrupts a `config.yaml` whose `plugins.enabled` items sit at
  the key's own indentation (`  enabled:` / `  - a`, PyYAML's default dump style). It
  inserted the plugin two spaces deeper. The file stopped parsing and Hermes refused to
  start on that profile. The new item now takes the existing items' indentation.
- Auxiliary usage no longer resurrects closed jobs. The first tick after an upgrade reports
  each session's accumulated auxiliary usage, and every row carried its session's
  `--agentic-job-id` whether or not that job was still live. Revenium creates a job for any
  id it has not seen, so 151 long-closed jobs reappeared as nameless `PENDING` rows. An
  auxiliary row now links to a job only when its create is in the jobs ledger and the job is
  open or closed within `REVENIUM_JOBS_STALE_SECONDS`. The spend is still reported, without
  the link. The aux ledger and transaction ids are unchanged.
- A subagent's completion no longer reaches Revenium before its root job exists. The session
  query visits a subagent before its root, so the completion carried the root's job id first;
  Revenium created the job with no name or type, and the root's later `jobs create` got a 409
  that was treated as success, losing both for good. The completion is now held, with nothing
  ledgered, until the create is confirmed. The hold ends after `REVENIUM_JOBS_STALE_SECONDS`,
  when the completion ships without the job link rather than strand the spend.
- A `CANCELLED` job outcome is no longer reported while its session is still open. The
  classifier uses `CANCELLED` as its "uncertain" verdict and writes it a couple of minutes
  into a session, so jobs were closed `UNSUCCESSFUL` while the work was still running. The
  outcome is now held until the session ends, or has been idle for
  `REVENIUM_OPEN_SESSION_MAX_IDLE_SECONDS` (default one day). `SUCCESS`, `FAILED` and the
  guardrail-halt cancel are reported as before. The held outcome is logged as
  `outcome held while session open: id=`.
- A job the classifier first judged `CANCELLED` is now re-judged, so a finished job can reach
  Revenium as `SUCCESS` with a value. The classifier infers a session's jobs once, mid-session,
  and `CANCELLED` is its "uncertain" verdict, so an arc whose work was still running (a
  subagent mid-flight) was latched `CANCELLED` for the life of the session. A `CANCELLED`
  arc is never evaluated, so it shipped with no job value. Every later trigger now re-checks
  a still-`CANCELLED` job against the transcript as it stands, at the cost of one status-only
  call per trigger however many jobs are open, and appends a new marker for the same job id
  when the status moves. `SUCCESS` and `FAILED` stay final, the guardrail-halt cancel is never
  re-judged, and a `SUCCESS` is evaluated exactly as a first-pass `SUCCESS` is. The
  reporter now reports the latest marker for a job id (by marker `ts`, a tie going to the
  later line), where it used to report and ledger the first. The re-judge marker updates the
  job's status only: task-marker ownership, in both reporters, still counts just the first
  marker per job id, so spend never moves between jobs. An operator correction in a job's
  sidecar is not superseded by the new estimate, including one filed while the evaluator is
  running (the check repeats under the sidecar lock at write time). A session with more than
  eight `CANCELLED` jobs re-checks a rotating window of eight per trigger. A `CANCELLED`
  outcome already ledgered before the re-judge lands is final, as every ledgered outcome is.
- The open-session hold no longer closes an active long session when `state.db` is locked
  during its column probe. A failed probe used to pin `started_at` as the idle clock for the
  rest of the run; a locked probe now defers, and only a probe that read the schema is
  remembered.

## [v1.8] — 2026-10-05

This release adds **subscriber attribution** for metered completions: a
namespaced subscriber key, resolved from the session's actor, is attached at all four
metered-completion sites once resolution succeeds, so spend attributes down to the
individual subscriber instead of stopping at agent or session granularity. Two
conditions must hold: the installed `revenium` CLI must accept `--subscriber-id` (an
older CLI meters exactly as before), and the session must resolve to a safe actor
identity. A completion with neither still ships, just without the key. Job records do
not carry a subscriber key in this release; attribution lives only on metered
completions this cycle. Two rounds of
work on the same experimental **job-value estimation**
feature also shipped here: the first added it, the second replaced most of its internals
so a model estimate can no longer read as an observed result. That feature stays
**opt-in and off by default** throughout, and an install that leaves it off meters
byte-identically to before. This release also carries auxiliary usage metering, which is
**on by default** and is a permanent increase in reported spend for unchanged traffic,
documented in [Auxiliary usage migration](docs/migration-auxiliary-usage.md).

### Documentation

- **[Job value and ROI](docs/value-and-roi.md)**: a dedicated reference for the whole
  experimental value path, replacing the fragments previously spread across the README,
  `docs/how-it-works.md`, `docs/configuration.md`, `references/config-schema.md` and
  `references/job-declaration.md`. It documents previously undocumented details: the evaluator call's own bounds,
  the eight-word abstention vocabulary,
  the full sidecar field inventory, the exact `--metadata` key order on the wire, the two
  truncation tiers, the correction record shape, the ledger lines and retention and pruning.
  It also includes a symptom-to-cause troubleshooting table. The pages it was extracted from keep their
  summaries and link to it.
- **[Cron and job cost reconciliation](docs/cron-and-job-cost-reconciliation.md)**:
  the Phase 65 diagnosis record for TRU-01 and TRU-02, documentation only; nothing under
  `skills/` changed. ([#141])

### Added — evidence grading and economic mechanisms

- **Nine evidence labels** (`evidence_class`), replacing the single forced constant.
  They do **not** form a confidence ranking: customer confirmation can be
  commercially authoritative yet causally weak. Observation proves that something
  happened rather than what produced it, while configuration establishes an approved rate
  rather than hours actually spent. The LLM-only path always resolves to
  `MODEL_ESTIMATED_DEMO` and **cannot** promote itself to any observed,
  customer-confirmed, associational or impact label. This is enforced structurally and proven
  by adversarial fixtures rather than asserted. Exact spellings and the resolution rule
  are in [`references/job-declaration.md`](skills/revenium/references/job-declaration.md).
- **Six economic mechanisms** (`economic_mechanism`) in place of the previous
  hours-times-rate assumption: labor substitution, augmentation or capacity expansion,
  quality or decision improvement, risk avoidance, newly enabled work and incremental
  revenue. The evaluator may select three of them; the other three are operator-declared
  (see Known limitations).
- **Net value across supplied costs** (`net_value`). A new `costs` config block, keyed by
  job type, subtracts `human_review`, `rework_or_error`, `handoff` and
  `training_or_change` from the estimated value. A supplied `0` and an absent category are
  different things and both are explicit in the record. There is no fleet-wide default;
  an unconfigured job type nets nothing.
- **Explicit zero and unknown denominators.** AI cost is never silently substituted when
  the claim concerns total workflow investment; no ratio is emitted.
- **Double-counting controls** (`double_counting_group`) so one outcome cannot be fully
  credited to several jobs, or claimed twice across overlapping mechanisms.
- **Zero and negative work stays visible.** Failed, cancelled, abandoned and unclassified
  jobs receive no positive value by default while retaining their metered and allocated
  cost, so negative net value remains legible instead of disappearing.
- **Bounded low/base/high estimates** in preference to false precision. Reversed or
  unordered bounds abstain rather than guess.

### Added — persistence, corrections, and provenance

- **A sidecar assessment record** under `${STATE_DIR}/job-assessments/`, keyed by job id.
  The richer assessment no longer competes for the 1024-byte marker line, which a
  six-field assessment had already filled to about 70%.
- **Append-only corrections.** `correct-assessment.sh` writes a `kind:"correction"` line
  locally and calls `revenium jobs outcome-update` server-side. The original assessment is
  preserved; nothing is destructively replaced. Operator-only, never run from cron.
- **Provenance that survives deferral and retry.** Model, prompt, taxonomy, policy and
  schema versions persist through a failed job creation and its retry, so a later
  taxonomy or prompt change never silently rewrites history.
- **The deciding model is recorded** separately from `evaluator`/`evaluator_version`,
  which identify the implementation rather than the model that produced the estimate.
- **`studyId` / `studyVersion`** config keys let an install name an impact study its
  assessments reference. Referencing a study never changes an assessment's own
  `evidence_class`.

### Added — boundaries, reporting, and privacy

- **Six pluggable boundaries as real contracts**: classification, output/outcome
  assessment, economic valuation, evidence resolution and reportability, cohort impact
  (contract only) and Revenium reporting, selected through a `boundaries` config object.
  A non-LLM implementation can be added behind any of them without masquerading as an LLM
  evaluator. The contracts are host-agnostic, so the core can later be extracted.
- **`ImpactStudyResult` as a contract only**: fields for study identity, estimand,
  identification method, effect interval, assumptions and validity scope. No estimators
  and no experiment orchestration ship here.
- **`experimentalReportEstimates`**, a second literal-boolean gate independent of
  `enabled`. Left off, an estimate is computed and recorded locally but its value is
  withheld from Revenium; the outcome and provenance still report
  (`reportability_status: "candidate"`). Turned on, the value ships as well
  (`reportability_status: "reportable"`). The resolver decides this, never the evaluator.
- **A bounded `--metadata` envelope** with a byte ceiling, tier-ordered shedding and a
  `metadata_truncated` marker when a tier actually drops keys. An over-ceiling payload
  never ships unmarked, and base metering never breaks on a field the API does not know.
- **Inference-locality provenance.** A derived address class and provider are recorded;
  the raw `base_url` is consumed and discarded, never persisted or transmitted. The docs
  state that this records where inference was **configured** to go, not where data
  stayed.
- **No raw prompt or transcript text** reaches any marker, ledger, queue, log or
  `--metadata` field, proven by a dynamically enumerated canary sweep whose
  vacuous-pass guard is itself proven binding by a negative control.

### Added — declaration authority and the evidence-class precedence rule

- **One cross-boundary precedence rule for `evidence_class`.** A configured boundary's
  registration-time declaration now reaches the persisted record, resolved by a single
  function (`_evidence_class_precedence`) that both record sites call. This defines one rule,
  not one per boundary. It walks four boundaries in fixed priority order: evidence,
  valuation, classification, evaluator.
- **A declaration must be non-forced to affect resolution, not merely non-empty.** The
  built-in default registrant on every boundary declares the same constant the LLM-only
  path already forces (`MODEL_ESTIMATED_DEMO`), so a literal first-non-empty walk would
  have stopped at the highest-priority boundary on 100% of installs and masked every
  lower one. A declaration equal to that constant is therefore indistinguishable from
  no declaration and does not affect resolution. All four fixture-declared classes are reachable as a result:
  `CUSTOMER_CONFIRMED`, `CUSTOMER_CONFIGURED`, `ACTIVITY_MEASURED`, `OUTCOME_OBSERVED`.
- **`evidence_class_authority`**, a new provenance-family `--metadata` key naming *which*
  boundary determined the class: `evidence`, `valuation`, `classification` or
  `evaluator`. With three-plus boundaries in the walk, the record must identify
  which declaration determined the class. Conditional-emit as usual: absent from the
  record means absent from the envelope, and a value outside the four-word enum is not
  forwarded. A `kind:"correction"` record carries neither this key nor `evidence_class`,
  because an operator override does not re-run the walk and so has no authority to name.
- **The causal-impact labels stay unobtainable from configuration.**
  `_DECLARABLE_EVIDENCE_CLASSES` narrows what a registrant may declare to six labels,
  excluding `ASSOCIATIONAL`, `QUASI_EXPERIMENTAL_IMPACT` and `EXPERIMENTAL_IMPACT`; a
  config-installed boundary cannot mark a record with a causal-impact label that no
  experiment backs, even from trusted code.
- **Boundary lookups are scoped to the profile that owns the session.** In multiplexed
  mode each profile has its own `config.json` and therefore its own `boundaries` object;
  the record-site lookups now thread per-session paths, so a persisted `evidence_class`
  and its authority name the boundary that actually applied to *that* profile's job. This
  also closes the same latent defect on the pre-existing valuation and reportability
  lookups.
- **The rule's replacement guarantee is checkable, not asserted.** The old DECL-03
  guarantee held structurally because the function took one parameter; the widened
  signature takes four, so an ast-walk guard now proves no parameter carries evaluator
  output and that no call-site argument derives from raw model output. Adversarial fixtures
  drive a hostile evaluator response through the real construction path (including one
  that names the walk's own parameters as attack keys) and the record is unchanged.
- **[Evidence-class precedence and declaration authority](docs/evidence-class-precedence.md)**
  records the implemented rule, the reachability amendment and a written verdict for each
  of the four pre-committed falsifiers.

### Added — documentation and guards

- **[Claim distinctions and evidence boundaries](docs/claim-distinctions-and-evidence-boundaries.md)**:
  output vs. outcome vs. valuation vs. impact vs. ROI, the results chain, the
  product-truth boundary, correction and audit behaviour, abstention and negative value
  and what this work deliberately does not ship.
- **A prohibited-claim-language guard** (`test_no_prohibited_claim_language_left`) using the
  same pattern as the existing legacy-name guards, scanning the whole shipped tree rather than
  Markdown alone, so an overreaching claim cannot ship in a code comment or a log string.
- **Two source-derived documentation guards** pinning the documented envelope key
  inventory and byte ceiling to the reporter's live constants, so the docs cannot drift
  from the code.

### Known limitations

- `quality_decision_improvement`, `risk_avoidance` and `incremental_revenue` are
  representable and forward correctly on the wire, but nothing can currently select them:
  no config key or CLI flag selects them and `correct-assessment.sh` does not set a mechanism. A
  study reference is the intended producer.
- When a configured `boundaries.valuation` or `boundaries.evidence` implementation
  declares its own `evidence_class`, the persisted record still shows the evaluator's
  class. The effect is conservative (`MODEL_ESTIMATED_DEMO` is the weakest label, so the
  record under-claims) and no promotion path is opened. Resolving it needs a
  cross-boundary precedence rule.
- `revenium jobs roi` shows no provenance, so the evidence label and assumptions are
  retained in the bounded metadata envelope and locally, not shown in that view. Use
  `revenium jobs outcome-history` to read them back.
- This round has not been exercised against a live tenant. The end-to-end proof is a
  fixture harness driving the real classifier and reporter with a stubbed model response.
- Whether a Revenium-side guardrail counter actually increases for an ingested auxiliary
  row inside a rule's scope is **not demonstrated by this release**; the proof shipped
  here establishes that an auxiliary row is emitted carrying the same session-resolved
  dimensions as its session's main-loop completion; the server-side counting half remains
  to be confirmed separately against a live tenant.

### Added — auxiliary usage metering

- **Auxiliary LLM calls are now metered.** `hermes-report.sh` gained
  `report_auxiliary_usage`, a post-loop pass reading Hermes' `session_model_usage` table
  read-only, shipping each non-empty-`task` row as its own `revenium meter completion`
  with `--operation-type AUX` and a `--task-type` from a fixed six-label `aux_*`
  vocabulary (`aux_approval`, `aux_title_generation`, `aux_compression`, `aux_vision`,
  `aux_web_extract`, `aux_session_search`). Compression, title generation, approval,
  vision, web extraction and session search were previously reported nowhere. **Not a
  new cron stage; the cron still runs six.**
- **On by default, with an off switch.** `REVENIUM_AUX_METERING=disabled` in the state env
  file, or `auxMetering: "disabled"` in `config.json` (env wins), ships no auxiliary rows
  and writes no auxiliary ledger; main-loop metering is then byte-identical to before. An
  install whose Hermes build has no `session_model_usage` table is byte-identical by
  construction and needs no setting.
- **A permanent increase in reported spend for unchanged traffic**, measured
  fleet-wide at 0.4598% of cost, with the near-zero-denominator outlier caveat, the
  re-runnable sizing SQL and the guardrail implications in
  [Auxiliary usage migration](docs/migration-auxiliary-usage.md).
- **The first tick after upgrading is a one-time historical catch-up**: the counters are
  cumulative and `revenium-aux.ledger` starts empty, so that tick reports each identity's
  whole accumulated pre-upgrade auxiliary usage into the current guardrail window.
  The reporter warns about this deliberate behavior once per install.
- **A fourth ledger**, `revenium-aux.ledger`, with its own key domain and per-column
  cumulative subtraction. Like the other three it is never pruned automatically.
- **An unrecognised `session_model_usage.task` value ships as `aux_unclassified`** rather
  than being dropped, with one warn per distinct value per install, so a future upstream
  addition never silently loses spend.
- **`billing_provider` of the literal `auto` is now resolved through model-name
  inference** on both the main-loop and auxiliary emit paths, from one shared function.
  This is **global**: provider-scoped counting changes for main-loop rows too. Rows
  Revenium already ingested carrying `auto` are not back-filled.
- **`diagnose.sh` gained a read-only `10. AUXILIARY USAGE PASS` section** (`--tick`
  renumbered 10 to 11), reporting tunable resolution and its source, table presence,
  auxiliary-vs-mirror row and cost counts side by side, dominant task values, the
  `aux-taxonomy.json` label count and any fired `.aux-warn` sentinels.

### Added — LLM outcome evaluation (initial)
- Opt-in, off-by-default **LLM outcome evaluation** (`llmOutcomeEvaluation` in
  `config.json`): on a `SUCCESS` job arc, estimates the job's economic value via one
  bounded LLM call on the user's own provider. The result is an unverified model
  estimate; Revenium combines it with metered cost into the displayed ROI. Fails
  closed: a missing or malformed config metres exactly as before.
- The evaluation-outcome log taxonomy now distinguishes `invalid` and `timed-out` from
  `abstained`, in addition to the pre-existing `evaluated`, `deferred` and `reported`:
  six words in total, split across two log destinations (in-process on the
  `revenium_classifier` logger for four of them, the cron's `revenium-metering.log` for
  the other two).
- `diagnose.sh` section reporting, per profile, whether LLM outcome evaluation is
  enabled, which evaluator is selected and the two cron-side taxonomy counts.
- The pre-existing unbounded deferred/wedged job-outcome logger is now rate-limited to
  once per `(outcome_id, reason)`, with a per-tick backlog aggregate line when the
  count is non-zero.

### Added — subscriber attribution

- **Subscriber identity resolution.** A session's actor is resolved into a namespaced
  subscriber key, giving Revenium a stable identifier beneath agent and session that
  persists for the same subscriber across sessions. ([#135])
- **`--subscriber-id` carried to all four `meter completion` sites** (the per-marker
  split path, the markerless path, the event path and the auxiliary-usage pass), so no
  metered completion ships unattributed once resolution succeeds. Agentic job records
  (`jobs create` / `jobs outcome`) and tool events do not carry a subscriber key in this
  release; subscriber attribution is scoped to metered completions only. ([#136])
- **Email, obfuscation and name legibility** (SUB-06, SUB-09). The new
  `skills/revenium/scripts/subscriber-names.sh` resolves subscriber-facing names, legible
  where an operator allows it and obfuscated where they don't, documented in
  [Subscriber attribution](docs/subscriber-attribution.md). ([#137])
- **Live proof against a real tenant** (SUB-10). Subscriber resolution and attribution
  verified end to end on a live install, documented in
  [Subscriber live proof](docs/subscriber-live-proof.md). ([#138])

### Added — operator tooling

- **Hermes Kanban ticket-id attribution.** Metered completions carry `--ticket-id` when a
  ticket is active, capability-gated so an older `revenium` CLI is unaffected. ([#123])
- **Per-job outcome metrics**, appended from the assessment sidecars via the new
  `outcome-metrics-report.sh`. A `404` on the append is treated as a deferral rather than
  a failure, and the behaviour is documented for operators. ([#131], [#133], [#134])
- **`costs-status.sh`**: a read-only report of which classified job types have no
  configured cost. ([#109])
- **`inferred_role` is now constrained to the operator's own rate-card vocabulary**,
  rather than a model-chosen label the rate card cannot match. ([#140])
- **The `.ready` sentinel directory is pruned alongside marker files**, so marker garbage
  collection no longer leaves orphaned sentinels behind. ([#139])

### Fixed

- `--organization-name` is now capability-probed on the jobs path; an install running an
  older `revenium` CLI had been silently failing job creation in production. ([#124])
- `owning_job_id` now resolves on the event path, so root-session rows link to their job
  instead of showing a job cost of zero. ([#125])
- A completion is never attributed to a job that does not exist yet, closing a race where
  the event path could reach `jobs create`'s own in-flight window. ([#126])
- A warn sentinel is kept alive while its session can still re-warn, instead of expiring
  and letting the same rule re-fire within one session. ([#128])
- SKILL.md declared a `required_credential_files` path that could never resolve, which made
  the skill report `setup_needed` and caused Hermes' cron preflight to refuse any job
  attaching it as `[blocked_config:silent]`. This happened on every run. Hermes joins declared
  paths onto HERMES_HOME and does not expand `~`, so `~/.config/revenium/config.yaml`
  resolved to `~/.hermes/~/.config/...`; a containment guard then rejects anything outside
  HERMES_HOME by design. The scripts read the CLI config directly and never needed the
  mount, so the declaration is removed and a regression test pins the rule. ([#132])

### Changed

- Every tick's root session ids are now resolved in one process instead of one subprocess
  per session, a cron-tick performance improvement with no change to wire output. ([#129])

## [v1.7] — 2026-08-22

### Added
- Skill-usage attribution on metered completions, and on the event path, for `revenium`
  CLI 1.4.0. Capability-gated, so an older CLI is unaffected. ([#81], [#82])
- `LICENSE` (MIT), backing the `license: MIT` that `SKILL.md` had declared in frontmatter
  since the first commit. ([#83])
- `CONTRIBUTING.md`, issue and pull-request templates and a CI workflow running the test
  suite on every pull request. ([#83])
- `CHANGELOG.md`. ([#84])
- [`docs/plugin-interface.md`](docs/plugin-interface.md): what the Hermes plugin surface
  does, measured against a live install. Shipped code depends on it: `api_event_spool.py`
  parses the payload contract it records. ([#85])

### Changed
- `README.md` split from 646 lines into a landing page plus seven guides under
  [`docs/`](docs/), and corrected to say that the working parts are a plugin, three shell
  hooks and a cron; `SKILL.md` itself is only a halt-check backstop. ([#83], [#84])
- Multi-profile guidance corrected: upgrades must re-name profiles. The restart target is
  often not the gateway and `rsync --delete` is no longer suggested. ([#78])

### Removed
- The planning and engineering-evidence trees are no longer tracked. `.planning/` had been
  gitignored since v1.2, but 32 files were still committed; `docs/internal/` held nine
  more. ([#84])

### Fixed
- `plugin-status.sh` reported a false `firing` when a grace-window session masked a stall,
  and its remediation named the gateway on hosts where a desktop-app
  `--profile <name> serve` process owns the profile. ([#79])

## [v1.6] — 2026-08-21

Fixes the chain of silent failures that made a fresh install look successful while
classifying nothing.

### Added
- `diagnose.sh`: one read-only report covering every stage of the pipeline, ordered by how
  often each stage is the cause. ([#75], [#76])

### Fixed
- `bootstrap.sh` now ships in the skill bundle. `hermes skills install` delivers only the
  files `SKILL.md` names bundle-relative, so the documented post-install command pointed at
  a file that never arrived. ([#73])
- `install.sh` confirms the whole `revenium` CLI config on every interactive run, api-url
  included, with current values as defaults. A stale api-url used to survive unseen and
  appear later as an unexplained `HTTP 403`. ([#74])
- `plugin-status.sh` no longer reports a false all-clear on hosts whose sessions never
  end; it had not detected the outage it was meant to catch. ([#76])
- `guardrail-status.json` is scoped to this install's rules, and duplicate rule names no
  longer collapse two rules onto one ruleId. ([#76])
- `bootstrap.sh --update` refreshes an existing install instead of retaining whatever
  `scripts/` arrived the first time. ([#77])

## [v1.5] — 2026-08-20

A second metering path that reports what each API call actually used, rather than
apportioning a session's token delta across markers.

### Added
- Event-driven metering on the `post_api_request` hook. `api_event_spool.py` appends a
  19-key record per API call with no network, no LLM and no sqlite in the hot path;
  `api-event-report.sh` ships each as its own row, keyed on the provider's
  `api_request_id`. Defaults to shadow mode, shipping nothing, until switched to live.
- Durable, atomically-claimed session ownership records (`owners/<sid>`), which decide
  which path bills a session, with mode-aware takeover for the event-owned/mode-revert
  hazard.
- `drain-status.sh`: a staleness-aware drain gate with a per-session legacy carve-out, so
  profiles converge on their own after `REVENIUM_LEGACY_COMPLETIONS=disabled`.
- `prune-markers.sh` for marker garbage collection, and `resolve-markers-dir.py` for
  per-session state resolution under a multiplexed gateway.

### Fixed
- Under-billing: the legacy path could claim a session it would never bill.
- Classification now reaches gateway-served sessions, via `on_session_finalize` plus a
  guarded `post_llm_call`, so an ordinary prompt produces a classified job on its first
  completed turn. `on_session_end` alone never fired for them.

## [v1.4.1] — 2026-06-25

### Added
- `--trace-type` auto-populated with the root agentic-job type, pinned per-trace and
  capability-gated for `revenium` CLI ≥ 1.2.1, so an older CLI is unaffected.
- `install.sh`: a native one-command installer.

### Fixed
- Trailing task markers now bind to the nearest preceding job.
- Setup hardening: `--reconfigure` / `--interactive` re-run gates, idempotent budget rules
  and an `ensure_path` return-0 fix on fresh hosts.

## [v1.4] — 2026-05-29

Pushes the "one business outcome per arc" semantic through Hermes' `delegate_task()` chain,
so Revenium rolls delegated activity up under a single trace and job instead of fragmenting
it per child session.

### Added
- **Trace inheritance**: `hermes-report.sh` and `tool-event-report.sh` ship
  `--trace-id <root_sid>` for subagent sessions. Top-level sessions are unchanged from v1.3.
- **Job inheritance**: a subagent's `--agentic-job-id` is replaced with the root's job id.
  `jobs create` and `jobs outcome` are suppressed for subagents, leaving the root's ledger
  entry as the single create/outcome.
- **Marker inheritance**: `classifier.py` emits root identifiers in subagent markers.
- `scripts/get-root-session-id.py` and a `common.sh` wrapper, walking
  `state.db.sessions.parent_session_id` with a `max_depth=10` circular guard and failing
  open on a missing or locked database.
- Golden-argv compatibility fixtures pinning the wire shape of `meter completion`,
  `meter tool-event`, `jobs create` and `jobs outcome`.

## [v1.3.1] — 2026-05-28

### Fixed
- `setup-local.sh` preflight: refuses to install when the `revenium` CLI, `sqlite3` or
  `python3` is missing, exiting before touching anything rather than leaving a silently
  non-functional install.
- Scanner compatibility: substituted a variable for a literal config path in comments and
  prose, and collapsed verification snippets into `hooks-status.sh`. Runnable code
  unchanged; verdict `DANGEROUS → SAFE`.

### Documentation
- Rewrote the canonical install path; the prior identifiers were structurally broken for
  this skill.

## [v1.3] — 2026-05-28

Budget enforcement moved off polling `revenium alerts budget` and onto first-class
`revenium guardrails` budget rules, with two-stage warn/hard thresholds. There is no coexistence flag.
Every existing `alertId` install auto-migrates on the
first cron tick. The v1.0–v1.2 metering behavior remains unchanged.

### Added
- `guardrail-check.sh` replaces `budget-check.sh` as the second cron stage, writing per-rule
  `guardrail-status.json`.
- Two-stage warn/block enforcement in `pre_llm_call.sh` and `pre_tool_call.sh`. The warn
  band emits one rate-limited stderr line per (session, ruleId) and continues; the block band
  emits the verbatim halt directive naming the offending rule.
- `setup-guardrails.sh` as the single rule-creation entry point, with three modes,
  flock-guarded, defaulting to `--filter AGENT:IS:${REVENIUM_AGENT_NAME}` and
  `--group-by AGENT`.
- An enforcement-event audit trail embedded in the halt notification, degrading gracefully
  when the API call fails.
- Shadow mode honoured end to end: shadow rules are excluded from halt derivation, and each
  breach transition gets its own one-shot `[shadow]`-prefixed notification.
- `clear-halt.sh` became ruleId-aware: `--rule-id` clears one rule; bare clears all.

### Removed
- `budget-check.sh` and `budget-status.json`.

## [v1.2] — 2026-05-19

Every Hermes tool call is metered to Revenium.

### Added
- `post_tool_call.sh`: a fail-open hook capturing a 7-key JSONL record per tool call, with
  no network call in the agent's hot path.
- `tool-event-report.sh`: a cron stage shipping events through `revenium meter tool-event`,
  idempotent on `TOOL:<sid>:<tool_call_id>`.

## [v1.1] — 2026-05-18

Discrete task arcs are tracked as Revenium agentic jobs: each created, its AI transactions
linked and its outcome reported exactly once.

### Added
- An additive `kind:"job"` marker schema with a separate `revenium-jobs.ledger`.
- Cron-side `jobs create` with `--task-id` linkage and a fail-open CLI preflight.
- Cron-side `jobs outcome`, exactly-once, treating `HTTP 409` as success for idempotency.

## [v1.0] — 2026-05-14

Every metered completion carries a content-driven `--task-type` and `--operation-type`,
turning spend attribution from per-session totals into per-turn activity breakdowns.

### Added
- The marker contract and the cron-side split pipeline, with byte-exact conservation across
  a split and a 5-field ledger line per session.
- Wire enrichment with `--task-type` and `--operation-type`, across eight providers.
- Mechanical classification through a Hermes plugin, replacing the agent-side path.
- `prune-markers.sh`.

[Unreleased]: https://github.com/revenium/hermes-revenium/compare/v1.8...main
[v1.8]: https://github.com/revenium/hermes-revenium/compare/v1.7...v1.8
[v1.7]: https://github.com/revenium/hermes-revenium/compare/v1.6...v1.7
[v1.6]: https://github.com/revenium/hermes-revenium/compare/v1.5...v1.6
[v1.5]: https://github.com/revenium/hermes-revenium/compare/v1.4.1...v1.5
[v1.4.1]: https://github.com/revenium/hermes-revenium/compare/v1.4...v1.4.1
[v1.4]: https://github.com/revenium/hermes-revenium/compare/v1.3.1...v1.4
[v1.3.1]: https://github.com/revenium/hermes-revenium/compare/v1.3...v1.3.1
[v1.3]: https://github.com/revenium/hermes-revenium/compare/v1.2...v1.3
[v1.2]: https://github.com/revenium/hermes-revenium/compare/v1.1...v1.2
[v1.1]: https://github.com/revenium/hermes-revenium/compare/v1.0...v1.1
[v1.0]: https://github.com/revenium/hermes-revenium/releases/tag/v1.0
[#73]: https://github.com/revenium/hermes-revenium/pull/73
[#74]: https://github.com/revenium/hermes-revenium/pull/74
[#75]: https://github.com/revenium/hermes-revenium/pull/75
[#76]: https://github.com/revenium/hermes-revenium/pull/76
[#77]: https://github.com/revenium/hermes-revenium/pull/77
[#78]: https://github.com/revenium/hermes-revenium/pull/78
[#79]: https://github.com/revenium/hermes-revenium/pull/79
[#81]: https://github.com/revenium/hermes-revenium/pull/81
[#82]: https://github.com/revenium/hermes-revenium/pull/82
[#83]: https://github.com/revenium/hermes-revenium/pull/83
[#84]: https://github.com/revenium/hermes-revenium/pull/84
[#85]: https://github.com/revenium/hermes-revenium/pull/85
[#109]: https://github.com/revenium/hermes-revenium/pull/109
[#123]: https://github.com/revenium/hermes-revenium/pull/123
[#124]: https://github.com/revenium/hermes-revenium/pull/124
[#125]: https://github.com/revenium/hermes-revenium/pull/125
[#126]: https://github.com/revenium/hermes-revenium/pull/126
[#128]: https://github.com/revenium/hermes-revenium/pull/128
[#129]: https://github.com/revenium/hermes-revenium/pull/129
[#131]: https://github.com/revenium/hermes-revenium/pull/131
[#132]: https://github.com/revenium/hermes-revenium/pull/132
[#133]: https://github.com/revenium/hermes-revenium/pull/133
[#134]: https://github.com/revenium/hermes-revenium/pull/134
[#135]: https://github.com/revenium/hermes-revenium/pull/135
[#136]: https://github.com/revenium/hermes-revenium/pull/136
[#137]: https://github.com/revenium/hermes-revenium/pull/137
[#138]: https://github.com/revenium/hermes-revenium/pull/138
[#139]: https://github.com/revenium/hermes-revenium/pull/139
[#140]: https://github.com/revenium/hermes-revenium/pull/140
[#141]: https://github.com/revenium/hermes-revenium/pull/141
