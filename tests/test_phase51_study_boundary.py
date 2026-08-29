"""Phase 51 MECH-05 — a study reference is not a mechanism producer.

Assertion-only: no production change is expected. _resolve_economic_mechanism
reads raw["economic_mechanism"] and nothing else, and _resolve_study_reference
takes `cfg`, not `raw` -- so the two cannot cross today.

The requirement exists because THIS phase made mechanisms operator-settable,
and that is exactly the change that could erode EGV-13's boundary: a cohort
estimate must not be represented as individually observed. These tests pin
the separation so a later phase cannot quietly wire a study into a mechanism.
"""

import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLASSIFIER = ROOT / 'skills' / 'revenium' / 'plugins' / 'revenium-classifier' / 'classifier.py'

_spec = importlib.util.spec_from_file_location('_p51_classifier', CLASSIFIER)
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)

UNKNOWN = mod.ECONOMIC_MECHANISM_UNKNOWN


class StudyReferenceIsNotAMechanismProducer(unittest.TestCase):

    def test_study_reference_alone_yields_no_mechanism(self):
        for raw in (
            {'study_id': 'STUDY-1', 'study_version': 3},
            {'studyId': 'STUDY-1', 'studyVersion': 3},
            {'study_id': 'STUDY-1'},
            {'study_version': 7},
        ):
            with self.subTest(raw=raw):
                self.assertEqual(mod._resolve_economic_mechanism(raw), UNKNOWN)

    def test_study_reference_does_not_override_a_declared_mechanism(self):
        """Adding a study reference to a record that already carries a
        mechanism must not change it -- in either direction."""
        raw = {
            'economic_mechanism': 'labor_substitution',
            'study_id': 'STUDY-1',
            'study_version': 3,
        }
        self.assertEqual(mod._resolve_economic_mechanism(raw), 'labor_substitution')

    def test_study_reference_cannot_reach_an_operator_only_mechanism(self):
        """The three operator-only mechanisms stay unreachable from `raw`
        whatever else it carries -- D-01's structural guarantee."""
        for m in ('quality_decision_improvement', 'risk_avoidance', 'incremental_revenue'):
            with self.subTest(mechanism=m):
                raw = {'economic_mechanism': m, 'study_id': 'S', 'study_version': 1}
                self.assertEqual(mod._resolve_economic_mechanism(raw), UNKNOWN)

    def test_resolvers_read_disjoint_inputs(self):
        """_resolve_economic_mechanism takes `raw` (untrusted evaluator
        output); _resolve_study_reference takes `cfg` (operator config).
        Different parameter, different trust domain -- the separation is
        structural, not conventional."""
        import inspect
        mech = list(inspect.signature(mod._resolve_economic_mechanism).parameters)
        study = list(inspect.signature(mod._resolve_study_reference).parameters)
        self.assertEqual(mech, ['raw'])
        self.assertNotIn('raw', study)

    def test_mechanism_resolver_reads_exactly_one_key_off_raw(self):
        """A guard against a later phase widening what `raw` may contribute:
        the function body reads one key and no other."""
        import re
        src = inspect_source = inspect_src = None
        import inspect as _i
        src = _i.getsource(mod._resolve_economic_mechanism)
        body = src.split('"""')[-1]
        keys = set(re.findall(r'raw\.get\(\s*["\']([a-z_]+)["\']', body))
        keys |= set(re.findall(r'raw\[\s*["\']([a-z_]+)["\']\s*\]', body))
        self.assertEqual(keys, {'economic_mechanism'})


if __name__ == '__main__':
    unittest.main()
