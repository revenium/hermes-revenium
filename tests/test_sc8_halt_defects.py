"""The two defects the Phase 19 SC-8 real-breach run surfaced (2026-08-19).

Both were pre-existing and only a live breach exposed them; see
docs/halt-enforcement-live-verification.md for the run that found them.

  DEFECT 1 - the warn rate-limit was defeated whenever session_id could not be
  resolved. The fallback key was 'unknown-' + int(time.time()), which changes
  every second, so the WARN_FLAGS_DIR sentinel never matched: the warn fired on
  every LLM call and leaked one flag file per call. Measured 4 calls -> 4 warns.

  DEFECT 2 - clear-halt.sh bought about one tick. The rule stayed over its
  limit, so the next guardrail-check.sh re-derived block and re-halted, while
  the halt string told the operator "To resume: clear-halt.sh".
"""

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'skills' / 'revenium' / 'scripts'


def _env(home, state, extra=None):
    e = {
        **os.environ,
        'HOME': home,
        'HERMES_HOME': home,
        'REVENIUM_STATE_DIR': state,
        'PATH': os.path.join(home, '.local', 'bin') + os.pathsep + os.environ.get('PATH', ''),
    }
    e.update(extra or {})
    return e


def _warn_status(state_dir):
    os.makedirs(state_dir, exist_ok=True)
    with open(os.path.join(state_dir, 'guardrail-status.json'), 'w') as f:
        json.dump({'halted': False, 'autonomousMode': False, 'rules': [{
            'ruleId': 'RULE01', 'name': 'Probe', 'state': 'warn',
            'metricType': 'TOKEN_COUNT', 'windowType': 'DAILY',
            'currentValue': 110, 'hardLimit': 200}]}, f)


class WarnRateLimitStableKeyTests(unittest.TestCase):
    """DEFECT 1. The sentinel is keyed on (session, rule); an unresolvable
    session must still produce a STABLE key."""

    def _run_n(self, payload, calls=4, make_sessions_dir=True):
        with tempfile.TemporaryDirectory(prefix='gsd-sc8-warn-') as tmp:
            home = os.path.join(tmp, 'home')
            state = os.path.join(tmp, 'state')
            os.makedirs(home)
            if make_sessions_dir:
                os.makedirs(os.path.join(home, 'sessions'))
            _warn_status(state)
            warns = 0
            for _ in range(calls):
                r = subprocess.run(
                    ['bash', str(SCRIPTS / 'pre_llm_call.sh')],
                    input=payload, env=_env(home, state),
                    capture_output=True, text=True, timeout=30)
                warns += r.stderr.count('Guardrail warn:')
            flags = os.path.join(state, 'markers', '.warn')
            n_flags = len(os.listdir(flags)) if os.path.isdir(flags) else 0
            return warns, n_flags

    def test_unresolvable_session_warns_once_not_once_per_call(self):
        """The regression itself: no session_id, no session files."""
        warns, flags = self._run_n('{}')
        self.assertEqual(1, warns, f'expected exactly one warn across 4 calls, got {warns}')
        self.assertEqual(1, flags, f'expected one sentinel file, got {flags}')

    def test_payload_session_id_is_used_when_present(self):
        """pre_tool_call.sh always read the payload; this hook did not, and
        silently degraded to the sessions-dir scan."""
        warns, flags = self._run_n('{"session_id":"sess-abc"}')
        self.assertEqual(1, warns)
        self.assertEqual(1, flags)

    def test_sentinel_is_named_for_the_payload_session(self):
        with tempfile.TemporaryDirectory(prefix='gsd-sc8-name-') as tmp:
            home = os.path.join(tmp, 'home'); state = os.path.join(tmp, 'state')
            os.makedirs(os.path.join(home, 'sessions'))
            _warn_status(state)
            subprocess.run(['bash', str(SCRIPTS / 'pre_llm_call.sh')],
                           input='{"session_id":"sess-xyz"}', env=_env(home, state),
                           capture_output=True, text=True, timeout=30)
            self.assertEqual(['sess-xyz__RULE01.flag'],
                             os.listdir(os.path.join(state, 'markers', '.warn')))

    def test_no_timestamped_fallback_key_remains_in_either_hook(self):
        """Source guard. A timestamped key is what broke this; it must not
        return to either hook."""
        for name in ('pre_llm_call.sh', 'pre_tool_call.sh'):
            body = (SCRIPTS / name).read_text()
            code = [l for l in body.splitlines() if not l.lstrip().startswith('#')]
            offenders = [l for l in code if "int(time.time())" in l and 'unknown' in l]
            self.assertEqual([], offenders, f'{name} reintroduced a timestamped sentinel key')


