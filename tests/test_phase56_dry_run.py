"""Phase 56 Plan 01 (D-03, ROI-12/ROI-13): the local dry-run that gates the
live run.

Phase 53's live arm ran 85 genuine live sessions and produced zero
reportable/valued rows -- the misconfiguration (a `rateCard` nested as a
top-level sibling of `llmOutcomeEvaluation` instead of a child of it) was
only discovered by reading the code path directly, after the tenant had
already been spent on. This module is the rehearsal that would have caught
it before a single live token was spent: drive the exact configuration
shape the live host will carry through the REAL classifier valuation path
and the REAL `hermes-report.sh`, and prove -- locally, before touching the
tenant -- that a `revenueCard`-configured install produces a reportable
priced assessment whose value reaches the wire and whose auxiliary spend
ships attributed to the same job.

Fixture-fidelity rule this module obeys throughout (P7, this plan's own
kept prohibition): the assessment record the reporter consumes is ALWAYS
the one `_build_job_assessment` produced from a REAL `_validate_assessment`
call against a REAL config -- never a hand-authored dict standing in for
classifier output. A rehearsal that asserts against its own fixture proves
only that the fixture matches itself.

Two harnesses are joined here, each duplicated (not imported) per this
repo's established test-fixture-duplication convention (CLAUDE.md: test
fixtures do not share code with each other or with the producer):
  - the classifier-side loader/config-writer from
    tests/test_phase54_revenue_valuation_boundary.py
    (_load_classifier, _write_config, and the DerivationTests call sequence
    that turns a config into a priced assessment);
  - the reporter-side fixture/tick harness from
    tests/test_phase55_auxiliary_metering.py's _AuxMeteringTestCase,
    extended with the outcome-stage requirements from
    tests/test_compat_jobs_outcome.py (the job-assessments sidecar, the
    pre-seeded JOB:<id>:created: ledger line, and the task/job marker pair).

Task 1: DryRunReportableValuedRowTests (behaviours 1-4, the end-to-end
tracer plus the placement-trap guard) and DryRunToggleParityTests
(behaviour 5, the D-05 toggle's local twin).
Task 2: DryRunEdgeArmTests (E3/E5/E6/E7, the four probe edges this plan
owns).
"""
import json
import os
import shlex
import shutil
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

from tests._compat_helpers import (
    argv_to_flags,
    build_session_model_usage,
    build_shim,
    build_state_db,
    run_script,
    SCRIPTS_DIR,
)

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / 'skills' / 'revenium' / 'plugins' / 'revenium-classifier'
HERMES_REPORT_SH = ROOT / 'skills' / 'revenium' / 'scripts' / 'hermes-report.sh'
_HERMES_REPORT_SH_TEXT = HERMES_REPORT_SH.read_text()

SID = 'p56-dry-run-sid-001'
JOB_ID = 'p56-dry-run-job-001'
# A distinctive card key and distinctive gross/attribution so a mis-selected
# card, or a value that is actually the built-in hours*rate derivation, is
# immediately visible rather than coincidentally plausible.
CARD_KEY = 'dry-run-revenue-card-p56'
GROSS_PER_JOB = 733.0
ATTRIBUTION_FRACTION = 0.42
# The same expression the real registrant uses (round(gross * fraction, 2))
# -- computed once here so the raw fixture's zero-width value band (below)
# and every assertion against the produced record's estimated_value agree
# by construction, not by a second, possibly-drifting derivation.
EXPECTED_VALUE = round(GROSS_PER_JOB * ATTRIBUTION_FRACTION, 2)


