"""Phase 47 Plan 01 (EGV-24/EGV-25 phase, D-06/D-07/D-08) -- the joined,
produced-artifact end-to-end chain.

Every existing reporter-path fixture (tests/test_phase38_reporter_path.py,
tests/test_phase46_feature_off.py) hand-authors the marker and/or the
job-assessment sidecar it feeds `hermes-report.sh`.
`SidecarFixtureFidelityTests` (test_phase38_reporter_path.py) exists to make
that hand-authoring SAFE, and its own docstring calls itself an explicit
LOWER BOUND: "it proves every literally-keyed forwarder has a matching
fixture key today, not that no future forwarder could ever escape it."

D-06 closes that bound for one path by building the chain out of PRODUCED
artifacts instead: a real `state.db` transcript is seeded (the only thing
this module hand-authors, and it is INPUT, never a produced artifact) -->
the REAL `revenium-classifier` plugin (`run_classification_async`, with only
`call_llm` stubbed) WRITES the marker and the job-assessment sidecar --> a
REAL `hermes-report.sh` subprocess READS those files and forwards them to a
PATH-shadowing `revenium` stub that captures argv. Nothing between the
classifier and the reporter is hand-authored.

D-08: every assertion here is STRUCTURAL (argv shape, metadata properties,
substring absence) -- no fifth golden argv fixture is added under
tests/fixtures/compat/. The four immutable v1.x goldens stay the only
pinned wire shapes.

Own isolated-import idiom (D-09): the module-scoped `_LOAD_SEQ` /
`_ENV_TOUCHED` / `_ENV_SAVED` / `_ENV_KEYS` globals, `setUpModule`,
`_restore_env`, `tearDownModule` and `_load_classifier` below are
DUPLICATED -- never imported -- from
tests/test_phase46_feature_off.py:35-123 (itself duplicated from
tests/test_phase38_reporter_path.py:1663-1719). Importing either module's
copy would couple this module to that module's import-time env mutation,
which is the documented bleed hazard: restoring only at tearDownModule
(module-scoped, once for the whole file) is not enough, because a
REVENIUM_STATE_DIR left pointing at an already-deleted tmpdir silently
breaks every later class run in the SAME `unittest discover` process.
`_restore_env` is therefore ALSO called from this class's own `tearDown`,
per test, not just at module teardown -- copied verbatim as a discipline,
not merely as a comment, so a later reader does not "simplify" it back to
module-scoped restore. This module's own module-name prefix is
`p47e2e_pkg`, distinct from Phase 38's and Phase 46's own prefixes, so
`sys.modules` keys cannot collide when discovery interleaves this module
with any other phase's isolated-import test module under `-p 'test_*.py'`.
"""
import ast
import asyncio
import importlib.util
import json
import os
import shlex
import shutil
import sqlite3
import subprocess
import sys as _sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests._compat_helpers import (
    build_shim,
    build_state_db,
    ROOT,
    SCRIPTS_DIR,
)

PLUGIN_DIR = ROOT / 'skills' / 'revenium' / 'plugins' / 'revenium-classifier'
SKILL_DIR = ROOT / 'skills' / 'revenium'

# Seeded transcript sentinels (T-47-03): distinctive enough that an
# accidental substring collision with real argv content is not plausible,
# so test_no_transcript_text_reaches_any_captured_argv is a meaningful
# negative assertion, not a vacuous one.
_SENTINEL_USER_TEXT = "gsd-p47e2e-sentinel-user-message-must-never-cross-the-wire"
_SENTINEL_ASSISTANT_TEXT = "gsd-p47e2e-sentinel-assistant-message-must-never-cross-the-wire"

# ---------------------------------------------------------------------------
# Own env-isolation idiom -- see module docstring. Distinct module-name
# prefix (`p47e2e_pkg`, never any other phase's own isolated-import prefix)
# so sys.modules keys cannot collide when discovery interleaves this module
# with any other phase's isolated-import test module under `-p 'test_*.py'`.
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
    for cached in [k for k in list(_sys.modules) if k.startswith('p47e2e_pkg')]:
        del _sys.modules[cached]


