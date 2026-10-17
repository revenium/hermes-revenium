"""quick-261017-kb1 -- the learned role card.

With zero operator configuration the built-in `llm` outcome evaluator now sees
a vocabulary of known human roles (role-taxonomy.json: seeded at install, grown
by the classifier), is told to copy one verbatim if it fits or propose a new
short title, and is shown each role's typical observed rate as a CONSISTENCY
ANCHOR. The role it returns is normalized, matched case-insensitively to a
stored spelling, persisted under the house LOCK_EX|LOCK_NB discipline, and
shipped on `jobs outcome --metadata` as `assumptions.inferred_role`.

Guarantee classes, per test class:

  LearnedRoleCardTracerTests   BEHAVIOURAL, end to end: seed -> prompt ->
                               canonical role -> taxonomy -> sidecar -> wire
                               (the real outcome_metadata heredoc).
  LearnedRateAnchorTests       BEHAVIOURAL on the rendered prompt.
  EvidenceInvarianceTests      BEHAVIOURAL, differential: a learned-card install
                               and a no-card install produce identical
                               evidence_class / authority / reportability /
                               value fields. A learned rate is a prompt anchor,
                               never a priced card.
  CardWinsTests                BEHAVIOURAL: an operator rateCard disables
                               learned mode entirely (no read, no write, same
                               prompt as a no-taxonomy install).
  FeatureOffTests              BEHAVIOURAL: with llmOutcomeEvaluation disabled
                               role-taxonomy.json is neither read nor written.
  FailOpenTests                BEHAVIOURAL: a persistence failure is logged and
                               never raises.

Own isolated-import idiom: `_LOAD_SEQ` / `_ENV_TOUCHED` / `_ENV_SAVED`,
`setUpModule`, `_restore_env`, `tearDownModule`, `_load_classifier`, `_resp`
and `_llm_patch` are DUPLICATED, not imported, from
tests/test_classifier_premature_cancel.py so this module does not couple to
another test module's import-time environment handling. Prefix `lrc_pkg`.
"""
import asyncio
import importlib.util
import json
import os
import shutil
import subprocess
import sys as _sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests._compat_helpers import ROOT, SCRIPTS_DIR

PLUGIN_DIR = ROOT / 'skills' / 'revenium' / 'plugins' / 'revenium-classifier'
SKILL_DIR = ROOT / 'skills' / 'revenium'
SEED_FILE = SKILL_DIR / 'role-taxonomy.json'
HERMES_REPORT_SH = SCRIPTS_DIR / 'hermes-report.sh'