class ClearHaltAcknowledgementTests(unittest.TestCase):
    """DEFECT 2. A manual clear must survive the next tick while the rule is
    still over its limit, and must expire on its own when the window rolls."""

    RULE = {'ruleId': 'RULE01', 'name': 'Probe', 'state': 'block',
            'metricType': 'TOKEN_COUNT', 'windowType': 'DAILY',
            'currentValue': 220, 'hardLimit': 200, 'windowKey': 'DAILY:2026-08-19',
            'shadowMode': False}

    def _state(self, tmp, **over):
        state = os.path.join(tmp, 'state')
        os.makedirs(state, exist_ok=True)
        doc = {'halted': True, 'autonomousMode': True,
               'haltedAt': '2026-08-19T18:00:00+00:00',
               'haltedRule': {'ruleId': 'RULE01'},
               'rules': [dict(self.RULE)]}
        doc.update(over)
        with open(os.path.join(state, 'guardrail-status.json'), 'w') as f:
            json.dump(doc, f)
        return state

    def test_clear_halt_records_the_window_it_cleared_in(self):
        with tempfile.TemporaryDirectory(prefix='gsd-sc8-clear-') as tmp:
            home = os.path.join(tmp, 'home'); os.makedirs(home)
            state = self._state(tmp)
            r = subprocess.run(['bash', str(SCRIPTS / 'clear-halt.sh')],
                               env=_env(home, state), capture_output=True,
                               text=True, timeout=30)
            self.assertEqual(0, r.returncode, r.stderr)
            doc = json.load(open(os.path.join(state, 'guardrail-status.json')))
            self.assertFalse(doc['halted'])
            self.assertEqual({'RULE01': 'DAILY:2026-08-19'}, doc.get('clearedWindows'),
                             'clear-halt must stamp the acknowledgement with its windowKey')

    def test_acknowledgement_is_scoped_to_its_window(self):
        """The expiry mechanism: same rule, NEW window -> no longer acknowledged."""
        ack = {'RULE01': 'DAILY:2026-08-19'}
        self.assertEqual(ack.get('RULE01'), 'DAILY:2026-08-19')
        self.assertNotEqual(ack.get('RULE01'), 'DAILY:2026-08-20',
                            'a rolled window must not match a prior acknowledgement')

    def test_clear_halt_without_windowkey_degrades_not_suppresses(self):
        """An older status file has no windowKey. That must fall back to the
        previous behaviour rather than suppressing enforcement forever."""
        with tempfile.TemporaryDirectory(prefix='gsd-sc8-nowk-') as tmp:
            home = os.path.join(tmp, 'home'); os.makedirs(home)
            rule = {k: v for k, v in self.RULE.items() if k != 'windowKey'}
            state = self._state(tmp, rules=[rule])
            subprocess.run(['bash', str(SCRIPTS / 'clear-halt.sh')],
                           env=_env(home, state), capture_output=True,
                           text=True, timeout=30)
            doc = json.load(open(os.path.join(state, 'guardrail-status.json')))
            self.assertEqual({}, doc.get('clearedWindows'),
                             'no windowKey means no acknowledgement recorded')

    def test_guardrail_check_carries_and_honours_the_acknowledgement(self):
        """Source-level guard on the three edits that make suppression work."""
        body = (SCRIPTS / 'guardrail-check.sh').read_text()
        self.assertIn("'windowKey': r.get('windowKey', '')", body,
                      'windowKey must be persisted per rule or clear-halt has nothing to stamp')
        self.assertIn("'clearedWindows': cleared_windows", body,
                      'clearedWindows must be written so it survives the next tick')
        self.assertIn('not in acknowledged', body,
                      'the halt decision must exclude acknowledged rules')

    def test_suppression_never_sets_halted_false_itself(self):
        """clear-halt.sh remains the ONLY thing that clears halted (CLAUDE.md).
        Suppression prevents setting it back to true; it must not clear it."""
        body = (SCRIPTS / 'guardrail-check.sh').read_text()
        self.assertIn('new_halted = autonomous and any_blocked', body,
                      'halted must still be derived from any_blocked, not special-cased')


