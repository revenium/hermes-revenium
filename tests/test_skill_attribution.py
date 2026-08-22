"""Skill-usage attribution on `revenium meter completion` (CLI 1.4.0).

Four properties, each corresponding to a way this could go wrong in production:

  1. No skill signal -> argv byte-identical to today. This is the COMMON case:
     across five sampled fleet profiles only 3-36% of token-bearing sessions
     carry any skill signal, so a regression here would corrupt the majority of
     rows rather than a corner.
  2. Probe negative (pre-1.4 CLI) -> not one skill flag emitted, even when the
     signal is present. The fleet host still runs a CLI without these flags, so
     this is a live configuration, not a legacy hypothetical.
  3. Multi-skill session -> MOST RECENT at-or-before the window wins.
     `--skill-name` is singular while sessions routinely open several skills
     (19 of 30 skill-bearing sessions on one sampled profile).
  4. Malformed payload -> falls through to the next-most-recent rather than
     emitting garbage or failing the completion. Attribution is enrichment; it
     must never cost a completion its metering.
"""
import json
import os
import shutil
import sqlite3
import tempfile
import unittest

from tests._compat_helpers import (
    argv_to_flags,
    build_shim,
    build_state_db,
    run_script,
    SCRIPTS_DIR,
)

SID = 'skill-sid-001'
SKILL_FLAGS = (
    '--skill-name', '--skill-invocation-trigger', '--skill-source',
    '--skill-marketplace-name', '--skill-kind', '--skill-plugin-name',
)


def add_skill_messages(db_path, rows):
    """rows: list of (tool_name, payload_str, timestamp)."""
    conn = sqlite3.connect(db_path)
    conn.execute(
        'CREATE TABLE IF NOT EXISTS messages '
        '(id INTEGER PRIMARY KEY, session_id TEXT, role TEXT, content TEXT, '
        'tool_calls TEXT, tool_name TEXT, timestamp REAL)'
    )
    for tool_name, payload, ts in rows:
        conn.execute(
            'INSERT INTO messages (session_id, role, content, tool_name, timestamp) '
            'VALUES (?,?,?,?,?)', (SID, 'tool', payload, tool_name, ts))
    conn.commit()
    conn.close()


