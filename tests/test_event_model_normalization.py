"""EVT-08: the event path's `--model` must be byte-identical to legacy's.

Tonight's canary (2026-08-17) billed session `20260817_213057_3a319e` on both
paths in the same tick and the two disagreed on the model name:

    LEGACY  model=fireworks/models/glm-5p2           cost=0.009937  PRICED
    EVENT   model=accounts/fireworks/models/glm-5p2  cost=0         UNPRICED

Revenium's price catalog is keyed on the NORMALIZED name, so every event-path
row priced at zero. `api-event-report.sh` now mirrors legacy's transformation
as `_normalize_model`.

Two tests, deliberately NOT redundant:

  * TestModelNormalizationEquivalence pins the TRANSFORMATION. It EXTRACTS both
    implementations from their source files at test time and runs them head to
    head, so drift on EITHER side fails the build. Re-typing either one into
    this file would recreate the exact defect this fixes: two copies of one
    rule, drifting apart.
  * TestEventPathModelRegression pins the WIRING — that field 3 of the pipe row
    actually calls the helper. Only this one can see a call site that stopped
    calling it. (Mutation-verified: reverting the call site leaves the
    equivalence test green and fails this one, on the model value.)
"""
import json
import os
import re
import shlex
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests._compat_helpers import (
    argv_to_flags,
    build_shim,
    run_script,
    SCRIPTS_DIR,
)

LEGACY_SCRIPT = SCRIPTS_DIR / 'hermes-report.sh'
EVENT_SCRIPT = SCRIPTS_DIR / 'api-event-report.sh'

# Legacy's whole `clean_model=$(...)` assignment, from the opening
# `python3 -c "` through its `|| echo "${model}"` fallback.
LEGACY_PATTERN = re.compile(
    r'clean_model=\$\(python3 -c ".*?" 2>/dev/null \|\| echo "\$\{model\}"\)',
    re.DOTALL,
)

# The `def _normalize_model(` line plus its indented body (blank lines allowed).
EVENT_PATTERN = re.compile(
    r'^def _normalize_model\(model\):\n(?:(?:[ \t]+.*)?\n)+',
    re.MULTILINE,
)

# REAL model strings observed on this fleet's state.db — not invented ones.
# (input, expected, why this row is in the table)
MODEL_TABLE = [
    ('accounts/fireworks/models/glm-5p2', 'fireworks/models/glm-5p2',
     'the defect itself; also the multi-slash case — only the FIRST segment is stripped'),
    ('glm-4.6', 'glm-4.6',
     'bare name, no slash, no prefix: the no-op path'),
    ('openai/gpt-4o-mini', 'gpt-4o-mini',
     'the ordinary single-slash case'),
    ('cohere/north-mini-code:free', 'north-mini-code:free',
     'first segment is a MEANINGFUL provider and is discarded anyway — lossy, and matched on purpose'),
    ('nvidia/nemotron-3-nano-30b-a3b:free', 'nemotron-3-nano-30b-a3b:free',
     'second lossy-first-segment case, with a :free suffix that must survive untouched'),
    ('anthropic.claude-sonnet-4-6', 'claude-sonnet-4-6',
     'dot-prefix path, no slash involved'),
    ('global.anthropic.claude-sonnet-4-6', 'claude-sonnet-4-6',
     'TWO prefixes stripped in ONE pass — works only because global. precedes anthropic. in the tuple'),
    ('claude-sonnet-4-6', 'claude-sonnet-4-6',
     "the event golden's value: proves the golden is a no-op and must not be edited"),
    ('', '',
     'degenerate input; both sides must agree on empty, not diverge into a fallback'),
]

# DELIBERATE OMISSION, not a gap: a quote-bearing model name (e.g.
# `it's-a-model`) is the one input on which the two sides genuinely diverge.
# Legacy's `model = '${model}'` is SHELL-INTERPOLATED, so a quote makes that
# invalid Python, `python3` exits non-zero, and `|| echo "${model}"` returns
# the RAW string — while the event path, fed by json.loads inside a quoted
# heredoc, normalizes it correctly. Excluded because no real model name
# contains a quote, and because legacy is the lossy side there; this change
# does not touch legacy.


def _write_jsonl(path, records):
    with open(path, 'w', encoding='utf-8') as f:
        for r in records:
            f.write(json.dumps(r, separators=(',', ':')) + '\n')