def _load_classifier(env: "dict | None" = None):
    """Mirror of test_phase54_revenue_valuation_boundary.py's own
    _load_classifier, duplicated here for the same reason every other
    Phase 54+ test file's copy of it is (test fixtures do not share code
    with each other or with the producer). Loaded standalone (no package):
    classifier.py's own `from . import valuation` fallback then attempts a
    BARE `import valuation`, which only resolves when PLUGIN has been
    placed on sys.path (see _DryRunClassifierTestCase.setUpClass below)."""
    import importlib.util

    env = env or {}
    saved = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    try:
        spec = importlib.util.spec_from_file_location(
            'phase56_classifier_dry_run', str(PLUGIN / 'classifier.py'))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def _write_config(config_path: Path, boundaries=None, revenue_card=None,
                   revenue_card_key=None, experimental_report_estimates=None,
                   revenue_card_top_level=False):
    """D-03 config-shape builder, duplicated (not imported) from
    tests/test_phase54_revenue_valuation_boundary.py's own _write_config.

    Extended with `revenue_card_top_level` -- the ONE knob Task 1's
    placement-trap guard needs: True reproduces the exact Phase 53 host
    defect by nesting `revenueCard`/`revenueCardKey` as TOP-LEVEL siblings
    of `llmOutcomeEvaluation` instead of children of it. `boundaries` is
    ALWAYS top-level -- that placement rule never varies, in either arm.
    """
    cfg = {}
    if boundaries is not None:
        cfg['boundaries'] = boundaries
    outcome_eval = {}
    if experimental_report_estimates is not None:
        outcome_eval['experimentalReportEstimates'] = experimental_report_estimates
    if revenue_card_top_level:
        if revenue_card is not None:
            cfg['revenueCard'] = revenue_card
        if revenue_card_key is not None:
            cfg['revenueCardKey'] = revenue_card_key
    else:
        if revenue_card is not None:
            outcome_eval['revenueCard'] = revenue_card
        if revenue_card_key is not None:
            outcome_eval['revenueCardKey'] = revenue_card_key
    if outcome_eval:
        cfg['llmOutcomeEvaluation'] = outcome_eval
    config_path.write_text(json.dumps(cfg))


class _DryRunClassifierTestCase(unittest.TestCase):
    """Classifier-side sys.path + config-loading helpers, duplicated from
    test_phase54_revenue_valuation_boundary.py's
    _ValuationBoundaryTestCase. `_produce_record` is the one method every
    behaviour test in this module drives its assertions from -- it is the
    ONLY place a job-assessment record is constructed, and it always goes
    through the real `_validate_assessment` / `_build_job_assessment` pair
    (P7)."""

    @classmethod
    def setUpClass(cls):
        cls._path_added = str(PLUGIN) not in sys.path
        if cls._path_added:
            sys.path.insert(0, str(PLUGIN))

    @classmethod
    def tearDownClass(cls):
        if cls._path_added and str(PLUGIN) in sys.path:
            sys.path.remove(str(PLUGIN))

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='gsd-p56-01-dry-run-')
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.config_path = Path(self.tmp) / 'config.json'

    def _raw(self, **over):
        raw = {
            'economic_mechanism': 'labor_substitution',
            'inferred_role': 'senior_engineer',
            'estimated_hours_saved': 2.5,
            'assumed_loaded_rate': 150.0,
            'currency': 'USD',
            'basis': 'booking completed',
            'confidence': 0.5,
            # A zero-width band (the same shape
            # test_phase42_assessment_contract.py's own
            # _tracer_assessment_record docstring names: "one bound family
            # (a zero-width band)"). Supplying all three of
            # value_low/value_base/value_high pins the record's persisted
            # --outcome-value to EXACTLY the revenue card's own derived
            # amount, by construction -- not by coincidence with the
            # built-in +/-15% derived-bound spread the unsupplied path
            # would otherwise apply around it.
            'value_low': EXPECTED_VALUE,
            'value_base': EXPECTED_VALUE,
            'value_high': EXPECTED_VALUE,
        }
        raw.update(over)
        return raw

    def _load(self, revenue_card_top_level=False):
        _write_config(
            self.config_path,
            boundaries={'valuation': 'revenue_card_valuation_fixture'},
            revenue_card={CARD_KEY: {
                'grossPerJob': GROSS_PER_JOB,
                'attributionFraction': ATTRIBUTION_FRACTION,
                'attributionBasis': 'dry-run rehearsal fixture basis',
            }},
            revenue_card_key=CARD_KEY,
            experimental_report_estimates=True,
            revenue_card_top_level=revenue_card_top_level,
        )
        # Phase 54 (D-07) precedent, carried over unchanged: HERMES_HOME
        # must be pinned to this test's OWN tmp directory so
        # _revenue_profile_attribution_certain never picks up a real dev
        # host's unrelated ~/.hermes/profiles/ state.
        return _load_classifier({
            'REVENIUM_CONFIG_FILE': str(self.config_path),
            'HERMES_HOME': self.tmp,
        })

    def _produce_record(self, job_id=JOB_ID, revenue_card_top_level=False):
        """Drive the REAL valuation path end to end and return
        (module, record) -- P7: never a hand-authored stand-in for
        classifier output."""
        mod = self._load(revenue_card_top_level=revenue_card_top_level)
        cfg = mod._llm_evaluation_config()
        raw = self._raw()
        validated = mod._validate_assessment(raw, cfg, 'stub', 'v1')
        self.assertIsNotNone(
            validated, 'the revenue-card fixture must validate this raw assessment')
        valid_job = {
            'agentic_job_id': job_id, 'job_type': 'booking_completion',
            'status': 'SUCCESS',
        }
        record = mod._build_job_assessment(valid_job, validated, raw, cfg, 'stub', 'v1')
        self.assertIsNotNone(
            record,
            '_build_job_assessment must not abstain for a configured revenue card')
        return mod, record


