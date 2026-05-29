# v1.x Top-Level Wire Compat Fixtures

The four `*.golden.json` files in this directory capture the byte-exact
argv shape that `skills/revenium/scripts/hermes-report.sh` and
`skills/revenium/scripts/tool-event-report.sh` ship to the `revenium`
CLI for **top-level sessions** (sessions with NO `parent_session_id`
chain in `~/.hermes/state.db`). They pin the v1.3 wire contract for
the entire v1.x release line.

## The four fixtures

- **meter-completion.golden.json** — `revenium meter completion` argv;
  loaded by `tests/test_compat_meter_completion.py`; pins the
  per-marker happy-path argv including `--trace-id`, `--task-type`,
  `--agentic-job-id`, `--transaction-id`, and provider routing.
- **jobs-create.golden.json** — `revenium jobs create` argv;
  loaded by `tests/test_compat_jobs_create.py`; pins the
  job-marker-driven create call including `--name`, `--type`, and
  `--environment` routing.
- **jobs-outcome.golden.json** — `revenium jobs outcome` argv (SUCCESS
  path); loaded by `tests/test_compat_jobs_outcome.py`; pins the
  positional `<agentic-job-id>` plus outcome flags.
- **meter-tool-event.golden.json** — `revenium meter tool-event` argv;
  loaded by `tests/test_compat_meter_tool_event.py`; pins the
  success-path bare `--success` flag and the absence of
  `--error-message`.

## Immutability contract

These fixtures are **IMMUTABLE** across the v1.x line (v1.0 through
v1.x). Any modification is a wire-shape change that would break
downstream Revenium analytics consumers depending on the v1.x argv
contract.

The contract is enforced two ways:

1. The four underlying runners
   (`tests/test_compat_meter_completion.py`,
   `tests/test_compat_jobs_create.py`,
   `tests/test_compat_jobs_outcome.py`,
   `tests/test_compat_meter_tool_event.py`) each load the matching
   golden JSON and assert byte-equality against captured argv.
2. The Phase 23 umbrella test
   `tests/test_compat_v1_4_meta.py::TestV14CompatMeta::test_v1_4_top_level_wire_is_byte_identical_to_v1_3`
   runs all four runners as a single `unittest.TestSuite` so the
   v1.4 milestone-level acceptance gate is a single grep-able PASS/FAIL
   identifier.

If a future phase needs to change the wire shape (e.g. add a new
field): create a NEW sibling fixture (e.g.
`meter-completion.v2.golden.json`), add a NEW sibling test class (e.g.
`tests/test_compat_v2_meter_completion.py`), and bump the skill's major
version to v2.0. **Silent edits to the existing v1.x fixtures are
PROHIBITED** and will be caught by the v1.4 meta umbrella.

## Originating decisions

The fixture design was locked in during Phase 20:

- **Phase 20 D-01** — golden-argv unit test pattern.
- **Phase 20 D-02** — reconstruct fixture from script source (the
  fixture is derived from a precise pointer into
  `hermes-report.sh` / `tool-event-report.sh`, not from a live
  observation).
- **Phase 20 D-03** — one canonical happy-path golden per verb.
- **Phase 20 D-04** — `exact_match_fields` (literal allowlist) plus
  `pattern_fields` (regex-bounded variation, e.g. ISO timestamps) plus
  `forbidden_fields` (denylist for accidental v1.0/v1.1 budget-id
  leaks).

Phase 23 D-01 elevates the four-runner side-effect into the explicit
v1.4 milestone gate by adding the umbrella test and this README.

## How a fixture maps to the wire

Each golden JSON file pins:

- **`exact_match_fields`** — literal flag-to-value pairs the captured
  argv MUST contain (e.g. `--trace-id` = the session id).
- **`pattern_fields`** — flags whose values vary across runs but
  match a regex (e.g. ISO-8601 `--started-at`).
- **`forbidden_fields`** — flags whose presence in the captured argv
  would indicate a v1.0/v1.1 regression and so MUST be absent.

The assertion machinery lives in
`tests/_compat_helpers.py::assert_argv_matches_golden` along with the
no-shift `revenium` shim builder (`build_shim`) that captures argv
without losing token boundaries.

## v1.4 subagent inheritance — orthogonal to top-level compat

v1.4 (Phases 21-23) adds subagent `--trace-id` + `--agentic-job-id`
inheritance for sessions that DO have a `parent_session_id` chain.
That wire-shape is necessarily different from the top-level shape the
fixtures here pin, and is asserted by separate behavioral tests in
`tests/test_repository.py` (e.g.
`test_hermes_report_subagent_trace_inheritance` and its three
siblings). The fixtures in this directory cover ONLY top-level
sessions and remain unchanged across the v1.4 milestone.