class TestModelNormalizationEquivalence(unittest.TestCase):
    """Both implementations, extracted from source and run head to head."""

    @classmethod
    def setUpClass(cls):
        cls._tmpdir = tempfile.mkdtemp(prefix='gsd-wej-equivalence-')

        legacy_src = LEGACY_SCRIPT.read_text(encoding='utf-8')
        legacy_matches = LEGACY_PATTERN.findall(legacy_src)
        # Exactly one, always. Zero or two means the legacy side changed
        # shape, and this test must fail loudly rather than silently degrade
        # into a no-op that pins nothing.
        assert len(legacy_matches) == 1, (
            f'expected exactly 1 clean_model assignment in {LEGACY_SCRIPT}, '
            f'found {len(legacy_matches)}'
        )
        cls.legacy_assignment = legacy_matches[0]

        # Built by CONCATENATION, never an f-string: the extracted text
        # contains ${model} and ${clean_model}, and an f-string would force
        # brace-escaping the very text whose fidelity is the point. Run under
        # REAL bash so shell interpolation is exercised, not simulated.
        wrapper = (
            '#!/usr/bin/env bash\n'
            'set -uo pipefail\n'
            'model="$1"\n'
            + cls.legacy_assignment + '\n'
            'printf \'%s\' "${clean_model}"\n'
        )
        cls.legacy_wrapper = os.path.join(cls._tmpdir, 'legacy_normalize.sh')
        with open(cls.legacy_wrapper, 'w', encoding='utf-8') as f:
            f.write(wrapper)

        event_src = EVENT_SCRIPT.read_text(encoding='utf-8')
        event_matches = EVENT_PATTERN.findall(event_src)
        assert len(event_matches) == 1, (
            f'expected exactly 1 _normalize_model definition in {EVENT_SCRIPT}, '
            f'found {len(event_matches)}'
        )
        cls.event_source = EVENT_PATTERN.search(event_src).group(0)
        namespace = {}
        exec(cls.event_source, namespace)  # noqa: S102 - repo-owned source
        # Held in a dict, not as a class attribute: a bare function assigned
        # to a class binds as a method and would receive `self` as its first
        # positional argument.
        cls.event_ns = namespace

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls._tmpdir, ignore_errors=True)

    def _legacy(self, model):
        proc = subprocess.run(
            ['bash', self.legacy_wrapper, model],
            capture_output=True, text=True, timeout=60,
        )
        self.assertEqual(
            proc.returncode, 0,
            f'legacy wrapper failed for {model!r}: {proc.stdout}{proc.stderr}'
        )
        return proc.stdout

    def test_legacy_assignment_extracted_exactly_once(self):
        self.assertIn('clean_model=$(python3 -c "', self.legacy_assignment)
        self.assertIn("model.split('/', 1)[1]", self.legacy_assignment)
        self.assertIn(
            "('global.', 'anthropic.', 'openai.', 'google.', 'x-ai.')",
            self.legacy_assignment,
            'the prefix tuple ORDER is load-bearing: global. must precede '
            'anthropic. or global.anthropic.* only loses global.'
        )

    def test_event_helper_extracted_exactly_once(self):
        self.assertTrue(callable(self.event_ns['_normalize_model']))

    def test_event_path_matches_legacy_over_real_model_strings(self):
        for model, expected, why in MODEL_TABLE:
            with self.subTest(model=model, why=why):
                legacy_out = self._legacy(model)
                event_out = self.event_ns['_normalize_model'](model)
                self.assertEqual(
                    event_out, legacy_out,
                    f'EVT-08 divergence for input {model!r} ({why}): '
                    f'event={event_out!r} legacy={legacy_out!r}'
                )
                # The expected column pins INTENT — equality alone would pass
                # if both sides were wrong in the same way.
                self.assertEqual(
                    legacy_out, expected,
                    f'legacy output for {model!r} ({why}) is {legacy_out!r}, '
                    f'expected {expected!r}'
                )
                self.assertEqual(
                    event_out, expected,
                    f'event output for {model!r} ({why}) is {event_out!r}, '
                    f'expected {expected!r}'
                )