class _DryRunReporterMixin:
    """Reporter-side fixture/tick harness. Extends the shape
    tests/test_phase55_auxiliary_metering.py's _AuxMeteringTestCase
    establishes (duplicated, not imported, per this repo's convention)
    with the outcome-stage requirements from
    tests/test_compat_jobs_outcome.py: the job-assessments sidecar
    directory, a pre-seeded JOB:<id>:created: ledger line (the OUTCOME-04
    gate, without which the outcome stage defers and no value ever reaches
    argv), and a task_marker + job_marker pair whose status is SUCCESS."""

    def _build_dry_run_tree(self, sid, job_id, record, aux_rows=None):
        tmpdir = tempfile.mkdtemp(prefix='gsd-p56-01-tree-')
        self.addCleanup(shutil.rmtree, tmpdir, ignore_errors=True)

        hermes_home = os.path.join(tmpdir, 'hh')
        state_dir = os.path.join(hermes_home, 'state', 'revenium')
        markers_dir = os.path.join(state_dir, 'markers')
        assessments_dir = os.path.join(state_dir, 'job-assessments')
        os.makedirs(markers_dir, mode=0o700)
        os.makedirs(assessments_dir, mode=0o700)
        state_db = os.path.join(hermes_home, 'state.db')
        jobs_ledger = os.path.join(state_dir, 'revenium-jobs.ledger')

        # started_at/ended_at far in the past so the session passes the
        # settle-seconds filter without needing a markers-ready sentinel
        # (the same idiom every compat/aux fixture in this repo uses).
        build_state_db(state_db, [{
            'id': sid, 'model': 'claude-sonnet-4-6', 'source': 'test',
            'input_tokens': 100, 'output_tokens': 50,
            'cache_read': 0, 'cache_write': 0, 'reasoning': 0,
            'estimated_cost': '0', 'api_calls': 1,
            'started_at': 1715514000.0, 'ended_at': 1715514000.0,
            'billing_provider': 'anthropic',
        }])
        if aux_rows is not None:
            build_session_model_usage(state_db, aux_rows)

        # Pre-seed the jobs ledger (OUTCOME-04 gate) so the outcome stage
        # does not defer.
        os.makedirs(os.path.dirname(jobs_ledger), exist_ok=True)
        with open(jobs_ledger, 'w') as f:
            f.write(f'JOB:{job_id}:created:1715516001.000\n')

        task_marker = {
            'muid': f'{job_id}-task', 'ts': 1715516000.5, 'sid': sid,
            'task_type': 'booking_completion', 'operation_type': 'CHAT',
        }
        job_marker = {
            'kind': 'job', 'ts': 1715516002.0, 'sid': sid,
            'agentic_job_id': job_id, 'job_name': 'Phase 56 Dry Run Job',
            'job_type': 'booking_completion', 'status': 'SUCCESS',
        }
        with open(os.path.join(markers_dir, f'{sid}.jsonl'), 'w') as f:
            f.write(json.dumps(task_marker, separators=(',', ':')) + '\n')
            f.write(json.dumps(job_marker, separators=(',', ':')) + '\n')

        # D-10 (Phase 42): the job-assessments SIDECAR is the ONLY
        # value/provenance source the outcome stage reads -- the record
        # produced by the REAL valuation path (_DryRunClassifierTestCase.
        # _produce_record), serialised unchanged.
        with open(os.path.join(assessments_dir, f'{job_id}.jsonl'), 'w') as f:
            f.write(json.dumps(record, separators=(',', ':')) + '\n')

        shim_home = os.path.join(tmpdir, 'home')
        bin_dir = os.path.join(shim_home, '.local', 'bin')
        os.makedirs(bin_dir)
        shim = os.path.join(bin_dir, 'revenium')
        build_shim(shim)

        return {
            'tmpdir': tmpdir, 'hermes_home': hermes_home, 'state_dir': state_dir,
            'state_db': state_db, 'shim_home': shim_home, 'bin_dir': bin_dir,
        }

    def _tick(self, fixture, tick_index=0, extra_env=None):
        meter_log = os.path.join(fixture['tmpdir'], f'meter-{tick_index}.log')
        jobs_log = os.path.join(fixture['tmpdir'], f'jobs-{tick_index}.log')
        inv_log = os.path.join(fixture['tmpdir'], f'inv-{tick_index}.log')

        base_env = {
            **os.environ,
            'HOME': fixture['shim_home'],
            'HERMES_HOME': fixture['hermes_home'],
            'REVENIUM_STATE_DIR': fixture['state_dir'],
            'PATH': fixture['bin_dir'] + os.pathsep + os.environ.get('PATH', ''),
            'INVOCATIONS_LOG': inv_log,
            'METER_LOG': meter_log,
            'JOBS_LOG': jobs_log,
            'TZ': 'UTC',
            'REVENIUM_ORGANIZATION_NAME': '',
        }
        if extra_env:
            base_env.update(extra_env)

        rc, _ignored, output = run_script(
            SCRIPTS_DIR / 'hermes-report.sh', base_env, inv_log)

        meter_invocations = []
        if os.path.exists(meter_log):
            with open(meter_log) as f:
                for line in f:
                    line = line.rstrip('\n')
                    if line:
                        meter_invocations.append(shlex.split(line))

        jobs_invocations = []
        if os.path.exists(jobs_log):
            with open(jobs_log) as f:
                for line in f:
                    line = line.rstrip('\n')
                    if line:
                        jobs_invocations.append(shlex.split(line))

        return {
            'rc': rc, 'output': output,
            'meter_invocations': meter_invocations,
            'jobs_invocations': jobs_invocations,
        }

    @staticmethod
    def _aux_row(sid, **overrides):
        base = {
            'session_id': sid,
            'model': 'claude-3-5-haiku',
            'billing_provider': 'anthropic',
            'billing_base_url': '',
            'billing_mode': '',
            'task': 'approval',
            'api_call_count': 3,
            'input_tokens': 40,
            'output_tokens': 10,
            'cache_read_tokens': 0,
            'cache_write_tokens': 0,
            'estimated_cost_usd': 0.0,
            'first_seen': 1715514500.0,
            'last_seen': 1715514600.0,
        }
        base.update(overrides)
        return base

    @staticmethod
    def _aux_invocations(meter_invocations):
        return [
            argv_to_flags(inv) for inv in meter_invocations
            if argv_to_flags(inv).get('--operation-type') == 'OTHER'
        ]

    @staticmethod
    def _non_aux_invocations(meter_invocations):
        return [
            inv for inv in meter_invocations
            if argv_to_flags(inv).get('--operation-type') != 'OTHER'
        ]

    @staticmethod
    def _outcome_invocation(jobs_invocations):
        for argv in jobs_invocations:
            if len(argv) >= 2 and argv[0] == 'jobs' and argv[1] == 'outcome':
                return argv
        return None