def _load_classifier(env=None):
    """Import the revenium-classifier plugin fresh; return (classifier, evaluators)."""
    for k, v in (env or {}).items():
        os.environ[k] = v
        _ENV_TOUCHED.add(k)
    _LOAD_SEQ[0] += 1
    name = f'p47e2e_pkg_{_LOAD_SEQ[0]}'
    for cached in [k for k in _sys.modules if k.startswith('p47e2e_pkg')]:
        del _sys.modules[cached]
    spec = importlib.util.spec_from_file_location(
        name, str(PLUGIN_DIR / '__init__.py'), submodule_search_locations=[str(PLUGIN_DIR)])
    mod = importlib.util.module_from_spec(spec)
    _sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return _sys.modules[f'{name}.classifier'], _sys.modules[f'{name}.evaluators']


# ---------------------------------------------------------------------------
# Task 2 (D-06 lower-bound closure) -- duplicated, not imported, from
# tests/test_phase38_reporter_path.py:934-983's _extract_forwarder_record_keys.
# Same discipline: anchor on the forwarder assignment string, isolate the
# heredoc body, ast.parse it as a standalone module, walk for
# record.get('<literal>') calls, and return None -- never a partial or
# guessed list -- if the anchor moved or the body no longer parses.
# ---------------------------------------------------------------------------
def _extract_forwarder_record_keys(script_text):
    """LOWER BOUND, not a complete inventory (see the analog's own
    docstring, test_phase38_reporter_path.py:934-952): the bound family
    (value_low/value_base/value_high) is read through a loop variable
    (`record.get(_bound_key)`), not a literal `record.get('value_low')`, so
    this ast walk over literal string arguments cannot see it."""
    anchor = 'outcome_metadata=$('
    start_marker = script_text.find(anchor)
    if start_marker == -1:
        return None
    heredoc_start = script_text.find("<<'PY'", start_marker)
    if heredoc_start == -1:
        return None
    body_start = script_text.find('\n', heredoc_start) + 1
    body_end = script_text.find('\nPY\n', body_start)
    if body_end == -1:
        return None
    body = script_text[body_start:body_end]
    try:
        tree = ast.parse(body)
    except SyntaxError:
        return None
    keys = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == 'get'
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == 'record'
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            keys.append(node.args[0].value)
    return keys


# Task 2: which of the extracted forwarder keys can the naked-LLM VALUED
# path (SUCCESS -> assessment -> MODEL_ESTIMATED_DEMO -> reportable)
# structurally never produce.
#
# Determined EMPIRICALLY (per this plan's own instruction), not guessed:
# _extract_forwarder_record_keys(script_text) against the live
# hermes-report.sh returns exactly 21 keys --
#   bounds_source, assessment_schema_version, taxonomy_version,
#   prompt_version, policy_version, evidence_class, reportability_status,
#   economic_mechanism, net_value, supplied_costs, cost_coverage,
#   double_counting_group, evaluator, evaluator_version, model,
#   inference_provider, inference_address_class, confidence, assumptions,
#   kind, sequence
# -- and a record produced by driving the real classifier through
# _drive_produced_arc's SUCCESS/reportable path (below) carries every one
# of those 21 keys, INCLUDING 'sequence' (classifier.py's
# _build_job_assessment sets it to the literal 0 on every record it
# builds, job_assessment and abstention alike -- not correction-only, the
# way test_phase38_reporter_path.py's HAND-AUTHORED _sidecar_record()
# fixture implies via its own _SEQUENCE_ONLY_ON_CORRECTIONS exemption).
# 'study_id'/'study_version' are NOT in the extracted list at all (the
# forwarder heredoc has no literal record.get('study_id') call today), so
# they are not a candidate for this set either way.
#
# The empirical result is therefore an EMPTY set: every literally-keyed
# forwarder the reporter reads IS present on a classifier-produced,
# naked-LLM valued sidecar. This is the finding this plan's own action
# anticipated as a possible outcome ("If the diff contains a key that has
# NO such justification, that is a real finding") -- here the finding runs
# the other way: no exemption is needed, so none is added (this repo's
# rule that an exemption set is never widened to make something pass,
# applied in its stronger form: it is not populated at all when the data
# does not require it).
_UNREACHABLE_ON_THE_NAKED_LLM_VALUED_PATH = frozenset()