class TestEventPathModelRegression(unittest.TestCase):
    """A live run of the real script must ship the normalized --model."""

    def test_event_meter_completion_ships_normalized_model(self):
        tmpdir = tempfile.mkdtemp(prefix='gsd-wej-regression-')
        try:
            hermes_home = os.path.join(tmpdir, 'hh')
            state_dir = os.path.join(hermes_home, 'state', 'revenium')
            spool_dir = os.path.join(state_dir, 'api-events')
            markers_dir = os.path.join(state_dir, 'markers')
            ready_dir = os.path.join(markers_dir, '.ready')
            os.makedirs(spool_dir, mode=0o700)
            os.makedirs(markers_dir, mode=0o700)
            os.makedirs(ready_dir, mode=0o700)

            shim_home = os.path.join(tmpdir, 'home')
            bin_dir = os.path.join(shim_home, '.local', 'bin')
            os.makedirs(bin_dir)
            meter_log = os.path.join(tmpdir, 'meter.log')
            inv_log = os.path.join(tmpdir, 'inv.log')
            shim = os.path.join(bin_dir, 'revenium')

            sid = 'wej-event-sid-001'
            arid = 'wej-event-arid-001'

            # Settle gate satisfied by the sentinel, not by age.
            Path(ready_dir, sid).touch()

            # `model` is deliberately different from `response_model`, so this
            # record also keeps proving --model ships from response_model.
            _write_jsonl(os.path.join(spool_dir, f'{sid}.jsonl'), [{
                'v': 1, 'sid': sid, 'api_request_id': arid,
                'ts': 1715514000.5, 'ended_at': 1715514001.0,
                'duration_ms': 500, 'platform': 'cli',
                'model': 'wej-session-model-should-not-ship',
                'response_model': 'accounts/fireworks/models/glm-5p2',
                'provider': 'fireworks',
                'base_url': 'https://api.fireworks.ai/inference/v1',
                'api_mode': 'openai_chat',
                'finish_reason': 'stop',
                'input_tokens': 100, 'output_tokens': 50,
                'cache_read_tokens': 10, 'cache_write_tokens': 5,
                'reasoning_tokens': 0, 'total_tokens': 165,
            }])

            _write_jsonl(os.path.join(markers_dir, f'{sid}.jsonl'), [
                {'muid': 'wej-event-muid-001', 'ts': 1715513900.0,
                 'sid': sid, 'task_type': 'code_review',
                 'operation_type': 'GUARDRAIL'},
                {'muid': 'wej-event-muid-002', 'ts': 1715513900.5,
                 'sid': sid, 'task_type': 'code_review',
                 'operation_type': 'CHAT'},
            ])

            build_shim(shim)

            base_env = {
                **os.environ,
                'HOME': shim_home,
                'HERMES_HOME': hermes_home,
                'REVENIUM_STATE_DIR': state_dir,
                'PATH': bin_dir + os.pathsep + os.environ.get('PATH', ''),
                'INVOCATIONS_LOG': inv_log,
                'METER_LOG': meter_log,
                'TZ': 'UTC',
                'REVENIUM_EVENT_METERING_MODE': 'live',
            }

            rc, _ignored_inv, output = run_script(
                SCRIPTS_DIR / 'api-event-report.sh', base_env, inv_log
            )

            meter_invocations = []
            if os.path.exists(meter_log):
                with open(meter_log) as f:
                    for line in f:
                        line = line.rstrip('\n')
                        if line:
                            meter_invocations.append(shlex.split(line))

            self.assertEqual(
                rc, 0, f'api-event-report.sh failed (rc={rc}): {output}'
            )
            self.assertEqual(
                len(meter_invocations), 1,
                f'expected 1 meter completion invocation, got '
                f'{len(meter_invocations)}: {meter_invocations[:3]!r}\n'
                f'Output: {output}'
            )

            flags = argv_to_flags(meter_invocations[0])

            self.assertEqual(
                flags.get('--model'), 'fireworks/models/glm-5p2',
                'EVT-08: --model must ship the NORMALIZED model name '
                "'fireworks/models/glm-5p2' (what Revenium's catalog is keyed "
                f"on), got {flags.get('--model')!r}"
            )
            self.assertNotEqual(
                flags.get('--model'), 'accounts/fireworks/models/glm-5p2',
                'EVT-08 regression: --model shipped the RAW model name '
                "'accounts/fireworks/models/glm-5p2' instead of the normalized "
                "'fireworks/models/glm-5p2' — this is the canary's cost=0 "
                'defect, unpriced by Revenium.'
            )
            self.assertNotEqual(
                flags.get('--model'), 'wej-session-model-should-not-ship',
                "--model must NOT ship the record's `model` field verbatim"
            )
            # Normalization must not leak into provider resolution: legacy
            # infers provider from the RAW model, and `fireworks` is not a
            # routing-layer name, so _resolve_provider returns it verbatim.
            self.assertEqual(
                flags.get('--provider'), 'fireworks',
                '--provider must be unchanged by normalization (provider '
                f"resolution consumes the RAW response_model), got "
                f"{flags.get('--provider')!r}"
            )

        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == '__main__':
    unittest.main()
