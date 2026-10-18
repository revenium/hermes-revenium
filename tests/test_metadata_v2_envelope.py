"""quick-261017-nck (LD-1/LD-2/LD-3, PR-1..PR-6): the v2 `jobs outcome --metadata`
contract.

Every assessment-bearing blob is `schema_version` 2: a handful of base keys
followed by nested value / basis / costs / estimator groups. These tests drive
the REAL outcome_metadata heredoc, extracted live from hermes-report.sh and run
as a standalone python3 process (the same discipline as
tests/test_phase46_locality.py), never a reimplementation of its field
selection, plus end-to-end ticks through hermes-report.sh for the one fact the
heredoc cannot know alone: value.reported must equal the --outcome-value flag.

Sidecar fixtures keep the v1 SIDECAR key names; only the wire changed.
"""
import json
import os
import re
import unittest
from pathlib import Path

from tests import test_phase38_reporter_path as p38
from tests import test_phase46_locality as p46

ROOT = Path(__file__).resolve().parents[1]
HERMES_REPORT_SH = ROOT / 'skills' / 'revenium' / 'scripts' / 'hermes-report.sh'

CEILING = 4096

TOP_LEVEL_ORDER = (
    'schema_version', 'source', 'status', 'session', 'failure_reason',
    'outcome_basis', 'corrected', 'correction_sequence', 'value', 'basis',
    'costs', 'estimator', 'metadata_truncated',
)

V1_ONLY_KEYS = (
    'assessment_schema_version', 'reportability_status', 'double_counting_group',
    'value_low', 'value_base', 'value_high', 'net_value', 'supplied_costs',
    'cost_coverage', 'evidence_class', 'economic_mechanism', 'assumptions',
    'evaluator', 'evaluator_version', 'model', 'inference_provider',
    'inference_address_class', 'prompt_version', 'taxonomy_version',
    'policy_version', 'attribution_fraction', 'attribution_basis',
    'bounds_source', 'evidence_class_authority',
)

ALLOWED_BASIS_KEYS = {
    'evidence', 'mechanism', 'role', 'hours_saved', 'hourly_rate',
    'confidence', 'study',
}

# The contract's expected blob for the golden record (reportable,
# CUSTOMER_CONFIGURED, authority 'valuation', no study).
EXPECTED_GOLDEN_BLOB = (
    '{"schema_version":2,"source":"test","status":"reportable","session":"g38-sid-002",'
    '"value":{"reported":446.25,"low":446.25,"base":525.0,"high":603.75,"currency":"USD","net":421.25},'
    '"basis":{"evidence":"CUSTOMER_CONFIGURED","mechanism":"labor_substitution",'
    '"role":"senior software engineer","hours_saved":3.5,"hourly_rate":150.0,"confidence":0.8},'
    '"costs":{"subtracted":{"human_review":25.0},'
    '"not_counted":["rework_or_error","handoff","training_or_change"],"ai_cost":"metered_separately"},'
    '"estimator":{"name":"llm","model":"unknown","provider":"openrouter","endpoint":"public",'
    '"versions":{"prompt":1,"taxonomy":1,"policy":1,"evaluator":"v1"}}}'
)