# Plan 47-02 (Task 1): the two outcome-value-family CLI flags
# hermes-report.sh appends together or not at all (never one alone --
# see the "Both flags are added together or not at all" comment at
# skills/revenium/scripts/hermes-report.sh:3555-3558). Spelled exactly as
# the script appends them; all three D-07 paths this plan drives (path 2
# abstention, path 3 withheld/candidate, path 4 negative net value's
# reportable-but-still-worth-checking shape) assert against this ONE
# shared constant rather than three independent literal spellings.
_VALUE_FLAG_TOKENS = ('--outcome-value', '--outcome-currency')


def _outcome_invocations(jobs_argv):
    return [
        argv for argv in jobs_argv
        if len(argv) >= 2 and argv[0] == 'jobs' and argv[1] == 'outcome'
    ]


def _metadata_of(argv):
    for i, tok in enumerate(argv):
        if tok == '--metadata' and i + 1 < len(argv):
            return argv[i + 1]
    return None


class TestPhase47EndToEnd(unittest.TestCase):
    """D-06/D-07/D-08 -- the produced-artifact chain: a real state.db
    transcript drives the REAL classifier (only call_llm stubbed), which
    WRITES the marker and job-assessment sidecar, which a REAL
    hermes-report.sh subprocess then READS and forwards to a PATH-shadowing
    revenium stub. Nothing between the two is hand-authored."""

    def tearDown(self):
        _restore_env()

    # -- fixture builder (D-06: the seeded transcript is the ONLY hand------
    # -- authored input; everything else is produced) ----------------------

    def _build_produced_fixture(self, sid, job_id, task_type='code_review',
                                 tokens=(100, 50), config=None, source='test'):
        """Build one produced-chain fixture on disk: a tmpdir with the
        hermes_home/state tree, a seeded state.db carrying BOTH the
        metering `sessions` row (via _compat_helpers.build_state_db,
        UNMODIFIED) and a real `messages` table (this harness's own
        addition, per D-06) plus a `parent_session_id` column on
        `sessions` so the classifier's root-session walk resolves instead
        of falling into its fail-open path. Copies the real taxonomy seed
        files so the fixture matches an installed host. Writes
        config.json from the caller-supplied (or D-07 path 1 default)
        llmOutcomeEvaluation object. Builds the PATH-shadowing revenium
        shim via _compat_helpers.build_shim, UNMODIFIED, at its default
        capabilities. Returns a dict of every path plus base_env, sid, and
        the SEED job_id (the classifier appends its own entropy suffix;
        _drive_classifier overwrites this key with the REAL, produced
        agentic_job_id once it exists on disk).
        """
        tmpdir = tempfile.mkdtemp(prefix='gsd-p47e2e-')
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

        build_state_db(state_db, [{
            'id': sid, 'model': 'claude-sonnet-4-6', 'source': source,
            'input_tokens': tokens[0], 'output_tokens': tokens[1],
            'cache_read': 0, 'cache_write': 0, 'reasoning': 0,
            'estimated_cost': '0', 'api_calls': 1,
            'started_at': 1715514000.0, 'ended_at': 1715514000.0,
            'billing_provider': 'anthropic',
        }])

        # D-06: this is the ONLY hand-authored input in the whole chain --
        # a real transcript the REAL classifier reads via
        # _read_session_messages / _read_session_transcript, on the SAME
        # sqlite file build_state_db already created (never a second,
        # synthetic DB). Everything downstream of this (the marker, the
        # sidecar, the argv) is PRODUCED, not authored by this test.
        conn = sqlite3.connect(state_db)
        try:
            conn.execute('ALTER TABLE sessions ADD COLUMN parent_session_id TEXT')
            conn.execute(
                'CREATE TABLE messages (session_id TEXT, role TEXT, content TEXT, '
                'tool_calls TEXT, timestamp INTEGER)'
            )
            conn.execute(
                'INSERT INTO messages VALUES (?,?,?,?,?)',
                (sid, 'user', _SENTINEL_USER_TEXT, None, 1000),
            )
            conn.execute(
                'INSERT INTO messages VALUES (?,?,?,?,?)',
                (sid, 'assistant', _SENTINEL_ASSISTANT_TEXT, None, 1001),
            )
            conn.commit()
        finally:
            conn.close()

        shutil.copy(SKILL_DIR / 'task-taxonomy.json', os.path.join(state_dir, 'task-taxonomy.json'))
        shutil.copy(SKILL_DIR / 'job-taxonomy.json', os.path.join(state_dir, 'job-taxonomy.json'))

        config_file = os.path.join(state_dir, 'config.json')
        cfg = config if config is not None else {
            'llmOutcomeEvaluation': {
                'enabled': True,
                'experimentalReportEstimates': True,
                'currency': 'USD',
                'maxHoursSaved': 40,
                'maxLoadedRate': 500,
                'costs': {task_type: {'human_review': 0.0}},
            },
        }
        with open(config_file, 'w') as f:
            json.dump(cfg, f)

        shim_home = os.path.join(tmpdir, 'home')
        bin_dir = os.path.join(shim_home, '.local', 'bin')
        os.makedirs(bin_dir)
        meter_log = os.path.join(tmpdir, 'meter.log')
        jobs_log = os.path.join(tmpdir, 'jobs.log')
        inv_log = os.path.join(tmpdir, 'inv.log')
        shim = os.path.join(bin_dir, 'revenium')
        build_shim(shim, squad_capable=True, outcome_value_capable=True)

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
            'tmpdir': tmpdir, 'hermes_home': hermes_home, 'state_dir': state_dir,
            'markers_dir': markers_dir, 'assessments_dir': assessments_dir,
            'state_db': state_db, 'config_file': config_file,
            'meter_log': meter_log, 'jobs_log': jobs_log, 'inv_log': inv_log,
            'hermes_ledger': hermes_ledger, 'jobs_ledger': jobs_ledger,
            'metering_log': metering_log, 'base_env': base_env,
            'sid': sid, 'job_id': job_id, 'task_type': task_type,
        }

    # -- drive the REAL classifier (D-06: writes what the reporter reads) -

    def _drive_classifier(self, fixture, task_label='code_review',
                           job_payload=None, eval_payload=None,
                           eval_model='claude-sonnet-4-6'):
        """Fresh-load the real classifier against `fixture`'s own
        HERMES_HOME/REVENIUM_STATE_DIR -- the SAME state dir the reporter
        subprocess will later read, which is what makes this fixture's
        directory the produced-artifact chain -- then drive
        run_classification_async with call_llm stubbed for exactly three
        ordered calls (classification, job inference, outcome
        evaluation), message=None/response=None so the classifier reads
        the seeded transcript from state.db itself (never content this
        test passes directly).

        Harness self-check (per this plan's own instruction): asserts a
        marker file exists and exactly one job-assessment sidecar file
        exists on disk afterward. If either is absent the chain did not
        form and every later assertion in this module would be vacuous.
        Overwrites fixture['job_id'] with the REAL, classifier-produced
        agentic_job_id (the seed id plus the classifier's own entropy
        suffix) read back off the marker it just wrote -- never retyped.
        """
        c, ev = _load_classifier({
            'HERMES_HOME': fixture['hermes_home'],
            'REVENIUM_STATE_DIR': fixture['state_dir'],
        })

        job_payload = job_payload if job_payload is not None else {
            'agentic_job_id': fixture['job_id'], 'job_name': 'E2E fixture job',
            'job_type': fixture['task_type'], 'status': 'SUCCESS',
        }

        task_resp = mock.MagicMock()
        task_resp.choices = [mock.MagicMock()]
        task_resp.choices[0].message.content = task_label

        job_resp = mock.MagicMock()
        job_resp.choices = [mock.MagicMock()]
        job_resp.choices[0].message.content = json.dumps([job_payload])

        eval_resp = mock.MagicMock()
        eval_resp.choices = [mock.MagicMock()]
        eval_resp.choices[0].message.content = (
            json.dumps(eval_payload) if eval_payload is not None else 'null'
        )
        # Phase 45 (EGV-08) provenance: response.model must be a REAL string
        # for _resolve_served_model to read, not a MagicMock auto-attribute.
        eval_resp.model = eval_model

        with mock.patch.object(c, 'call_llm', side_effect=[task_resp, job_resp, eval_resp]):
            asyncio.run(c.run_classification_async(
                session_id=fixture['sid'], message=None, response=None,
            ))

        marker_path = Path(fixture['markers_dir']) / f"{fixture['sid']}.jsonl"
        self.assertTrue(
            marker_path.is_file(),
            'the classifier must have produced a marker file for this session '
            '-- the chain did not form',
        )
        real_job_id = None
        for line in marker_path.read_text().splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            if rec.get('kind') == 'job':
                real_job_id = rec.get('agentic_job_id')
        self.assertIsNotNone(
            real_job_id,
            'the classifier must have written a kind:"job" marker record '
            '-- the chain did not form',
        )
        fixture['job_id'] = real_job_id

        sidecar_files = list(Path(fixture['assessments_dir']).glob('*.jsonl'))
        self.assertEqual(
            len(sidecar_files), 1,
            f'expected exactly one produced job-assessment sidecar file, '
            f'found: {sidecar_files} -- the chain did not form',
        )
        fixture['sidecar_path'] = str(sidecar_files[0])
        return c, ev

    # -- spawn the REAL hermes-report.sh (copy of Phase 46's _run_tick) ---

    def _run_tick(self, fixture):
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

    # -- the one entry point every test in this module drives through -----

    def _drive_produced_arc(self, sid, job_id, task_type='code_review',
                             tokens=(100, 50), config=None, source='test',
                             task_label='code_review', job_payload=None,
                             eval_payload=None, eval_model='claude-sonnet-4-6'):
        """Build a produced-chain fixture, drive the REAL classifier once,
        then run TWO real hermes-report.sh ticks -- never a hand-seeded
        JOB:<id>:created: ledger line, which would put a hand-authored
        intermediate back into the chain D-06 exists to make produced.
        Accumulates meter_argv/jobs_argv across both ticks (a valued
        SUCCESS arc can ship its `jobs create` and `jobs outcome` in the
        SAME tick, since the ledger write is synchronous-on-success within
        one hermes-report.sh run -- see the assertion below, which counts
        across the pair rather than assuming which tick carries it).
        """
        fixture = self._build_produced_fixture(
            sid=sid, job_id=job_id, task_type=task_type, tokens=tokens,
            config=config, source=source,
        )
        self._drive_classifier(
            fixture, task_label=task_label, job_payload=job_payload,
            eval_payload=eval_payload, eval_model=eval_model,
        )
        meter_argv, jobs_argv = [], []
        for _ in range(2):
            tick = self._run_tick(fixture)
            self.assertEqual(
                tick['rc'], 0,
                f"hermes-report.sh failed (rc={tick['rc']}): {tick['output']}",
            )
            meter_argv.extend(tick['meter_argv'])
            jobs_argv.extend(tick['jobs_argv'])
        return {**fixture, 'meter_argv': meter_argv, 'jobs_argv': jobs_argv}

    # -- Task 1: the valued happy path (D-07 path 1) -----------------------

    _VALUED_EVAL_PAYLOAD = {
        'economic_mechanism': 'labor_substitution',
        'inferred_role': 'software engineer',
        'estimated_hours_saved': 2.5,
        'assumed_loaded_rate': 150.0,
        'currency': 'USD',
        'basis': 'e2e fixture basis',
        'confidence': 0.7,
    }

    def test_valued_happy_path_ships_outcome_value_and_model_estimated_demo(self):
        """D-07 path 1: a SUCCESS arc, classified and evaluated by the REAL
        classifier with only call_llm stubbed, produces a job-assessment
        sidecar that resolves to MODEL_ESTIMATED_DEMO / reportable, and a
        REAL hermes-report.sh tick ships `--outcome-value` (the sidecar's
        OWN LOW bound, read off disk -- never a number retyped here) plus a
        provenance-bearing `--metadata` payload. Exactly one `jobs outcome`
        invocation exists for this job across the two driven ticks."""
        result = self._drive_produced_arc(
            sid='p47e2e-valued-sid-001', job_id='p47e2e-valued-job-001',
            task_type='code_review', eval_payload=self._VALUED_EVAL_PAYLOAD,
        )

        outcomes = _outcome_invocations(result['jobs_argv'])
        self.assertEqual(
            len(outcomes), 1,
            f'expected exactly one jobs outcome invocation for job='
            f'{result["job_id"]!r} across both ticks: {result["jobs_argv"]}',
        )
        argv = outcomes[0]
        self.assertEqual(argv[2], result['job_id'])

        sidecar_lines = [
            line for line in Path(result['sidecar_path']).read_text().splitlines()
            if line.strip()
        ]
        self.assertEqual(len(sidecar_lines), 1, sidecar_lines)
        sidecar = json.loads(sidecar_lines[0])
        self.assertIn('value_low', sidecar, sidecar)

        self.assertIn('--outcome-value', argv, argv)
        value_out = argv[argv.index('--outcome-value') + 1]
        self.assertEqual(
            value_out, str(sidecar['value_low']),
            '--outcome-value must equal the sidecar\'s OWN value_low bound, '
            f'sidecar={sidecar!r} argv={argv!r}',
        )
        self.assertIn('--outcome-currency', argv, argv)
        self.assertEqual(argv[argv.index('--outcome-currency') + 1], 'USD')

        metadata_raw = _metadata_of(argv)
        self.assertIsNotNone(metadata_raw, argv)
        meta = json.loads(metadata_raw)
        self.assertEqual(meta.get('evidence_class'), 'MODEL_ESTIMATED_DEMO', meta)
        self.assertEqual(meta.get('reportability_status'), 'reportable', meta)
        self.assertEqual(meta.get('evaluator'), 'llm', meta)
        self.assertIn('evaluator_version', meta, meta)
        self.assertEqual(meta.get('model'), 'claude-sonnet-4-6', meta)
        self.assertIn('net_value', meta, meta)
        self.assertIn('confidence', meta, meta)
        self.assertIn('assumptions', meta, meta)

    def test_no_transcript_text_reaches_any_captured_argv(self):
        """T-47-03 (EGV-20 posture, carried into the produced-artifact
        chain): neither the seeded user message nor the seeded assistant
        message appears as a substring of any captured `meter completion`
        or `jobs` argv token from the same driven arc."""
        result = self._drive_produced_arc(
            sid='p47e2e-leak-sid-001', job_id='p47e2e-leak-job-001',
            task_type='code_review', eval_payload=self._VALUED_EVAL_PAYLOAD,
        )
        self.assertTrue(result['jobs_argv'], 'the driven arc shipped no jobs argv at all')
        all_tokens = []
        for argv in result['meter_argv'] + result['jobs_argv']:
            all_tokens.extend(argv)
        joined = '\x00'.join(all_tokens)
        self.assertNotIn(
            _SENTINEL_USER_TEXT, joined,
            f'seeded user transcript text leaked into captured argv: {all_tokens}',
        )
        self.assertNotIn(
            _SENTINEL_ASSISTANT_TEXT, joined,
            f'seeded assistant transcript text leaked into captured argv: {all_tokens}',
        )

    # -- Task 2: close SidecarFixtureFidelityTests' lower bound ------------

    def test_produced_sidecar_carries_every_literally_keyed_forwarder_key(self):
        """Closes `SidecarFixtureFidelityTests`' own documented lower bound
        (tests/test_phase38_reporter_path.py): that test proves the
        HAND-AUTHORED `_sidecar_record()` fixture matches
        hermes-report.sh's forwarder heredoc; this proves the artifact
        PRODUCTION actually writes matches it too -- the closure that
        fixture's own docstring declines to claim.

        A moved/rewritten forwarder anchor must fail this test loudly
        (via the None/empty assertions below), never pass it vacuously."""
        script_text = (SCRIPTS_DIR / 'hermes-report.sh').read_text()
        keys = _extract_forwarder_record_keys(script_text)
        self.assertIsNotNone(
            keys,
            'could not extract record.get(...) keys from hermes-report.sh '
            '-- the --metadata forwarder heredoc moved and '
            '_extract_forwarder_record_keys needs updating',
        )
        self.assertTrue(
            keys,
            'extracted zero forwarder keys -- the forwarder block moved or '
            'the extractor is broken',
        )

        result = self._drive_produced_arc(
            sid='p47e2e-fidelity-sid-001', job_id='p47e2e-fidelity-job-001',
            task_type='code_review', eval_payload=self._VALUED_EVAL_PAYLOAD,
        )
        sidecar_lines = [
            line for line in Path(result['sidecar_path']).read_text().splitlines()
            if line.strip()
        ]
        self.assertEqual(len(sidecar_lines), 1, sidecar_lines)
        record = json.loads(sidecar_lines[0])

        missing = (
            (set(keys) - _UNREACHABLE_ON_THE_NAKED_LLM_VALUED_PATH) - set(record.keys())
        )
        self.assertEqual(
            missing, set(),
            f'the produced sidecar is missing forwardable keys: {missing} -- '
            'a missing key means the docs and the wire fixtures describe a '
            f'shape the produced artifact never carries. record={record!r}',
        )

    # -- Plan 47-02 Task 1: the abstention path (D-07 path 2) --------------

    def test_abstention_path_ships_outcome_with_provenance_and_no_value(self):
        """D-07 path 2: a SUCCESS arc whose evaluator DECLINES (the third
        call_llm response is the evaluator's literal abstention token,
        `'null'` -- pinned by tests/test_phase37_llm_evaluator.py's own
        `test_prompt_shape` asserting the prompt says "output exactly:
        null") still ships exactly one `jobs outcome` invocation, carrying
        NO outcome-value flag and NO outcome-currency flag, but STILL
        carrying provenance (evaluator, evaluator_version) in --metadata.

        Load-bearing (Phase 40's live run): an evaluator that never
        abstains is indistinguishable from one that assigns a number to
        every successful arc regardless of merit. Proving the abstention
        path ships a real, provenance-bearing record -- not a dropped
        report -- is what makes a later observed valuation meaningful
        rather than assumed. `_drive_produced_arc`'s own default config
        (llmOutcomeEvaluation.enabled=True,
        experimentalReportEstimates=True) is reused unmodified: the only
        difference from path 1 (the valued happy path) is the evaluator's
        own response, never the config."""
        result = self._drive_produced_arc(
            sid='p47e2e-abstain-sid-001', job_id='p47e2e-abstain-job-001',
            task_type='code_review',
            # eval_payload=None (the default) drives _drive_classifier's
            # own literal 'null' abstention response -- never retyped here.
        )

        outcomes = _outcome_invocations(result['jobs_argv'])
        self.assertEqual(
            len(outcomes), 1,
            f'expected exactly one jobs outcome invocation for job='
            f'{result["job_id"]!r} across both ticks: {result["jobs_argv"]}',
        )
        argv = outcomes[0]
        self.assertEqual(argv[2], result['job_id'])

        for flag in _VALUE_FLAG_TOKENS:
            self.assertNotIn(
                flag, argv,
                f'abstained arc must not ship {flag!r}: argv={argv!r}',
            )

        metadata_raw = _metadata_of(argv)
        self.assertIsNotNone(metadata_raw, argv)
        meta = json.loads(metadata_raw)
        self.assertIn('evaluator', meta, meta)
        self.assertIn('evaluator_version', meta, meta)


if __name__ == '__main__':
    unittest.main()