class DryRunReportableValuedRowTests(_DryRunClassifierTestCase, _DryRunReporterMixin):
    """Task 1 behaviours 1-4: the revenueCard-configured install prices a
    job through the REAL classifier valuation path, the produced record
    reaches the wire with its value intact, its auxiliary spend ships
    attributed to the same job, and a wrongly-nested card is proven to
    produce nothing reportable -- the exact Phase 53 host defect,
    reproduced and caught before a tenant is ever touched."""

    def test_1_configured_revenue_card_produces_reportable_priced_assessment(self):
        mod, record = self._produce_record()
        self.assertIn(
            record['evidence_class'], mod._REPORTABLE_EVIDENCE_CLASSES,
            f"a revenueCard-configured assessment must carry a reportable "
            f"evidence_class, got {record['evidence_class']!r}",
        )
        self.assertIsNotNone(
            record.get('estimated_value'),
            'a configured revenue card must produce a non-null estimated_value')
        self.assertGreater(
            record['estimated_value'], 0,
            'a configured revenue card must produce a positive estimated_value')
        self.assertEqual(
            EXPECTED_VALUE, record['estimated_value'],
            'the derived value must be the configured gross*fraction product, '
            'not the built-in hours*rate derivation')

    def test_2_produced_record_reaches_jobs_outcome_argv_with_its_value(self):
        _mod, record = self._produce_record()
        fixture = self._build_dry_run_tree(
            SID, JOB_ID, record, aux_rows=[self._aux_row(SID)])
        result = self._tick(fixture, 0)
        self.assertEqual(result['rc'], 0, f"hermes-report.sh failed: {result['output']}")

        argv = self._outcome_invocation(result['jobs_invocations'])
        self.assertIsNotNone(
            argv, f"expected a jobs outcome invocation: {result['jobs_invocations']!r}")
        self.assertIn('--outcome-value', argv)
        self.assertEqual(
            argv[argv.index('--outcome-value') + 1], str(EXPECTED_VALUE),
            '--outcome-value must equal the value the real valuation path produced')
        self.assertIn('--metadata', argv)
        meta = json.loads(argv[argv.index('--metadata') + 1])
        self.assertIsNotNone(
            meta.get('net_value'),
            'the --metadata envelope must carry a non-null value field for a '
            'reportable record')

    def test_3_same_tick_aux_invocation_attributed_to_the_same_job(self):
        _mod, record = self._produce_record()
        fixture = self._build_dry_run_tree(
            SID, JOB_ID, record, aux_rows=[self._aux_row(SID)])
        result = self._tick(fixture, 0)
        self.assertEqual(result['rc'], 0, f"hermes-report.sh failed: {result['output']}")

        aux = self._aux_invocations(result['meter_invocations'])
        self.assertEqual(
            len(aux), 1,
            f'expected exactly 1 invocation carrying --operation-type OTHER, '
            f'got {len(aux)}: {result["meter_invocations"]!r}',
        )
        outcome_argv = self._outcome_invocation(result['jobs_invocations'])
        self.assertIsNotNone(outcome_argv)
        self.assertEqual(
            aux[0].get('--agentic-job-id'), outcome_argv[2],
            'the auxiliary row must be attributed to the same job the '
            'outcome stage reported against',
        )
        self.assertEqual(aux[0].get('--agentic-job-id'), JOB_ID)

    def test_4_wrongly_nested_card_yields_no_reportable_assessment(self):
        mod, record = self._produce_record(revenue_card_top_level=True)
        self.assertNotIn(
            record['evidence_class'], mod._REPORTABLE_EVIDENCE_CLASSES,
            'a revenueCard misplaced as a top-level sibling of '
            'llmOutcomeEvaluation must never produce a reportable evidence class',
        )
        self.assertNotEqual(
            record.get('reportability_status'), mod.REPORTABILITY_REPORTABLE,
            'the placement trap must produce NO reportable priced assessment -- '
            'this is exactly the rehearsal that would have caught the Phase 53 '
            '85-session defect before a single live token was spent',
        )