_LOAD_SEQ = [0]
_ENV_TOUCHED = set()
_ENV_SAVED = {}
_ENV_KEYS = (
    'REVENIUM_STATE_DIR', 'REVENIUM_MARKERS_DIR', 'REVENIUM_CONFIG_FILE',
    'REVENIUM_TAXONOMY_FILE', 'REVENIUM_JOB_TAXONOMY_FILE',
    'REVENIUM_ROLE_TAXONOMY_FILE', 'HERMES_HOME',
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
    for cached in [k for k in list(_sys.modules) if k.startswith('lrc_pkg')]:
        del _sys.modules[cached]


def _load_classifier(env=None):
    """Import the revenium-classifier plugin fresh; return (classifier, evaluators)."""
    for k, v in (env or {}).items():
        os.environ[k] = v
        _ENV_TOUCHED.add(k)
    _LOAD_SEQ[0] += 1
    name = f'lrc_pkg_{_LOAD_SEQ[0]}'
    for cached in [k for k in _sys.modules if k.startswith('lrc_pkg')]:
        del _sys.modules[cached]
    spec = importlib.util.spec_from_file_location(
        name, str(PLUGIN_DIR / '__init__.py'), submodule_search_locations=[str(PLUGIN_DIR)])
    mod = importlib.util.module_from_spec(spec)
    _sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return _sys.modules[f'{name}.classifier'], _sys.modules[f'{name}.evaluators']


def _resp(content, model='claude-sonnet-4-6'):
    """A call_llm return value with a REAL string `.model`."""
    r = mock.MagicMock()
    r.choices = [mock.MagicMock()]
    r.choices[0].message.content = content
    r.model = model
    return r


def _llm_patch(c, responses):
    """Patch `c.call_llm` to return `responses` in order (queue-based, never a
    bare side_effect list: an exhausted list raises StopIteration, which
    asyncio.to_thread cannot deliver, hanging the suite instead of failing)."""
    queue = list(responses)

    def next_response(**kwargs):
        if not queue:
            raise RuntimeError('call_llm called more times than this test expects')
        return queue.pop(0)

    return mock.patch.object(c, 'call_llm', side_effect=next_response)


# The wire hop duplicates tests/test_phase46_metadata_envelope.py's helpers
# rather than importing that module (its setUpModule/_load_classifier mutate
# os.environ).
def _extract_outcome_metadata_heredoc(script_text):
    anchor = 'outcome_metadata=$('
    start = script_text.find(anchor)
    if start == -1:
        return None
    heredoc_start = script_text.find("<<'PY'", start)
    if heredoc_start == -1:
        return None
    body_start = script_text.find('\n', heredoc_start) + 1
    body_end = script_text.find('\nPY\n', body_start)
    if body_end == -1:
        return None
    return script_text[body_start:body_end]


def _run_forwarder(body, assessment, status='SUCCESS'):
    env = {
        'OUTCOME_SOURCE': 'prod', 'OUTCOME_STATUS': status,
        'OUTCOME_FAILURE_REASON': '', 'ASSESSMENT_JSON': json.dumps(assessment),
    }
    return subprocess.run(
        [_sys.executable, '-'], input=body, env=env, capture_output=True, text=True)


TRANSCRIPT = 'user: review this PR\nassistant: reviewed it and left comments'

EVAL_BASE = {'enabled': True, 'currency': 'USD'}
EVAL_OPT_IN = {
    'enabled': True, 'currency': 'USD',
    'experimentalReportEstimates': True, 'reportModelEstimates': True,
}


def _payload(role='senior software engineer', rate=150.0, hours=3.5, **extra):
    body = {
        'economic_mechanism': 'labor_substitution', 'inferred_role': role,
        'estimated_hours_saved': hours, 'assumed_loaded_rate': rate,
        'currency': 'USD', 'basis': 'stub', 'confidence': 0.7,
    }
    body.update(extra)
    return body


class _Harness(unittest.TestCase):
    """One tmp state tree per test and a freshly imported classifier bound to
    it. `self.role_file` is the role-taxonomy.json path under that tree."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='gsd-lrc-')
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.addCleanup(_restore_env)
        self._new_tree('main')

    def _new_tree(self, name):
        self.hermes_home = os.path.join(self.tmp, name, 'hh')
        self.state_dir = os.path.join(self.hermes_home, 'state', 'revenium')
        self.markers_dir = os.path.join(self.state_dir, 'markers')
        os.makedirs(self.markers_dir, mode=0o700)
        self.role_file = Path(self.state_dir) / 'role-taxonomy.json'
        self.lock_file = Path(self.state_dir) / 'role-taxonomy.json.lock'

    def seed_real(self):
        """Copy the REAL skill seed into the state dir (never a hand-typed list)."""
        shutil.copy(SEED_FILE, self.role_file)

    def write_roles(self, roles):
        self.role_file.write_text(json.dumps({'roles': roles}, indent=2) + '\n')

    def roles(self):
        return json.loads(self.role_file.read_text())['roles']

    def load(self, eval_cfg=EVAL_BASE, top_level=None):
        """Fresh classifier bound to this tree. `eval_cfg=None` writes no
        llmOutcomeEvaluation object at all."""
        cfg = dict(top_level or {})
        if eval_cfg is not None:
            cfg['llmOutcomeEvaluation'] = dict(eval_cfg)
        config_file = os.path.join(self.state_dir, 'config.json')
        with open(config_file, 'w') as f:
            json.dump(cfg, f)
        c, ev = _load_classifier({
            'HERMES_HOME': self.hermes_home, 'REVENIUM_STATE_DIR': self.state_dir,
            'REVENIUM_MARKERS_DIR': self.markers_dir,
            'REVENIUM_CONFIG_FILE': config_file,
            'REVENIUM_ROLE_TAXONOMY_FILE': str(self.role_file),
        })
        return c, ev

    @staticmethod
    def prompt_of(llm):
        messages = llm.call_args.kwargs['messages']
        return '\n'.join(m['content'] for m in messages)

    def evaluate(self, c, payload, job_id='kb1-job-001'):
        """One real _attach_assessment over the built-in `llm` evaluator with a
        stubbed call_llm. Returns (job, sidecar_record_or_None, prompt)."""
        job = {
            'agentic_job_id': job_id, 'job_name': 'KB1 job',
            'job_type': 'code_review', 'status': 'SUCCESS',
        }
        with _llm_patch(c, [_resp(json.dumps(payload))]) as llm:
            asyncio.run(c._attach_assessment(job, TRANSCRIPT, c._module_paths()))
        record = job.pop('_assessment_record', None)
        return job, record, self.prompt_of(llm)


class LearnedRoleCardTracerTests(_Harness):

    def test_seed_to_prompt_to_canonical_role_to_taxonomy_to_wire(self):
        self.seed_real()
        c, _ev = self.load()
        job, record, prompt = self.evaluate(c, _payload(role='senior software engineer'))

        # Seed -> prompt: quoted, with the reuse-or-propose instruction.
        self.assertIn('"Senior Software Engineer"', prompt)
        self.assertIn('copy the text INSIDE its quotes verbatim', prompt)
        self.assertIn('propose a new short role title', prompt)

        # Canonical spelling on the marker summary and the sidecar record.
        self.assertEqual(job['assessment']['assumptions']['inferred_role'], 'Senior Software Engineer')
        self.assertEqual(record['assumptions']['inferred_role'], 'Senior Software Engineer')

        # Taxonomy: count 1 and the rate window holds this rate.
        entry = self.roles()['Senior Software Engineer']
        self.assertEqual(entry['count'], 1)
        self.assertEqual(entry['rates']['USD'], {'count': 1, 'recent': [150.0]})
        self.assertRegex(entry['last_seen_at'], r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$')

        # Wire: the real outcome_metadata heredoc ships the canonical role.
        body = _extract_outcome_metadata_heredoc(HERMES_REPORT_SH.read_text())
        self.assertIsNotNone(body)
        result = _run_forwarder(body, record)
        self.assertEqual(result.returncode, 0, result.stderr)
        meta = json.loads(result.stdout.strip())
        self.assertEqual(meta['assumptions']['inferred_role'], 'Senior Software Engineer')

    def test_a_valid_new_role_is_persisted_with_the_models_collapsed_spelling(self):
        self.seed_real()
        c, _ev = self.load()
        job, record, _prompt = self.evaluate(c, _payload(role='Revenue   Operations  Lead'))
        self.assertEqual(record['assumptions']['inferred_role'], 'Revenue Operations Lead')
        self.assertIn('Revenue Operations Lead', self.roles())
        self.assertEqual(self.roles()['Revenue Operations Lead']['count'], 1)

    def test_cold_install_with_no_seed_still_learns(self):
        c, _ev = self.load()
        self.assertFalse(self.role_file.exists())
        job, record, prompt = self.evaluate(c, _payload(role='Data Analyst'))
        self.assertNotIn('known human roles', prompt, 'an empty card injects nothing')
        self.assertIn('Data Analyst', self.roles())

    def test_junk_roles_leave_the_role_blank_and_the_taxonomy_untouched(self):
        self.seed_real()
        before = self.role_file.read_bytes()
        c, _ev = self.load()
        for junk in ('  AI   agent ', 'n/a', 'x', 'Sales, Ops'):
            with self.subTest(junk=junk):
                job, record, _prompt = self.evaluate(c, _payload(role=junk))
                # The assessment and its value are still accepted.
                self.assertIn('assessment', job)
                self.assertEqual(record['assumptions']['inferred_role'], '')
                self.assertEqual(job['assessment']['assumptions']['inferred_role'], '')
                self.assertIn('estimated_value', record)
                self.assertEqual(self.role_file.read_bytes(), before)


class LearnedRateAnchorTests(_Harness):

    def _roles(self):
        return {
            'Data Analyst': {
                'count': 3, 'last_seen_at': '2026-10-01T00:00:00Z',
                'rates': {
                    'USD': {'count': 3, 'recent': [120.0, 150.0, 140.0]},
                    'EUR': {'count': 5, 'recent': [91.0, 92.0, 93.0, 94.0, 95.0]},
                },
            },
            'Recruiter': {
                'count': 2, 'last_seen_at': '2026-10-02T00:00:00Z',
                'rates': {'USD': {'count': 2, 'recent': [80.0, 90.0]}},
            },
        }

    def test_three_observations_show_the_median_and_two_do_not(self):
        self.write_roles(self._roles())
        c, _ev = self.load()
        _job, _record, prompt = self.evaluate(c, _payload(role='Data Analyst'))
        self.assertIn('"Data Analyst" (typical rate so far: 140 USD/hour)', prompt)
        self.assertIn('"Recruiter"', prompt)
        self.assertNotIn('"Recruiter" (typical', prompt)

    def test_rates_recorded_under_another_currency_are_not_shown(self):
        self.write_roles(self._roles())
        c, _ev = self.load()
        _job, _record, prompt = self.evaluate(c, _payload(role='Data Analyst'))
        self.assertNotIn('EUR/hour', prompt)
        self.assertNotIn('93 ', prompt.split('known human roles', 1)[1].split('Task arc:', 1)[0])


class EvidenceInvarianceTests(_Harness):
    """A learned rate is a prompt anchor and NEVER an operator rateCard: the
    evidence class, its authority, reportability and every value field must be
    identical with and without a learned card, in every config arm."""

    FIELDS = (
        'evidence_class', 'evidence_class_authority', 'reportability_status',
        'estimated_value', 'value_low', 'value_base', 'value_high',
        'bounds_source', 'currency',
    )

    def _run(self, name, with_card, eval_cfg, top_level):
        self._new_tree(name)
        if with_card:
            self.write_roles({
                'Senior Software Engineer': {
                    'count': 5, 'last_seen_at': '2026-10-01T00:00:00Z',
                    'rates': {'USD': {'count': 5, 'recent': [400.0, 410.0, 420.0, 430.0, 440.0]}},
                },
            })
        c, _ev = self.load(eval_cfg, top_level)
        job, record, prompt = self.evaluate(c, _payload(role='Senior Software Engineer', rate=150.0))
        self.assertEqual('known human roles' in prompt, with_card)
        fields = {k: (record or {}).get(k) for k in self.FIELDS}
        return job.get('assessment') is not None, fields

    def _assert_invariant(self, label, eval_cfg, top_level=None, expect_accepted=None):
        with_card = self._run(label + '-card', True, eval_cfg, top_level)
        without = self._run(label + '-none', False, eval_cfg, top_level)
        self.assertEqual(with_card, without, f'{label}: a learned card changed the outcome')
        if expect_accepted is not None:
            self.assertEqual(with_card[0], expect_accepted)
        return with_card

    def test_enabled_only(self):
        accepted, fields = self._assert_invariant('enabled-only', EVAL_BASE, expect_accepted=True)
        self.assertEqual(fields['evidence_class'], 'MODEL_ESTIMATED_DEMO')
        self.assertEqual(fields['evidence_class_authority'], 'evaluator')
        # 3.5h x $150, NOT the learned $400-440 anchor.
        self.assertEqual(fields['estimated_value'], 525.0)

    def test_opted_in_to_model_estimates(self):
        _accepted, fields = self._assert_invariant('opted-in', EVAL_OPT_IN, expect_accepted=True)
        self.assertEqual(fields['evidence_class'], 'MODEL_ESTIMATED_DEMO')
        self.assertEqual(fields['evidence_class_authority'], 'evaluator')

    def test_rate_card_valuation_fixture_boundary_with_no_rate_card(self):
        # The boundary is selected but NO rateCard is configured: a learned
        # rate must not stand in for one, so the outcome is whatever the
        # no-card install gets.
        self._assert_invariant(
            'valuation-fixture', EVAL_OPT_IN,
            top_level={'boundaries': {'valuation': 'rate_card_valuation_fixture'}})


class CardWinsTests(_Harness):

    def test_operator_rate_card_disables_learned_mode_entirely(self):
        self.seed_real()
        seeded = self.role_file.read_bytes()
        eval_cfg = dict(EVAL_BASE, rateCard={'Senior Software Engineer': 150})
        c, _ev = self.load(eval_cfg)

        _job, record, prompt_with_file = self.evaluate(c, _payload(role='Senior Software Engineer'))
        self.assertEqual(self.role_file.read_bytes(), seeded, 'a configured rateCard must not write')
        self.assertFalse(self.lock_file.exists())
        self.assertNotIn('known human roles', prompt_with_file)
        self.assertIn('approved list', prompt_with_file, 'the #140 vocabulary is in force')

        self.role_file.unlink()
        _job, _record, prompt_without_file = self.evaluate(c, _payload(role='Senior Software Engineer'))
        self.assertEqual(prompt_with_file, prompt_without_file)
        self.assertFalse(self.role_file.exists(), 'learned mode is off: nothing is created')


class FeatureOffTests(_Harness):

    SID = 'lrc-feature-off-sid'

    def _drive(self, c):
        jobs = [{'agentic_job_id': 'write_report', 'job_name': 'Write report',
                 'job_type': 'documentation', 'status': 'SUCCESS'}]
        with _llm_patch(c, [_resp('code_review'), _resp(json.dumps(jobs))]) as llm, \
             mock.patch.object(c, '_read_session_transcript', return_value=TRANSCRIPT):
            asyncio.run(c.run_classification_async(
                session_id=self.SID, message='write the report', response='done'))
        return llm

    def _job_markers(self):
        path = Path(self.markers_dir) / f'{self.SID}.jsonl'
        records = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
        return [r for r in records if r.get('kind') == 'job']

    def test_disabled_feature_leaves_an_existing_role_file_byte_identical(self):
        self.seed_real()
        before = self.role_file.read_bytes()
        c, _ev = self.load({'enabled': False, 'currency': 'USD'})
        llm = self._drive(c)
        self.assertEqual(llm.call_count, 2, 'task call + job call only: no evaluation')
        self.assertEqual(self.role_file.read_bytes(), before)
        self.assertFalse(self.lock_file.exists())
        [marker] = self._job_markers()
        self.assertNotIn('assessment', marker)

    def test_disabled_feature_never_creates_an_absent_role_file(self):
        c, _ev = self.load(None)
        self._drive(c)
        self.assertFalse(self.role_file.exists())
        self.assertFalse(self.lock_file.exists())
        [marker] = self._job_markers()
        self.assertNotIn('assessment', marker)


class FailOpenTests(_Harness):

    def test_unwritable_role_taxonomy_path_is_logged_and_never_raises(self):
        # A directory where the file should be: the read fails, the replace
        # fails, and the evaluation must still attach its assessment.
        self.role_file.mkdir()
        c, _ev = self.load()
        with self.assertLogs('revenium_classifier', level='WARNING') as logs:
            job, record, _prompt = self.evaluate(c, _payload(role='Data Analyst'))
        self.assertIn('assessment', job)
        self.assertIsNotNone(record)
        self.assertEqual(record['assumptions']['inferred_role'], 'Data Analyst')
        self.assertTrue(
            any('role persist' in line for line in logs.output),
            f'expected a role-persist warning, got: {logs.output}')
        self.assertTrue(self.role_file.is_dir(), 'the directory is left alone')
        self.assertFalse(Path(str(self.role_file) + '.tmp').exists(), 'no stray tmp file')


if __name__ == '__main__':
    unittest.main()