class SkillAttributionTests(unittest.TestCase):
    def _run(self, skill_rows=None, skill_capable=True, lock_entry=None):
        """Meter one session; return the flags dict of the meter-completion argv."""
        tmpdir = tempfile.mkdtemp(prefix='gsd-skill-attr-')
        self.addCleanup(shutil.rmtree, tmpdir, ignore_errors=True)

        hermes_home = os.path.join(tmpdir, 'hh')
        state_dir = os.path.join(hermes_home, 'state', 'revenium')
        markers_dir = os.path.join(state_dir, 'markers')
        os.makedirs(markers_dir, mode=0o700)
        state_db = os.path.join(hermes_home, 'state.db')
        shim_home = os.path.join(tmpdir, 'home')
        bin_dir = os.path.join(shim_home, '.local', 'bin')
        os.makedirs(bin_dir)
        meter_log = os.path.join(tmpdir, 'meter.log')
        inv_log = os.path.join(tmpdir, 'inv.log')

        build_state_db(state_db, [{
            'id': SID, 'model': 'claude-3-5-sonnet', 'source': 'cli',
            'input_tokens': 100, 'output_tokens': 50,
            'cache_read': 0, 'cache_write': 0, 'reasoning': 0,
            'estimated_cost': '0', 'api_calls': 1,
            'started_at': 1715514000.0, 'ended_at': 1715515000.0,
            'billing_provider': 'anthropic',
        }])
        if skill_rows:
            add_skill_messages(state_db, skill_rows)

        with open(os.path.join(markers_dir, SID + '.jsonl'), 'w') as f:
            f.write(json.dumps({
                'muid': 'skill-muid-001', 'ts': 1715515000.5, 'sid': SID,
                'task_type': 'code_review', 'operation_type': 'CHAT',
            }, separators=(',', ':')) + '\n')

        if lock_entry is not None:
            hub = os.path.join(hermes_home, 'skills', '.hub')
            os.makedirs(hub, exist_ok=True)
            with open(os.path.join(hub, 'lock.json'), 'w') as f:
                json.dump({'installed': lock_entry}, f)

        build_shim(os.path.join(bin_dir, 'revenium'), skill_capable=skill_capable)
        env = {
            **os.environ,
            'HOME': shim_home, 'HERMES_HOME': hermes_home,
            'REVENIUM_STATE_DIR': state_dir,
            'PATH': bin_dir + os.pathsep + os.environ.get('PATH', ''),
            'INVOCATIONS_LOG': inv_log, 'METER_LOG': meter_log,
            'TZ': 'UTC', 'REVENIUM_ORGANIZATION_NAME': '',
        }
        rc, _inv, output = run_script(SCRIPTS_DIR / 'hermes-report.sh', env, inv_log)
        self.assertEqual(rc, 0, f'reporter exit {rc}\n{output}')
        with open(meter_log) as f:
            lines = [ln for ln in f.read().splitlines() if ln.strip()]
        self.assertTrue(lines, f'no meter completion captured\n{output}')
        import shlex
        return argv_to_flags(shlex.split(lines[0])), output

    def test_no_skill_signal_emits_no_skill_flags(self):
        """The common case: a session that never opened a skill is unchanged."""
        flags, _ = self._run(skill_rows=None)
        for f in SKILL_FLAGS:
            self.assertNotIn(
                f, flags,
                f'{f} emitted for a session with no skill signal — 64-97% of '
                f'real sessions look like this, so the no-skill path IS the '
                f'wire contract')

    def test_pre_1_4_cli_emits_no_skill_flags_even_with_signal(self):
        """A negative capability probe must suppress the whole family."""
        flags, _ = self._run(
            skill_rows=[('skill_view', json.dumps({'name': 'sentry-watch'}), 1715514500.0)],
            skill_capable=False)
        for f in SKILL_FLAGS:
            self.assertNotIn(
                f, flags,
                f'{f} sent to a CLI that does not advertise it — the fleet host '
                f'runs exactly this configuration today')

    def test_most_recent_skill_wins(self):
        """Operator-chosen policy: most recent at-or-before the window end."""
        flags, _ = self._run(skill_rows=[
            ('skill_view', json.dumps({'name': 'older-skill'}), 1715514100.0),
            ('skill_view', json.dumps({'name': 'middle-skill'}), 1715514400.0),
            ('skill_manage', json.dumps({'name': 'newest-skill'}), 1715514900.0),
        ])
        self.assertEqual(flags.get('--skill-name'), 'newest-skill')
        self.assertEqual(flags.get('--skill-invocation-trigger'), 'skill_manage')

    def test_malformed_payload_falls_through_to_next_most_recent(self):
        """A payload that will not parse must not emit garbage or lose the row."""
        flags, output = self._run(skill_rows=[
            ('skill_view', json.dumps({'name': 'good-skill'}), 1715514100.0),
            ('skill_view', '{not json at all', 1715514900.0),
        ])
        self.assertEqual(
            flags.get('--skill-name'), 'good-skill',
            'a malformed newest payload must fall through, not win and not abort')
        self.assertNotIn('Traceback', output)

    def test_provenance_comes_from_the_hub_lock_or_is_omitted(self):
        """Source/marketplace are read from lock.json — never invented."""
        flags, _ = self._run(
            skill_rows=[('skill_view', json.dumps({'name': 'sentry-watch'}), 1715514500.0)],
            lock_entry={'sentry-watch': {'source': 'skills.sh'}})
        self.assertEqual(flags.get('--skill-source'), 'skills.sh')
        self.assertEqual(flags.get('--skill-marketplace-name'), 'skills.sh')

        # Unknown skill -> both omitted rather than guessed.
        flags2, _ = self._run(
            skill_rows=[('skill_view', json.dumps({'name': 'hand-written'}), 1715514500.0)],
            lock_entry={'something-else': {'source': 'skills.sh'}})
        self.assertEqual(flags2.get('--skill-name'), 'hand-written')
        self.assertNotIn('--skill-source', flags2)
        self.assertNotIn('--skill-marketplace-name', flags2)

    def test_kind_and_plugin_name_are_never_emitted(self):
        """We do not know what Revenium expects; an invented value is worse."""
        flags, _ = self._run(
            skill_rows=[('skill_view', json.dumps({'name': 'sentry-watch'}), 1715514500.0)],
            lock_entry={'sentry-watch': {'source': 'skills.sh'}})
        self.assertNotIn('--skill-kind', flags)
        self.assertNotIn('--skill-plugin-name', flags)


if __name__ == '__main__':
    unittest.main()