class DryRunToggleParityTests(_DryRunClassifierTestCase, _DryRunReporterMixin):
    """Task 1 behaviour 5: the D-05 toggle's local twin. One fixture,
    metered twice from pristine copies (so the enabled arm's ledger writes
    cannot influence the disabled arm), differing only in
    REVENIUM_AUX_METERING -- proven byte-identical outside the AUX row."""

    def test_disabled_arm_ships_zero_aux_and_matches_enabled_arm_outside_aux(self):
        _mod, record = self._produce_record()

        fixture_enabled = self._build_dry_run_tree(
            SID, JOB_ID, record, aux_rows=[self._aux_row(SID)])
        result_enabled = self._tick(fixture_enabled, 0)
        self.assertEqual(
            result_enabled['rc'], 0, f"hermes-report.sh failed: {result_enabled['output']}")

        fixture_disabled = self._build_dry_run_tree(
            SID, JOB_ID, record, aux_rows=[self._aux_row(SID)])
        result_disabled = self._tick(
            fixture_disabled, 0, extra_env={'REVENIUM_AUX_METERING': 'disabled'})
        self.assertEqual(
            result_disabled['rc'], 0, f"hermes-report.sh failed: {result_disabled['output']}")

        aux_disabled = self._aux_invocations(result_disabled['meter_invocations'])
        self.assertEqual(
            len(aux_disabled), 0,
            'the disabled arm must ship zero --operation-type OTHER invocations')

        enabled_non_aux = self._non_aux_invocations(result_enabled['meter_invocations'])
        self.assertEqual(
            enabled_non_aux, result_disabled['meter_invocations'],
            'the non-AUX meter completion argv must be equal, element for '
            'element, between the enabled and disabled arms',
        )
        self.assertEqual(
            result_enabled['jobs_invocations'], result_disabled['jobs_invocations'],
            'the jobs outcome argv must be equal, element for element, '
            'between the enabled and disabled arms',
        )


