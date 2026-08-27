"""Phase 46 Plan 05 (EGV-22, D-08) -- feature-off byte-identity, DRIVEN.

The four immutable v1.x goldens (tests/fixtures/compat/*.golden.json) pin
the wire SHAPE for the top-level session paths, but nothing before this
module actually drives a real hermes-report.sh tick with
`llmOutcomeEvaluation.enabled` set to the literal JSON boolean false and
asserts the result against them. "The enrichment code is not reached" is a
source-level claim -- exactly the class of claim this repo's four-times-
recurring fixture-fidelity defect has falsified before (see
tests/test_phase38_reporter_path.py's own SidecarFixtureFidelityTests).

This module proves it by EXECUTION instead:

  1. A real `revenium-classifier` gate function call
     (classifier._llm_evaluation_enabled) reads this module's own
     disabled-fixture config.json and returns False -- the exact boolean
     run_classification_async consults before it will ever call
     _attach_assessment (classifier.py Step 7).
  2. A real hermes-report.sh subprocess, spawned against state a
     disabled classifier run actually produces (a marker file with no
     "assessment" key, ZERO files under job-assessments/), ships
     `meter completion` argv byte-identical to BOTH
     tests/fixtures/compat/meter-completion.golden.json (the per-marker
     path) and meter-completion-markerless.golden.json (the markerless
     path, including its argv_order token list).
  3. The same driven tick appends the unchanged HERMES:/JOB: ledger line
     shapes, ships a `jobs outcome` --metadata payload carrying nothing
     from Phase 42-46 (net_value, evidence_class, metadata_truncated,
     inference_address_class), and stays idempotent across two ticks.
  4. This harness coexists with tests/test_phase38_reporter_path.py's
     TestPhase38Canary in one unittest process, in EITHER discovery
     order, with a negative control proving the coexistence guard is not
     itself vacuous.

Own isolated-import idiom (D-08): the module-scoped `_LOAD_SEQ` /
`_ENV_TOUCHED` / `_ENV_SAVED` globals, `setUpModule`, `_restore_env`,
`tearDownModule` and `_load_classifier` below are DUPLICATED -- not
imported -- from tests/test_phase38_reporter_path.py:1663-1719. Importing
that module's copies would couple this module to that module's
import-time env mutation, which is the documented bleed hazard: restoring
only at tearDownModule (module-scoped, once for the whole file) is not
enough, because a REVENIUM_STATE_DIR left pointing at a canary test's
already-deleted tmpdir silently breaks every later class run in the SAME
process. `_restore_env` is therefore also called from this class's own
`tearDown`, per test, not just at module teardown -- copied verbatim as a
discipline, not merely as a comment, so a later reader does not
"simplify" it back to module-scoped restore.
"""
import importlib.util
import io
import json
import os
import shlex
import shutil
import subprocess
import sys as _sys
import tempfile
import unittest
from pathlib import Path

from tests._compat_helpers import (
    assert_argv_matches_golden,
    build_shim,
    build_state_db,
    load_golden,
    ROOT,
    SCRIPTS_DIR,
)

PLUGIN_DIR = ROOT / 'skills' / 'revenium' / 'plugins' / 'revenium-classifier'

# ---------------------------------------------------------------------------
# Own env-isolation idiom -- see module docstring. Distinct module-name
# prefix (`p46off_pkg`, never another phase's own isolated-import prefix)
# so sys.modules keys cannot collide when discovery interleaves this
# module with any other phase's isolated-import test module under
# `-p 'test_*.py'`.
# ---------------------------------------------------------------------------
_LOAD_SEQ = [0]
_ENV_TOUCHED = set()
_ENV_SAVED = {}

_ENV_KEYS = (
    'REVENIUM_STATE_DIR', 'REVENIUM_MARKERS_DIR', 'REVENIUM_CONFIG_FILE',
    'REVENIUM_TAXONOMY_FILE', 'REVENIUM_JOB_TAXONOMY_FILE', 'HERMES_HOME',
)


def setUpModule():
    for k in _ENV_KEYS:
        _ENV_SAVED[k] = os.environ.get(k)