def _walk_keys(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield k
            yield from _walk_keys(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk_keys(v)


def _walk_dicts(obj):
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from _walk_dicts(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk_dicts(v)


def _golden_record(**overrides):
    base = p38._sidecar_record(
        'g38-sid-002', reportability_status='reportable',
        evidence_class='CUSTOMER_CONFIGURED', evidence_class_authority='valuation')
    base.update(overrides)
    return base


def _candidate_record(**overrides):
    """What the sidecar re-read leaves of a candidate record: the value family
    stripped (hermes-report.sh's _VALUE_OMIT_FAMILY), everything else kept."""
    rec = p38._sidecar_record('g38-sid-002', reportability_status='candidate',
                              evidence_class='MODEL_ESTIMATED')
    for key in ('value_low', 'value_base', 'value_high', 'bounds_source',
                'currency', 'estimated_value', 'assumptions', 'net_value',
                'attribution_fraction', 'attribution_basis'):
        rec.pop(key, None)
    rec.update(overrides)
    return rec


class _ForwarderCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.script_text = HERMES_REPORT_SH.read_text()
        cls.body = p46._extract_outcome_metadata_heredoc(cls.script_text)
        assert cls.body is not None, 'outcome_metadata heredoc anchor moved'

    def _raw(self, assessment, source='test', status='SUCCESS', failure_reason='',
             value_sent=None, outcome_basis=None):
        env = p46._forwarder_env(assessment, source=source, status=status,
                                 failure_reason=failure_reason)
        if value_sent is not None:
            env['OUTCOME_VALUE_SENT'] = value_sent
        if outcome_basis is not None:
            env['OUTCOME_BASIS'] = outcome_basis
        result = p46._run_forwarder(self.body, env)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.rstrip('\n')

    def _meta(self, assessment, **kwargs):
        return json.loads(self._raw(assessment, **kwargs))


class ExactShapeTests(_ForwarderCase):
    def test_golden_record_yields_exactly_the_contract_blob(self):
        self.assertEqual(
            EXPECTED_GOLDEN_BLOB, self._raw(_golden_record(), value_sent='446.25'))

    def test_output_is_one_compact_line_within_the_ceiling(self):
        raw = self._raw(_golden_record(), value_sent='446.25')
        self.assertNotIn('\n', raw)
        self.assertNotIn(', ', raw)
        self.assertNotIn(': ', raw)
        self.assertLessEqual(len(raw.encode('utf-8')), CEILING)

    def test_schema_version_is_first_and_top_level_order_is_the_contract(self):
        meta = self._meta(_golden_record(), value_sent='446.25')
        keys = list(meta)
        self.assertEqual('schema_version', keys[0])
        self.assertEqual(2, meta['schema_version'])
        self.assertEqual(sorted(keys, key=TOP_LEVEL_ORDER.index), keys)

    def test_group_key_order(self):
        meta = self._meta(_golden_record(), value_sent='446.25')
        self.assertEqual(
            ['reported', 'low', 'base', 'high', 'currency', 'net'], list(meta['value']))
        self.assertEqual(
            ['evidence', 'mechanism', 'role', 'hours_saved', 'hourly_rate', 'confidence'],
            list(meta['basis']))
        self.assertEqual(['subtracted', 'not_counted', 'ai_cost'], list(meta['costs']))
        self.assertEqual(
            ['name', 'model', 'provider', 'endpoint', 'versions'], list(meta['estimator']))
        self.assertEqual(
            ['prompt', 'taxonomy', 'policy', 'evaluator'], list(meta['estimator']['versions']))

    def test_no_v1_only_key_at_the_top_level(self):
        meta = self._meta(_golden_record(), value_sent='446.25')
        for key in V1_ONLY_KEYS:
            with self.subTest(key=key):
                self.assertNotIn(key, meta)

    def test_authority_bounds_source_and_rate_source_appear_nowhere(self):
        for rec in (_golden_record(), _golden_record(evidence_class_authority='evaluator'),
                    _candidate_record()):
            keys = set(_walk_keys(self._meta(rec, value_sent='446.25')))
            for banned in ('evidence_class_authority', 'bounds_source', 'rate_source',
                           'included', 'authority'):
                with self.subTest(banned=banned):
                    self.assertNotIn(banned, keys)

    def test_authority_changes_nothing_on_the_wire(self):
        a = self._meta(_golden_record(evidence_class_authority='valuation'), value_sent='446.25')
        b = self._meta(_golden_record(evidence_class_authority='evaluator'), value_sent='446.25')
        self.assertEqual(a, b)
        c = self._meta(_golden_record(evidence_class='ACTIVITY_MEASURED',
                                      evidence_class_authority='evaluator'),
                       value_sent='446.25')
        self.assertEqual(a['basis'].keys(), c['basis'].keys())
        self.assertEqual('ACTIVITY_MEASURED', c['basis']['evidence'])

    def test_legacy_label_reaches_the_wire_as_the_new_label(self):
        meta = self._meta(_golden_record(evidence_class='MODEL_ESTIMATED_DEMO'))
        self.assertEqual('MODEL_ESTIMATED', meta['basis']['evidence'])

    def test_both_heredocs_declare_the_same_alias_dict(self):
        import ast
        found = re.findall(r"_LEGACY_EVIDENCE_CLASS_ALIASES = (\{[^}]*\})", self.script_text)
        self.assertEqual(2, len(found), 'one alias dict per heredoc (sidecar re-read, outcome_metadata)')
        self.assertEqual(ast.literal_eval(found[0]), ast.literal_eval(found[1]))
        self.assertEqual({'MODEL_ESTIMATED_DEMO': 'MODEL_ESTIMATED'}, ast.literal_eval(found[0]))


class ValueReportedTests(_ForwarderCase):
    def test_reported_present_only_when_the_flag_was_sent(self):
        sent = self._meta(_golden_record(), value_sent='446.25')
        self.assertEqual(446.25, sent['value']['reported'])
        for unsent in (None, ''):
            with self.subTest(unsent=unsent):
                meta = self._meta(_golden_record(), value_sent=unsent)
                self.assertNotIn('reported', meta['value'])
                self.assertEqual(446.25, meta['value']['low'])
                self.assertEqual('USD', meta['value']['currency'])

    def test_reported_follows_the_sent_string_not_the_record(self):
        meta = self._meta(_golden_record(), value_sent='100.5')
        self.assertEqual(100.5, meta['value']['reported'])

    def test_unparseable_sent_value_is_dropped_not_fatal(self):
        meta = self._meta(_golden_record(), value_sent='not-a-number')
        self.assertNotIn('reported', meta['value'])

    def test_currency_must_be_three_capital_letters(self):
        for raw, expect in (('usd', 'USD'), (' eur ', 'EUR'), ('USDX', None), ('US', None),
                            ('U$D', None), ('', None), (5, None), (None, None)):
            with self.subTest(raw=raw):
                meta = self._meta(_golden_record(currency=raw))
                if expect is None:
                    self.assertNotIn('currency', meta['value'])
                else:
                    self.assertEqual(expect, meta['value']['currency'])


class CostsAndNetTests(_ForwarderCase):
    def _costs(self, supplied, **coverage):
        cov = {'included': [], 'known_zero': [], 'unknown': [], 'excluded': []}
        cov.update(coverage)
        return _golden_record(supplied_costs=supplied, cost_coverage=cov, net_value=500.0)

    def test_empty_supplied_costs_gives_empty_subtracted_and_no_net(self):
        meta = self._meta(self._costs({}), value_sent='446.25')
        self.assertEqual({}, meta['costs']['subtracted'])
        self.assertNotIn('net', meta['value'])
        self.assertNotIn('known_zero', meta['costs'])
        self.assertNotIn('not_counted', meta['costs'])

    def test_a_zero_cost_is_listed_but_does_not_produce_net(self):
        meta = self._meta(self._costs({'human_review': 0.0}, known_zero=['human_review']),
                          value_sent='446.25')
        self.assertEqual({'human_review': 0.0}, meta['costs']['subtracted'])
        self.assertEqual(['human_review'], meta['costs']['known_zero'])
        self.assertNotIn('net', meta['value'])

    def test_a_real_cost_produces_net_from_the_reported_value(self):
        # net is value.reported less the subtracted costs, never the
        # sidecar's base-derived net_value (500.0 here): a net above the
        # reported value would read as more value than Revenium displays.
        meta = self._meta(self._costs({'human_review': 25.0}), value_sent='446.25')
        self.assertEqual(421.25, meta['value']['net'])
        self.assertLessEqual(meta['value']['net'], meta['value']['reported'])

    def test_net_subtracts_every_cost_exactly(self):
        meta = self._meta(self._costs({'human_review': 0.1, 'handoff': 0.2}),
                          value_sent='0.3')
        self.assertEqual(0.0, meta['value']['net'])

    def test_no_reported_value_means_no_net(self):
        meta = self._meta(self._costs({'human_review': 25.0}))
        self.assertNotIn('reported', meta.get('value', {}))
        self.assertNotIn('net', meta.get('value', {}))

    def test_net_may_go_negative_when_costs_exceed_the_value(self):
        meta = self._meta(self._costs({'human_review': 25.0}), value_sent='10')
        self.assertEqual(-15.0, meta['value']['net'])

    def test_unknown_categories_and_bad_amounts_are_filtered(self):
        meta = self._meta(self._costs(
            {'human_review': 5, 'mystery': 9.0, 'handoff': 'abc'},
            unknown=['handoff', 'mystery'], excluded=['something_else']))
        self.assertEqual({'human_review': 5.0}, meta['costs']['subtracted'])
        self.assertEqual(['handoff'], meta['costs']['not_counted'])
        self.assertNotIn('ai_cost', meta['costs'])

    def test_a_record_with_no_cost_fields_ships_no_costs_group(self):
        rec = _golden_record()
        rec.pop('supplied_costs')
        rec.pop('cost_coverage')
        self.assertNotIn('costs', self._meta(rec))

    def test_included_is_dropped(self):
        meta = self._meta(self._costs({'human_review': 25.0}, included=['human_review']))
        self.assertNotIn('included', meta['costs'])


class ReportabilityStripTests(_ForwarderCase):
    def test_candidate_ships_no_value_group_and_no_assumption_basis_keys(self):
        meta = self._meta(_candidate_record())
        self.assertNotIn('value', meta)
        for key in ('role', 'hours_saved', 'hourly_rate'):
            self.assertNotIn(key, meta['basis'])
        self.assertEqual('candidate', meta['status'])
        self.assertEqual('MODEL_ESTIMATED', meta['basis']['evidence'])
        self.assertEqual('labor_substitution', meta['basis']['mechanism'])
        self.assertIn('confidence', meta['basis'])
        self.assertIn('costs', meta)
        self.assertIn('estimator', meta)

    def test_correction_ships_corrected_sequence_value_and_attribution(self):
        rec = p38._correction_sidecar_record('g38-sid-002', sequence=2)
        meta = self._meta(rec)
        self.assertIs(True, meta['corrected'])
        self.assertEqual(2, meta['correction_sequence'])
        self.assertEqual(100.0, meta['value']['low'])
        self.assertEqual({'fraction': 0.15, 'basis': '15% per policy REV-2024-03'},
                         meta['value']['attribution'])
        self.assertNotIn('basis', meta)
        self.assertEqual(2, meta['schema_version'])
        # key order of the base keys
        self.assertEqual(sorted(meta, key=TOP_LEVEL_ORDER.index), list(meta))

    def test_an_original_assessment_never_carries_the_corrected_marker(self):
        meta = self._meta(_golden_record())
        self.assertNotIn('corrected', meta)
        self.assertNotIn('correction_sequence', meta)

    def test_fraction_without_a_basis_drops_the_attribution(self):
        rec = p38._correction_sidecar_record('g38-sid-002')
        rec.pop('attribution_basis')
        meta = self._meta(rec)
        self.assertNotIn('attribution', meta['value'])
        rec['attribution_basis'] = '   '
        self.assertNotIn('attribution', self._meta(rec)['value'])

    def test_out_of_range_or_bool_fraction_drops_the_attribution(self):
        for bad in (1.5, -0.1, True, float('nan'), 'x'):
            with self.subTest(bad=repr(bad)):
                rec = p38._correction_sidecar_record('g38-sid-002', attribution_fraction=bad)
                self.assertNotIn('attribution', self._meta(rec)['value'])


class BaseOnlyBlobTests(_ForwarderCase):
    def test_no_assessment_is_exactly_source_and_no_schema_version(self):
        self.assertEqual('{"source":"test"}', self._raw(None))

    def test_failed_arc_keeps_the_v1_base_bytes(self):
        self.assertEqual(
            '{"source":"test","failure_reason":"boom"}',
            self._raw(None, status='FAILED', failure_reason='boom'))

    def test_undetermined_cancelled_arc_keeps_the_v1_base_bytes(self):
        meta = self._meta(None, status='CANCELLED', outcome_basis='undetermined')
        self.assertEqual(['source', 'failure_reason', 'outcome_basis'], list(meta))
        self.assertEqual('undetermined', meta['outcome_basis'])

    def test_malformed_assessment_degrades_to_the_base_blob(self):
        env = p46._forwarder_env(None, source='test')
        env['ASSESSMENT_JSON'] = '{not json'
        out = p46._run_forwarder(self.body, env)
        self.assertEqual(0, out.returncode, out.stderr)
        self.assertEqual('{"source":"test"}', out.stdout.strip())

    def test_nothing_to_send_prints_nothing(self):
        env = p46._forwarder_env(None, source='')
        out = p46._run_forwarder(self.body, env)
        self.assertEqual('', out.stdout.strip())


class AllowListTests(_ForwarderCase):
    def test_out_of_set_mechanism_and_endpoint_are_dropped(self):
        meta = self._meta(_golden_record(economic_mechanism='telepathy',
                                         inference_address_class='intranet'))
        self.assertNotIn('mechanism', meta['basis'])
        self.assertNotIn('endpoint', meta['estimator'])

    def test_study_needs_both_halves(self):
        both = self._meta(_golden_record(study_id='study-9', study_version=3))
        self.assertEqual({'id': 'study-9', 'version': 3}, both['basis']['study'])
        for sid, ver in (('', 3), ('study-9', 0), ('study-9', True), (None, 3),
                         ('study-9', 1.5), ('  ', 2)):
            with self.subTest(sid=sid, ver=ver):
                meta = self._meta(_golden_record(study_id=sid, study_version=ver))
                self.assertNotIn('study', meta['basis'])

    def test_study_id_is_sliced(self):
        meta = self._meta(_golden_record(study_id='s' * 300, study_version=1))
        self.assertEqual('s' * 100, meta['basis']['study']['id'])

    def test_evidence_is_sliced_to_32(self):
        meta = self._meta(_golden_record(evidence_class='E' * 80))
        self.assertEqual('E' * 32, meta['basis']['evidence'])

    def test_free_text_slices(self):
        meta = self._meta(_golden_record(
            evaluator='n' * 200, model='m' * 200, inference_provider='p' * 200,
            evaluator_version='v' * 200, double_counting_group='g' * 200,
            reportability_status='r' * 200))
        self.assertEqual('n' * 64, meta['estimator']['name'])
        self.assertEqual('m' * 64, meta['estimator']['model'])
        self.assertEqual('p' * 32, meta['estimator']['provider'])
        self.assertEqual('v' * 16, meta['estimator']['versions']['evaluator'])
        self.assertEqual('g' * 64, meta['session'])
        self.assertEqual('r' * 16, meta['status'])

    def test_role_is_sliced_and_blank_role_is_dropped(self):
        assumptions = {'inferred_role': 'r' * 200, 'estimated_hours_saved': 1.0,
                       'assumed_loaded_rate': 10.0}
        self.assertEqual('r' * 60, self._meta(_golden_record(assumptions=assumptions))['basis']['role'])
        assumptions['inferred_role'] = '   '
        self.assertNotIn('role', self._meta(_golden_record(assumptions=assumptions))['basis'])

    def test_bool_versions_are_not_numbers(self):
        meta = self._meta(_golden_record(prompt_version=True, taxonomy_version=2))
        self.assertNotIn('prompt', meta['estimator']['versions'])
        self.assertEqual(2, meta['estimator']['versions']['taxonomy'])


class ProseGuardTests(_ForwarderCase):
    """D-04/C-3: the evaluator's own sentences never reach the wire, and the
    wire `basis` is a different, allow-listed object."""

    CANARY = 'CANARY-PROSE-DO-NOT-SHIP'

    def test_prose_fields_never_reach_the_blob(self):
        rec = _golden_record(
            basis=f'{self.CANARY} basis sentence',
            candidate_downstream_outcome=f'{self.CANARY} outcome',
            counterfactual_assumption=f'{self.CANARY} counterfactual')
        raw = self._raw(rec, value_sent='446.25')
        self.assertNotIn(self.CANARY, raw)

    def test_wire_basis_is_a_dict_of_allowed_keys_only(self):
        for rec in (_golden_record(basis='free prose'), _candidate_record(),
                    _golden_record(study_id='s', study_version=1)):
            meta = self._meta(rec, value_sent='446.25')
            self.assertIsInstance(meta['basis'], dict)
            self.assertLessEqual(set(meta['basis']), ALLOWED_BASIS_KEYS)

    def test_the_heredoc_never_reads_the_prose_keys(self):
        for key in ('basis', 'candidate_downstream_outcome', 'counterfactual_assumption'):
            with self.subTest(key=key):
                self.assertNotIn(f"record.get('{key}')", self.body)
                self.assertNotIn(f'record.get("{key}")', self.body)
                self.assertNotIn(f"record['{key}']", self.body)


class BoundedEmitTests(_ForwarderCase):
    def _heavy_record(self, **overrides):
        rec = _golden_record(
            model='m' * 64, evaluator='n' * 64, inference_provider='p' * 32,
            double_counting_group='g' * 64, study_id='s' * 100, study_version=4,
            attribution_fraction=0.5, attribution_basis='b' * 500,
            supplied_costs={'human_review': 10.0, 'rework_or_error': 5.0,
                            'handoff': 2.0, 'training_or_change': 1.0},
            cost_coverage={'included': ['human_review'], 'known_zero': ['handoff'],
                           'unknown': ['rework_or_error', 'training_or_change'],
                           'excluded': ['metered_ai_cost']})
        rec.update(overrides)
        return rec

    def _assert_no_empty_groups(self, meta):
        for d in _walk_dicts(meta):
            for k, v in d.items():
                if isinstance(v, dict) and k != 'subtracted':
                    self.assertTrue(v, f'empty group {k!r} emitted')

    def test_under_the_ceiling_nothing_is_shed_and_nothing_is_marked(self):
        meta = self._meta(self._heavy_record(), value_sent='446.25')
        self.assertNotIn('metadata_truncated', meta)
        self.assertIn('attribution', meta['value'])

    def test_tier_one_sheds_the_value_tier_and_keeps_provenance(self):
        # 3200 chars of failure_reason leaves the base + provenance under the
        # ceiling but the whole value tier over it.
        meta = self._meta(self._heavy_record(), status='FAILED',
                          failure_reason='r' * 3200, value_sent='446.25')
        self.assertIs(True, meta['metadata_truncated'])
        for gone in ('value', 'costs'):
            self.assertNotIn(gone, meta)
        for gone in ('role', 'hours_saved', 'hourly_rate'):
            self.assertNotIn(gone, meta['basis'])
        for kept in ('evidence', 'mechanism', 'confidence', 'study'):
            self.assertIn(kept, meta['basis'])
        self.assertIn('estimator', meta)
        self.assertIn('status', meta)
        self.assertIn('session', meta)
        self.assertEqual('r' * 3200, meta['failure_reason'])
        self.assertEqual(2, meta['schema_version'])
        self._assert_no_empty_groups(meta)
        raw = json.dumps(meta, separators=(',', ':'))
        self.assertLessEqual(len(raw.encode('utf-8')), CEILING)

    def test_tier_two_sheds_provenance_but_never_the_base_keys(self):
        rec = self._heavy_record(kind='correction', sequence=3)
        meta = self._meta(rec, status='FAILED', failure_reason='r' * 3900,
                          value_sent='446.25')
        self.assertIs(True, meta['metadata_truncated'])
        for gone in ('value', 'costs', 'basis', 'estimator', 'status', 'session',
                     'correction_sequence'):
            self.assertNotIn(gone, meta)
        for kept in ('schema_version', 'source', 'failure_reason', 'corrected'):
            self.assertIn(kept, meta)
        self._assert_no_empty_groups(meta)
        raw = json.dumps(meta, separators=(',', ':'))
        self.assertLessEqual(len(raw.encode('utf-8')), CEILING)

    def test_marker_is_set_only_when_something_was_removed(self):
        # Over the ceiling purely through failure_reason: no assessment, so
        # there is nothing to shed and nothing may claim to have been shed.
        meta = self._meta(None, status='FAILED', failure_reason='x' * 5000)
        self.assertNotIn('metadata_truncated', meta)
        self.assertEqual(5000, len(meta['failure_reason']))

    def test_a_group_left_empty_by_shedding_is_removed(self):
        rec = {'value_low': 1.0, 'currency': 'USD'}
        meta = self._meta(rec, status='FAILED', failure_reason='r' * 4090)
        self.assertNotIn('value', meta)
        self._assert_no_empty_groups(meta)
        self.assertIs(True, meta['metadata_truncated'])

    def test_metadata_truncated_is_the_last_key(self):
        meta = self._meta(self._heavy_record(), status='FAILED', failure_reason='r' * 3200)
        self.assertEqual('metadata_truncated', list(meta)[-1])

    def test_tier_tuples_are_dotted_path_strings(self):
        import ast
        tree = ast.parse(self.body)
        found = {}
        for node in tree.body:
            if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
                if node.targets[0].id in ('_VALUE_FAMILY_META_KEYS', '_PROVENANCE_FAMILY_META_KEYS'):
                    found[node.targets[0].id] = ast.literal_eval(node.value)
        self.assertEqual(
            ('value', 'value.attribution', 'basis.role', 'basis.hours_saved',
             'basis.hourly_rate', 'costs'), found['_VALUE_FAMILY_META_KEYS'])
        self.assertEqual(
            ('basis.evidence', 'basis.mechanism', 'basis.confidence', 'basis.study',
             'estimator', 'session', 'status', 'correction_sequence'),
            found['_PROVENANCE_FAMILY_META_KEYS'])


class EndToEndTests(unittest.TestCase):
    """One real hermes-report.sh tick: value.reported must equal the exact
    --outcome-value the same call sent."""

    _run_one_outcome = p38.TestPhase38ReporterPath._run_one_outcome
    _metadata_value = staticmethod(p38.TestPhase38ReporterPath._metadata_value)

    def test_reported_equals_the_outcome_value_flag(self):
        argv = self._run_one_outcome(
            'nck-v2-sid', 'nck-v2-job', 'SUCCESS',
            sidecar=p38._sidecar_record(
                'nck-v2-job', reportability_status='reportable',
                evidence_class='CUSTOMER_CONFIGURED'))
        sent = argv[argv.index('--outcome-value') + 1]
        meta = json.loads(self._metadata_value(argv))
        self.assertEqual(2, meta['schema_version'])
        self.assertEqual(float(sent), meta['value']['reported'])
        self.assertEqual(446.25, meta['value']['reported'])

    def test_no_reported_when_the_cli_cannot_take_the_flag(self):
        argv = self._run_one_outcome(
            'nck-v2-sid2', 'nck-v2-job2', 'SUCCESS', outcome_value_capable=False,
            sidecar=p38._sidecar_record(
                'nck-v2-job2', reportability_status='reportable',
                evidence_class='CUSTOMER_CONFIGURED'))
        self.assertNotIn('--outcome-value', argv)
        meta = json.loads(self._metadata_value(argv))
        self.assertNotIn('reported', meta['value'])
        self.assertEqual(446.25, meta['value']['low'])

    def test_candidate_tick_ships_no_value_group(self):
        argv = self._run_one_outcome(
            'nck-v2-sid3', 'nck-v2-job3', 'SUCCESS',
            sidecar=p38._sidecar_record('nck-v2-job3'))  # candidate by default
        self.assertNotIn('--outcome-value', argv)
        meta = json.loads(self._metadata_value(argv))
        self.assertNotIn('value', meta)
        self.assertEqual('candidate', meta['status'])
        self.assertEqual('MODEL_ESTIMATED', meta['basis']['evidence'])

    def test_a_tick_without_a_sidecar_stays_byte_identical_to_v1(self):
        argv = self._run_one_outcome('nck-v2-sid4', 'nck-v2-job4', 'SUCCESS')
        self.assertEqual({'source': 'test'}, json.loads(self._metadata_value(argv)))


if __name__ == '__main__':
    unittest.main()