class DryRunEdgeArmTests(_DryRunClassifierTestCase, _DryRunReporterMixin):
    """Task 2: the four probe edges this plan owns -- E3 (idempotency), E5
    (adjacency), E6 first half (empty), and E7 (ordering). E6's second half
    (the absent-table and off-switch arms) and the shipped Phase 55
    coverage are cited, not duplicated here -- see this plan's own
    <verify> block, which runs
    tests.test_phase55_auxiliary_metering.OffSwitchArmTests and
    tests.test_phase55_aux_edges directly."""

    def test_e3_idempotency_second_tick_over_unchanged_counters_ships_nothing(self):
        _mod, record = self._produce_record()
        fixture = self._build_dry_run_tree(
            SID, JOB_ID, record, aux_rows=[self._aux_row(SID)])
        self._tick(fixture, 0)

        ledger_path = os.path.join(fixture['state_dir'], 'revenium-aux.ledger')
        with open(ledger_path) as f:
            lines_before = f.readlines()

        result2 = self._tick(fixture, 1)
        aux2 = self._aux_invocations(result2['meter_invocations'])
        self.assertEqual(
            len(aux2), 0,
            'a second tick over an unchanged fixture must ship zero AUX invocations')

        with open(ledger_path) as f:
            lines_after = f.readlines()
        self.assertEqual(
            len(lines_before), len(lines_after),
            'a second tick over an unchanged fixture must append zero new '
            'AUX: ledger lines')

    def test_e5_adjacency_touching_case_emits_nothing_one_token_above_emits_once(self):
        _mod, record = self._produce_record()
        aux_row = self._aux_row(SID)
        fixture = self._build_dry_run_tree(SID, JOB_ID, record, aux_rows=[aux_row])
        self._tick(fixture, 0)

        ledger_path = os.path.join(fixture['state_dir'], 'revenium-aux.ledger')
        with open(ledger_path) as f:
            lines_after_baseline = f.readlines()
        self.assertEqual(len(lines_after_baseline), 1)

        # The touching case: tick again over the SAME, unchanged state.db --
        # the row's cumulative counters exactly equal the ledger baseline.
        result_touch = self._tick(fixture, 1)
        aux_touch = self._aux_invocations(result_touch['meter_invocations'])
        self.assertEqual(
            len(aux_touch), 0,
            'a row whose cumulative counters exactly equal its ledger '
            'baseline must emit nothing')
        with open(ledger_path) as f:
            lines_after_touch = f.readlines()
        self.assertEqual(
            len(lines_after_touch), 1,
            'the touching case must append no new ledger line')

        # One token -- and a matching cost delta, so --total-cost is
        # actually emitted on this tick -- above the baseline must emit
        # exactly once.
        conn = sqlite3.connect(fixture['state_db'])
        conn.execute(
            "UPDATE session_model_usage SET input_tokens = input_tokens + 1, "
            "estimated_cost_usd = estimated_cost_usd + 0.01 "
            "WHERE session_id = ? AND task = ?", (SID, aux_row['task']),
        )
        conn.commit()
        conn.close()

        result_above = self._tick(fixture, 2)
        aux_above = self._aux_invocations(result_above['meter_invocations'])
        self.assertEqual(
            len(aux_above), 1,
            'exactly one token above the ledger baseline must emit exactly once')
        self.assertEqual(aux_above[0].get('--input-tokens'), '1')
        self.assertEqual(
            aux_above[0].get('--total-cost'), '0.010000',
            'the emitted --total-cost must equal the expected delta as a '
            'decimal string, never a tolerance-based comparison')
        with open(ledger_path) as f:
            lines_after_above = f.readlines()
        self.assertEqual(
            len(lines_after_above), 2,
            'exactly one new ledger line must be appended')

    def test_e6_no_aux_rows_still_produces_valued_outcome(self):
        _mod, record = self._produce_record()
        fixture = self._build_dry_run_tree(SID, JOB_ID, record, aux_rows=None)
        result = self._tick(fixture, 0)
        self.assertEqual(result['rc'], 0, f"hermes-report.sh failed: {result['output']}")

        argv = self._outcome_invocation(result['jobs_invocations'])
        self.assertIsNotNone(argv)
        self.assertIn(
            '--outcome-value', argv,
            'a revenueCard-configured session with no auxiliary row at all '
            'must still produce its valued main-loop (outcome) row')

    def test_e7_ordering_two_rows_ship_in_a_stable_order_across_ticks(self):
        _mod, record = self._produce_record()
        row_a = self._aux_row(SID, task='approval')
        row_b = self._aux_row(SID, task='compression')

        fixture1 = self._build_dry_run_tree(
            SID, JOB_ID, record, aux_rows=[row_a, row_b])
        result1 = self._tick(fixture1, 0)
        aux1 = self._aux_invocations(result1['meter_invocations'])
        self.assertEqual(len(aux1), 2)
        txids1 = {a.get('--transaction-id') for a in aux1}
        self.assertEqual(
            len(txids1), 2, 'the two rows must ship with distinct transaction ids')
        order1 = [a.get('--task-type') for a in aux1]

        fixture2 = self._build_dry_run_tree(
            SID, JOB_ID, record, aux_rows=[row_a, row_b])
        result2 = self._tick(fixture2, 0)
        aux2 = self._aux_invocations(result2['meter_invocations'])
        order2 = [a.get('--task-type') for a in aux2]

        self.assertEqual(
            order1, order2,
            'emission order must be identical across two independent ticks '
            'over the same byte-identical fixture')

        # Source is two adjacent Python string literals (concatenated at
        # parse time, not joined by a space in the file itself), so the
        # ORDER BY clause is asserted as its two contiguous source lines
        # rather than as one long joined string.
        self.assertIn(
            '"ORDER BY session_id, model, billing_provider, billing_base_url, "',
            _HERMES_REPORT_SH_TEXT,
            'the auxiliary query ORDER BY must still name the first five of '
            'its six primary-key columns, or emission order is no longer total',
        )
        self.assertIn(
            '"billing_mode, task"',
            _HERMES_REPORT_SH_TEXT,
            'the auxiliary query ORDER BY must still name the sixth '
            'primary-key column (task), or emission order is no longer total',
        )


if __name__ == '__main__':
    unittest.main()