def _make_revenium_stub(bin_dir, rules_json):
    """Minimal `revenium` covering every call guardrail-check.sh makes.

    Placement follows the D-16 contract used by the setup-guardrails tests:
    <home>/.local/bin with HOME pointed at <home>, because ensure_path()
    prepends on each iteration so ${HOME}/.local/bin ends up FIRST — otherwise a
    real /opt/homebrew/bin/revenium wins and the test validates reality.
    """
    os.makedirs(bin_dir, exist_ok=True)
    path = os.path.join(bin_dir, 'revenium')
    with open(path, 'w') as f:
        f.write(
            '#!/usr/bin/env bash\n'
            'for a in "$@"; do if [[ "$a" == "--help" ]]; then\n'
            '  echo "      --page int"; echo "      --page-size int"; exit 0; fi; done\n'
            'case "$*" in\n'
            '  "config show"*) echo "Team ID:    TEAM01" ;;\n'
            '  *"enforcement-rules get"*) cat <<\'JSON\'\n' + rules_json + '\nJSON\n ;;\n'
            '  *"budget-rules list"*) echo \'[{"id":"RULE01","label":"Probe","name":"Probe"}]\' ;;\n'
            '  *"enforcement-events list"*) echo \'[]\' ;;\n'
            '  *) echo "{}" ;;\n'
            'esac\n')
    os.chmod(path, 0o755)


def _rules_payload(window_key, breached=True, current=220):
    return json.dumps({'rules': [{
        'name': 'Probe', 'ruleId': 9001, 'metricType': 'TOKEN_COUNT',
        'periodType': 'DAILY', 'currentValue': current, 'threshold': 200,
        'warnThreshold': 100, 'breached': breached, 'warnBreached': True,
        'shadowMode': False, 'groupBy': 'AGENT', 'windowKey': window_key,
        'action': 'BLOCK'}]})


class ClearHaltSurvivesTheNextTickTests(unittest.TestCase):
    """The behavioural proof for DEFECT 2, driving guardrail-check.sh for real."""

    def _setup(self, tmp, window_key):
        home = os.path.join(tmp, 'home')
        state = os.path.join(tmp, 'state')
        os.makedirs(state, exist_ok=True)
        _make_revenium_stub(os.path.join(home, '.local', 'bin'),
                            _rules_payload(window_key))
        with open(os.path.join(state, 'config.json'), 'w') as f:
            json.dump({'ruleIds': ['RULE01'], 'autonomousMode': True}, f)
        return home, state

    def _tick(self, home, state):
        return subprocess.run(['bash', str(SCRIPTS / 'guardrail-check.sh')],
                              env=_env(home, state), capture_output=True,
                              text=True, timeout=60)

    def _halted(self, state):
        with open(os.path.join(state, 'guardrail-status.json')) as f:
            return json.load(f)

    def test_clear_then_next_tick_does_not_rehalt(self):
        with tempfile.TemporaryDirectory(prefix='gsd-sc8-e2e-') as tmp:
            home, state = self._setup(tmp, 'DAILY:2026-08-19')

            self._tick(home, state)
            self.assertTrue(self._halted(state)['halted'], 'breach must halt first')

            subprocess.run(['bash', str(SCRIPTS / 'clear-halt.sh')],
                           env=_env(home, state), capture_output=True,
                           text=True, timeout=30)
            self.assertFalse(self._halted(state)['halted'], 'clear-halt must clear')

            r = self._tick(home, state)
            doc = self._halted(state)
            self.assertFalse(
                doc['halted'],
                'THE REGRESSION: the tick after a manual clear re-halted while the '
                'rule was still over its limit')
            self.assertIn('HALT_TRANSITION=false', r.stdout)
            self.assertEqual('block', doc['rules'][0]['state'],
                             'the rule must still REPORT block — only the halt is suppressed')

    def test_acknowledgement_expires_when_the_window_rolls(self):
        with tempfile.TemporaryDirectory(prefix='gsd-sc8-roll-') as tmp:
            home, state = self._setup(tmp, 'DAILY:2026-08-19')
            self._tick(home, state)
            subprocess.run(['bash', str(SCRIPTS / 'clear-halt.sh')],
                           env=_env(home, state), capture_output=True, text=True, timeout=30)
            self._tick(home, state)
            self.assertFalse(self._halted(state)['halted'])

            # Same rule, still breached, NEW window.
            _make_revenium_stub(os.path.join(home, '.local', 'bin'),
                                _rules_payload('DAILY:2026-08-20'))
            self._tick(home, state)
            doc = self._halted(state)
            self.assertTrue(doc['halted'],
                            'a rolled window must re-arm enforcement with no manual step')
            self.assertEqual({}, doc.get('clearedWindows'),
                             'the stale acknowledgement must be pruned, not accumulated')

    def test_unacknowledged_breach_still_halts_normally(self):
        """Control: suppression must not weaken a fresh breach."""
        with tempfile.TemporaryDirectory(prefix='gsd-sc8-ctl-') as tmp:
            home, state = self._setup(tmp, 'DAILY:2026-08-19')
            r = self._tick(home, state)
            self.assertTrue(self._halted(state)['halted'])
            self.assertIn('HALT_TRANSITION=true', r.stdout)


if __name__ == '__main__':
    unittest.main()