def _restore_env():
    for k in _ENV_TOUCHED | set(_ENV_SAVED):
        prior = _ENV_SAVED.get(k)
        if prior is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = prior


def tearDownModule():
    _restore_env()
    for cached in [k for k in list(_sys.modules) if k.startswith('p46off_pkg')]:
        del _sys.modules[cached]


def _load_classifier(env=None):
    """Import the revenium-classifier plugin fresh; return (classifier, evaluators)."""
    for k, v in (env or {}).items():
        os.environ[k] = v
        _ENV_TOUCHED.add(k)
    _LOAD_SEQ[0] += 1
    name = f'p46off_pkg_{_LOAD_SEQ[0]}'
    for cached in [k for k in _sys.modules if k.startswith('p46off_pkg')]:
        del _sys.modules[cached]
    spec = importlib.util.spec_from_file_location(
        name, str(PLUGIN_DIR / '__init__.py'), submodule_search_locations=[str(PLUGIN_DIR)])
    mod = importlib.util.module_from_spec(spec)
    _sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return _sys.modules[f'{name}.classifier'], _sys.modules[f'{name}.evaluators']


def _iter_tests(suite):
    """Flatten a (possibly nested) unittest.TestSuite into individual test cases."""
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            for sub in _iter_tests(item):
                yield sub
        else:
            yield item


# Task 3 (D-08, T-46-12): these two test methods each drive a sub-run that
# loads TestPhase46FeatureOff BY NAME; naively including them in that
# sub-run would recurse forever. Excluded by explicit method-name
# membership -- matching this repo's named-exemption convention (e.g.
# test_phase38_reporter_path.py's _TRANSCRIPT_SOURCE_EXEMPT) -- never by a
# prefix or pattern match, so a future test added to this class is
# INCLUDED in the coexistence sub-run by default rather than silently
# skipped.
_COEXISTENCE_SELF_TEST_NAMES = frozenset({
    'test_coexists_with_phase38_canary_in_both_orders',
    'test_coexistence_negative_control_env_guard_is_load_bearing',
})


def _load_case_excluding(dotted_name, exclude_names):
    suite = unittest.TestLoader().loadTestsFromName(dotted_name)
    filtered = unittest.TestSuite()
    for test in _iter_tests(suite):
        if getattr(test, '_testMethodName', None) not in exclude_names:
            filtered.addTest(test)
    return filtered


# Phase 42-46 enrichment keys that must never reach --metadata when the
# feature is off and no job-assessment sidecar exists (D-08, EGV-22).
_ENRICHMENT_KEYS = (
    'net_value', 'evidence_class', 'metadata_truncated', 'inference_address_class',
)


class TestPhase46FeatureOff(unittest.TestCase):
    """EGV-22 (D-08) -- with llmOutcomeEvaluation.enabled=false, a REAL
    driven hermes-report.sh tick ships argv byte-identical to the base and
    markerless completion goldens, the same ledger line shapes, zero
    job-assessment sidecar files, and no Phase 42-46 enrichment key in
    --metadata -- proven by execution, never by a source-level "the code
    is not reached" claim.
    """

    def tearDown(self):
        _restore_env()

    # -- fixture builders (Task 1) ----------------------------------------

    def _build_disabled_fixture(self, sid, job_id=None, muid=None,
                                 tokens=(100, 50), task_type='code_review',
                                 job_status=None, write_marker=True,
                                 seed_job_created=False, squad_capable=True,
                                 source='test'):
        """Build one disabled-feature fixture on disk: a tmpdir with
        hermes_home, the state tree, an empty job-assessments dir (D-08:
        with the feature off, a real classifier run never writes here), a
        config.json carrying the literal JSON boolean false, a seeded
        state.db, and (optionally) a marker file shaped exactly like what
        a real disabled classifier run produces -- ready for a real
        hermes-report.sh subprocess spawn, never a hand-constructed argv.
        """
        tmpdir = tempfile.mkdtemp(prefix='gsd-p46off-')
        self.addCleanup(shutil.rmtree, tmpdir, ignore_errors=True)

        hermes_home = os.path.join(tmpdir, 'hh')
        state_dir = os.path.join(hermes_home, 'state', 'revenium')
        markers_dir = os.path.join(state_dir, 'markers')
        assessments_dir = os.path.join(state_dir, 'job-assessments')
        os.makedirs(markers_dir, mode=0o700)
        os.makedirs(assessments_dir, mode=0o700)
        state_db = os.path.join(hermes_home, 'state.db')
        hermes_ledger = os.path.join(state_dir, 'revenium-hermes.ledger')
        jobs_ledger = os.path.join(state_dir, 'revenium-jobs.ledger')
        metering_log = os.path.join(state_dir, 'revenium-metering.log')

        # D-08: hermes-report.sh itself never reads llmOutcomeEvaluation --
        # only classifier.py's _llm_evaluation_enabled gate does, in-session,
        # at the classification boundary (see
        # test_classifier_gate_reads_this_fixtures_config_as_disabled for
        # the real function-call proof). This config.json is written here
        # because a REAL disabled install's config.json really does carry
        # this key -- the byte-identity claim this class proves rests on
        # the ABSENCE of a job-assessments sidecar file (what a real
        # disabled classifier run produces), never on the reporter
        # branching on this key.
        config_file = os.path.join(state_dir, 'config.json')
        with open(config_file, 'w') as f:
            json.dump({'llmOutcomeEvaluation': {'enabled': False}}, f)

        shim_home = os.path.join(tmpdir, 'home')
        bin_dir = os.path.join(shim_home, '.local', 'bin')
        os.makedirs(bin_dir)
        meter_log = os.path.join(tmpdir, 'meter.log')
        jobs_log = os.path.join(tmpdir, 'jobs.log')
        inv_log = os.path.join(tmpdir, 'inv.log')
        shim = os.path.join(bin_dir, 'revenium')

        build_state_db(state_db, [{
            'id': sid, 'model': 'claude-sonnet-4-6', 'source': source,
            'input_tokens': tokens[0], 'output_tokens': tokens[1],
            'cache_read': 0, 'cache_write': 0, 'reasoning': 0,
            'estimated_cost': '0', 'api_calls': 1,
            'started_at': 1715514000.0, 'ended_at': 1715514000.0,
            'billing_provider': 'anthropic',
        }])

        if write_marker:
            task_marker = {
                'muid': muid, 'ts': 1715515000.5, 'sid': sid,
                'task_type': task_type, 'operation_type': 'CHAT',
            }
            job_marker = {
                'kind': 'job', 'ts': 1715515001.0, 'sid': sid,
                'agentic_job_id': job_id, 'job_name': 'Phase 46 Feature-Off Fixture',
                'job_type': task_type, 'status': job_status or 'IN_PROGRESS',
            }
            with open(os.path.join(markers_dir, f'{sid}.jsonl'), 'w') as f:
                f.write(json.dumps(task_marker, separators=(',', ':')) + '\n')
                f.write(json.dumps(job_marker, separators=(',', ':')) + '\n')

        if seed_job_created:
            with open(jobs_ledger, 'w') as f:
                f.write(f'JOB:{job_id}:created:1715516001.000\n')

        build_shim(shim, squad_capable=squad_capable)

        base_env = {
            **os.environ,
            'HOME': shim_home,
            'HERMES_HOME': hermes_home,
            'REVENIUM_STATE_DIR': state_dir,
            'PATH': bin_dir + os.pathsep + os.environ.get('PATH', ''),
            'INVOCATIONS_LOG': inv_log,
            'METER_LOG': meter_log,
            'JOBS_LOG': jobs_log,
            'TZ': 'UTC',
            'REVENIUM_ORGANIZATION_NAME': '',
            'REVENIUM_AGENT_NAME': 'Hermes',
            'REVENIUM_SQUAD_NAME': '',
        }
        return {
            'tmpdir': tmpdir, 'state_dir': state_dir, 'markers_dir': markers_dir,
            'assessments_dir': assessments_dir, 'meter_log': meter_log,
            'jobs_log': jobs_log, 'inv_log': inv_log,
            'hermes_ledger': hermes_ledger, 'jobs_ledger': jobs_ledger,
            'metering_log': metering_log, 'config_file': config_file,
            'base_env': base_env, 'sid': sid, 'job_id': job_id,
        }

    def _run_tick(self, fixture):
        """Run hermes-report.sh once against `fixture`, truncating the
        meter/jobs/invocation logs first (mirrors
        TestPhase38MultiTick._run_tick in test_phase38_reporter_path.py)
        so each call's return value covers only that call's invocations.
        The ledgers, marker file, and job-assessments dir are left
        untouched across calls -- persistence across ticks is the entire
        point for the idempotency test."""
        for log in (fixture['meter_log'], fixture['jobs_log'], fixture['inv_log']):
            if os.path.exists(log):
                os.unlink(log)
            open(log, 'w').close()
        if os.path.exists(fixture['metering_log']):
            os.unlink(fixture['metering_log'])
        result = subprocess.run(
            ['bash', str(SCRIPTS_DIR / 'hermes-report.sh')],
            env=fixture['base_env'], capture_output=True, text=True, timeout=60,
        )
        meter_argv = []
        if os.path.exists(fixture['meter_log']):
            with open(fixture['meter_log']) as f:
                for line in f:
                    line = line.rstrip('\n')
                    if line:
                        meter_argv.append(shlex.split(line))
        jobs_argv = []
        if os.path.exists(fixture['jobs_log']):
            with open(fixture['jobs_log']) as f:
                for line in f:
                    line = line.rstrip('\n')
                    if line:
                        jobs_argv.append(shlex.split(line))
        return {
            'rc': result.returncode, 'meter_argv': meter_argv,
            'jobs_argv': jobs_argv, 'output': result.stdout + result.stderr,
        }

    def _drive_disabled_tick(self, **kwargs):
        """One-shot: build a disabled-feature fixture and run exactly one
        REAL hermes-report.sh tick against it. Returns the merged fixture
        info plus this tick's captured argv -- the single entry point
        Task 1's own smoke test and every Task 2 byte-identity assertion
        drive through, never a hand-constructed argv list."""
        fixture = self._build_disabled_fixture(**kwargs)
        tick = self._run_tick(fixture)
        self.assertEqual(
            tick['rc'], 0,
            f"hermes-report.sh failed (rc={tick['rc']}): {tick['output']}",
        )
        return {**fixture, **tick}

    def _drive_lifecycle_tick(self):
        """Shared fixture for the ledger/no-sidecar/no-enrichment/
        idempotency assertions: a SUCCESS job with a pre-seeded
        JOB:<id>:created: ledger line (OUTCOME-04 -- so the outcome ships
        this same tick rather than deferring), the feature off, and no
        sidecar."""
        return self._drive_disabled_tick(
            sid='p46off-life-sid-001', job_id='p46off-life-job-001',
            muid='p46off-life-muid-001', tokens=(100, 50),
            task_type='code_review', job_status='SUCCESS',
            seed_job_created=True,
        )

    @staticmethod
    def _outcome_invocations(jobs_argv):
        return [
            argv for argv in jobs_argv
            if len(argv) >= 2 and argv[0] == 'jobs' and argv[1] == 'outcome'
        ]

    # -- Task 1: the harness itself, proven before anything rests on it ---

    def test_drive_disabled_tick_produces_a_real_nonempty_meter_capture(self):
        """The fixture is proven before Task 2's byte-identity assertions
        rest on it: a driven disabled tick with a marker present ships at
        least one real `meter completion` invocation."""
        result = self._drive_disabled_tick(
            sid='p46off-smoke-sid-001', job_id='p46off-smoke-job-001',
            muid='p46off-smoke-muid-001', tokens=(100, 50),
            job_status='IN_PROGRESS',
        )
        self.assertTrue(
            result['meter_argv'],
            f"expected at least one meter completion invocation; output: {result['output']}",
        )

    def test_classifier_gate_reads_this_fixtures_config_as_disabled(self):
        """A real function-call proof, not a source-level one: fresh-load
        the classifier against THIS module's own disabled-fixture
        config.json and assert _llm_evaluation_enabled returns False --
        the exact gate run_classification_async consults before it will
        ever call _attach_assessment (classifier.py Step 7, ROI-07/ROI-09
        guard ordering)."""
        fixture = self._build_disabled_fixture(
            sid='p46off-gate-sid-001', job_id='p46off-gate-job-001',
            muid='p46off-gate-muid-001', write_marker=False,
        )
        c, _ev = _load_classifier({
            'REVENIUM_STATE_DIR': fixture['state_dir'],
            'REVENIUM_CONFIG_FILE': fixture['config_file'],
        })
        self.assertFalse(
            c._llm_evaluation_enabled(),
            'the fixture config.json must read as disabled through the REAL gate function',
        )

    # -- Task 2: byte-identical argv, identical ledgers, no sidecar -------

    def test_marker_driven_meter_completion_matches_base_golden(self):
        """A real disabled tick, with a marker present, ships a
        `meter completion` invocation byte-identical to the base golden
        (D-08, EGV-22) -- reusing the EXACT sid/muid/job/token fixture
        tests/test_compat_meter_completion.py uses to capture
        meter-completion.golden.json, so every exact_match_fields literal
        (--transaction-id, --trace-id, --agentic-job-id, --task-type)
        still matches with the feature off and no sidecar present."""
        result = self._drive_disabled_tick(
            sid='compat-sid-001', job_id='compat-job-001',
            muid='compat-muid-001', tokens=(100, 50),
            task_type='code_review', job_status='IN_PROGRESS',
        )
        self.assertEqual(
            len(result['meter_argv']), 1,
            f"expected exactly 1 meter completion invocation, got "
            f"{len(result['meter_argv'])}: {result['meter_argv']!r}",
        )
        assert_argv_matches_golden(
            self, result['meter_argv'][0], load_golden('meter-completion.golden.json'),
        )

    def test_markerless_meter_completion_matches_markerless_golden_argv_order(self):
        """A real disabled tick with NO marker file at all ships an argv
        token list equal, element for element, to the markerless golden's
        own argv_order (D-08, EGV-22) -- reusing
        tests/test_phase29_agent_inheritance.py's exact markerless
        fixture (compat-sid-markerless-001, squad-capable shim,
        REVENIUM_AGENT_NAME=Hermes, REVENIUM_ORGANIZATION_NAME='')."""
        result = self._drive_disabled_tick(
            sid='compat-sid-markerless-001', write_marker=False,
            tokens=(100, 50), squad_capable=True,
        )
        self.assertEqual(len(result['meter_argv']), 1, result['meter_argv'])
        golden = load_golden('meter-completion-markerless.golden.json')
        self.assertEqual(
            result['meter_argv'][0], golden['argv_order'],
            'feature-off markerless argv is not byte-identical to '
            'meter-completion-markerless.golden.json\n'
            f"Captured: {result['meter_argv'][0]}\nGolden:   {golden['argv_order']}",
        )

    def test_disabled_tick_appends_one_hermes_ledger_line(self):
        """EGV-22: the disabled tick appends exactly one
        HERMES:<sid>:<tokens>:<ts>:<muid> ledger line -- the same shape as
        before this phase."""
        result = self._drive_lifecycle_tick()
        with open(result['hermes_ledger']) as f:
            lines = [line for line in f.read().splitlines() if line.strip()]
        self.assertEqual(len(lines), 1, lines)
        self.assertRegex(lines[0], r'^HERMES:p46off-life-sid-001:150:\d+(\.\d+)?:.+$')

    def test_disabled_tick_appends_job_created_and_outcome_ledger_lines_in_order(self):
        """EGV-22: the disabled tick's jobs ledger carries
        JOB:<id>:created:<ts> before JOB:<id>:outcome:<ts>:<status> --
        the same ordering guarantee as before this phase."""
        result = self._drive_lifecycle_tick()
        with open(result['jobs_ledger']) as f:
            lines = [line for line in f.read().splitlines() if line.strip()]
        created_idx = next(
            (i for i, line in enumerate(lines)
             if line.startswith('JOB:p46off-life-job-001:created:')),
            None,
        )
        outcome_idx = next(
            (i for i, line in enumerate(lines)
             if line.startswith('JOB:p46off-life-job-001:outcome:')),
            None,
        )
        self.assertIsNotNone(created_idx, lines)
        self.assertIsNotNone(outcome_idx, lines)
        self.assertLess(created_idx, outcome_idx, lines)
        self.assertRegex(
            lines[outcome_idx], r'^JOB:p46off-life-job-001:outcome:\d+(\.\d+)?:SUCCESS$',
        )

    def test_disabled_tick_writes_zero_job_assessment_sidecar_files(self):
        """D-08: a stronger claim than canary absence, which presupposes a
        sidecar exists -- with the feature off, the job-assessments
        directory contains ZERO files at all, asserted by directory
        listing."""
        result = self._drive_lifecycle_tick()
        sidecar_files = os.listdir(result['assessments_dir'])
        self.assertEqual(
            sidecar_files, [],
            f'expected zero files under job-assessments/ with the feature '
            f'off; found: {sidecar_files}',
        )

    def test_disabled_tick_metadata_never_carries_enrichment_keys(self):
        """EGV-22: the disabled tick's `jobs outcome` --metadata payload
        carries none of the Phase 42-46 enrichment keys, and -- with no
        sidecar present at all -- is exactly the pre-Phase-42 base shape
        ({"source": "test"})."""
        result = self._drive_lifecycle_tick()
        outcome_invocations = self._outcome_invocations(result['jobs_argv'])
        self.assertEqual(len(outcome_invocations), 1, outcome_invocations)
        argv = outcome_invocations[0]
        metadata_value = None
        for i, tok in enumerate(argv):
            if tok == '--metadata' and i + 1 < len(argv):
                metadata_value = argv[i + 1]
        self.assertIsNotNone(
            metadata_value,
            f'expected --metadata to be present (carrying at least "source"): {argv}',
        )
        meta = json.loads(metadata_value)
        for key in _ENRICHMENT_KEYS:
            self.assertNotIn(
                key, meta,
                f'Phase 42-46 enrichment key {key!r} reached --metadata with the '
                f'feature off and no sidecar present: {meta}',
            )
        self.assertEqual(
            meta, {'source': 'test'},
            'with the feature off and no sidecar, --metadata must carry exactly '
            'the base-metering source field, matching the pre-Phase-42 shape',
        )

    def test_disabled_tick_is_idempotent_across_two_ticks(self):
        """EGV-22: re-running the disabled tick against unchanged state
        ships zero additional meter completion / jobs outcome
        invocations and appends zero additional ledger lines to either
        ledger -- idempotency preserved on the disabled path, the exact
        edge this repo has been bitten by before (phase-32 cross-profile
        double-ship; the legacy-reporter race)."""
        fixture = self._build_disabled_fixture(
            sid='p46off-idem-sid-001', job_id='p46off-idem-job-001',
            muid='p46off-idem-muid-001', tokens=(100, 50),
            task_type='code_review', job_status='SUCCESS',
            seed_job_created=True,
        )
        first = self._run_tick(fixture)
        self.assertEqual(first['rc'], 0, first['output'])
        self.assertEqual(len(self._outcome_invocations(first['jobs_argv'])), 1, first['jobs_argv'])

        with open(fixture['hermes_ledger']) as f:
            hermes_lines_after_first = [line for line in f.read().splitlines() if line.strip()]
        with open(fixture['jobs_ledger']) as f:
            jobs_lines_after_first = [line for line in f.read().splitlines() if line.strip()]

        second = self._run_tick(fixture)
        self.assertEqual(second['rc'], 0, second['output'])
        self.assertEqual(
            second['meter_argv'], [],
            'a second identical tick must ship zero meter completion invocations '
            f'for an unchanged session: {second["meter_argv"]}',
        )
        self.assertEqual(
            self._outcome_invocations(second['jobs_argv']), [],
            'a second identical tick must ship zero jobs outcome invocations -- '
            f'idempotency on the disabled path: {second["jobs_argv"]}',
        )

        with open(fixture['hermes_ledger']) as f:
            hermes_lines_after_second = [line for line in f.read().splitlines() if line.strip()]
        with open(fixture['jobs_ledger']) as f:
            jobs_lines_after_second = [line for line in f.read().splitlines() if line.strip()]

        self.assertEqual(
            len(hermes_lines_after_first), len(hermes_lines_after_second),
            'a second tick must append no additional HERMES: ledger lines',
        )
        self.assertEqual(
            len(jobs_lines_after_first), len(jobs_lines_after_second),
            'a second tick must append no additional JOB: ledger lines',
        )

    # -- Task 3: coexistence with the Phase 38 canary harness --------------

    def test_coexists_with_phase38_canary_in_both_orders(self):
        """T-46-12/D-08: tests.test_phase38_reporter_path.TestPhase38Canary
        and this class (itself excluded per _COEXISTENCE_SELF_TEST_NAMES)
        run green together in ONE process, in EITHER discovery order, and
        this module's own env-isolation globals show no dangling key
        pointing at an already-deleted tmpdir afterward -- proving the
        two spawning harnesses coexist in a single `unittest discover`
        run (D-08)."""
        orders = (
            ('phase38-then-phase46', (
                'tests.test_phase38_reporter_path.TestPhase38Canary',
                'tests.test_phase46_feature_off.TestPhase46FeatureOff',
            )),
            ('phase46-then-phase38', (
                'tests.test_phase46_feature_off.TestPhase46FeatureOff',
                'tests.test_phase38_reporter_path.TestPhase38Canary',
            )),
        )
        for order_name, dotted_names in orders:
            suite = unittest.TestSuite()
            for dotted in dotted_names:
                if dotted.endswith('TestPhase46FeatureOff'):
                    suite.addTest(_load_case_excluding(dotted, _COEXISTENCE_SELF_TEST_NAMES))
                else:
                    suite.addTest(unittest.TestLoader().loadTestsFromName(dotted))
            stream = io.StringIO()
            result = unittest.TextTestRunner(stream=stream, verbosity=0).run(suite)
            self.assertTrue(
                result.wasSuccessful(),
                f'{order_name} sub-run failed:\n{stream.getvalue()}',
            )
            self._assert_no_dangling_env_keys(order_name)

    def _assert_no_dangling_env_keys(self, order_name):
        for k, saved in _ENV_SAVED.items():
            current = os.environ.get(k)
            self.assertEqual(
                current, saved,
                f'{order_name}: env key {k!r} is {current!r} after the sub-run, '
                f'expected the restored baseline {saved!r} -- a dangling path '
                'into a deleted tmpdir would silently break a later module in '
                'the same discover process',
            )

    def test_coexistence_negative_control_env_guard_is_load_bearing(self):
        """T-46-12: prove _assert_no_dangling_env_keys is not vacuously
        green. Neuter this module's own _restore_env, run the ONE test in
        this class that actually mutates os.environ (via _load_classifier
        -- every other test in this class only builds an explicit
        base_env dict for a subprocess and never touches the parent
        process's os.environ at all), then assert the SAME guard now
        raises on the resulting dangling REVENIUM_STATE_DIR/
        REVENIUM_CONFIG_FILE -- before trusting it to mean anything when
        it passes above."""
        import tests.test_phase46_feature_off as _self_mod
        real_restore = _self_mod._restore_env
        try:
            _self_mod._restore_env = lambda: None
            probe = unittest.TestLoader().loadTestsFromName(
                'tests.test_phase46_feature_off.TestPhase46FeatureOff.'
                'test_classifier_gate_reads_this_fixtures_config_as_disabled'
            )
            stream = io.StringIO()
            unittest.TextTestRunner(stream=stream, verbosity=0).run(probe)
            with self.assertRaises(AssertionError):
                self._assert_no_dangling_env_keys('negative-control')
        finally:
            _self_mod._restore_env = real_restore
            _restore_env()


if __name__ == '__main__':
    unittest.main()
