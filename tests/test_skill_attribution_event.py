"""Skill-usage attribution on the EVENT path's `revenium meter completion`.

Sibling of tests/test_skill_attribution.py, which pins the same four CLI 1.4.0
flags on hermes-report.sh. The two paths are mutually exclusive per session via
the ownership record, so proving one proves nothing about the other: a session
claimed by the event path was getting zero skill attribution, and the legacy
path can never backfill it.

Six properties, each a way this could go wrong in production:

  1. No skill signal at all -> argv byte-identical to today. This is the COMMON
     case: across five sampled fleet profiles only 3-36% of token-bearing
     sessions carry any skill signal, so a regression here corrupts the
     majority of rows rather than a corner.
  2. A state.db with no `messages` table -> no flags, row still ships. That is
     what any install predating Hermes' skill tools looks like, and it is the
     shape build_state_db itself produces.
  3. Probe negative (pre-1.4 CLI) -> not one skill flag, even with the signal
     present. The fleet host still runs a CLI without these flags.
  4. Two events straddling a skill switch -> DIFFERENT skills. This is the
     property that distinguishes this path from the legacy one, which can only
     attribute per delta window. If someone "unifies" the two paths for
     symmetry, this is the test that stops them.
  5. An event preceding every skill row -> no flags. The marker join in the
     same heredoc deliberately extends its first window BACKWARD; skills are
     the opposite question, because a skill opened after a call did not
     influence it.
  6. Malformed payload -> the next-most-recent skill wins rather than emitting
     garbage or losing the row. Attribution is enrichment; it must never cost
     a completion its metering.
"""
import json
import os
import shlex
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

from tests._compat_helpers import (
    argv_to_flags,
    build_shim,
    build_state_db,
    run_script,
    SCRIPTS_DIR,
)

SID = 'skill-event-sid-001'

# The whole flag family: the four this path emits, plus the two it deliberately
# never does. Every suppression assertion below iterates this tuple, so a flag
# added to the append block without being added here would slip past them —
# test_flag_tuple_covers_every_skill_flag_in_the_script is what closes that.
SKILL_FLAGS = (
    '--skill-name', '--skill-invocation-trigger', '--skill-source',
    '--skill-marketplace-name', '--skill-kind', '--skill-plugin-name',
)

# One CHAT marker, dated before the earliest event, so the temporal join
# attributes a real task_type and the rows under test are the enriched shape.
MARKER_TS = 1715513900.5

# Two events in one session, ~10 minutes apart.
EVENT_A_TS, EVENT_A_END, ARID_A = 1715514000.5, 1715514001.0, 'skill-event-arid-a'
EVENT_B_TS, EVENT_B_END, ARID_B = 1715514600.5, 1715514601.0, 'skill-event-arid-b'

# Between A and B: a skill opened here is in force for B but not for A.
SWITCH_TS = 1715514300.0
# Before A: in force for both.
EARLY_TS = 1715513950.0
# After B: in force for neither (property 5).
LATE_TS = 1715514900.0


def _event(arid, ts, ended_at):
    """One contract-C-2 spool record."""
    return {
        'v': 1, 'sid': SID, 'api_request_id': arid,
        'ts': ts, 'ended_at': ended_at,
        'duration_ms': 500, 'platform': 'cli',
        'model': 'session-model-should-not-ship',
        'response_model': 'claude-sonnet-4-6',
        'provider': 'anthropic',
        'base_url': 'https://api.anthropic.com',
        'api_mode': 'anthropic_messages',
        'finish_reason': 'stop',
        'input_tokens': 100, 'output_tokens': 50,
        'cache_read_tokens': 10, 'cache_write_tokens': 5,
        'reasoning_tokens': 0, 'total_tokens': 165,
    }


def _write_jsonl(path, records):
    with open(path, 'w', encoding='utf-8') as f:
        for r in records:
            f.write(json.dumps(r, separators=(',', ':')) + '\n')


def add_skill_messages(db_path, rows):
    """rows: list of (tool_name, payload_str, timestamp).

    Creates the `messages` table on demand — build_state_db does not, which is
    exactly why the missing-table case below is a real install shape.
    """
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


class SkillAttributionEventTests(unittest.TestCase):
    def _run(self, skill_rows=None, skill_capable=True, lock_entry=None,
             events=None, make_state_db=False):
        """Meter one session on the event path.

        Returns (flags_by_transaction_id, all_flag_dicts, output). Every
        meter-completion line in METER_LOG is parsed, so the multi-event cases
        can assert per --transaction-id rather than per position.
        """
        tmpdir = tempfile.mkdtemp(prefix='gsd-skill-attr-event-')
        self.addCleanup(shutil.rmtree, tmpdir, ignore_errors=True)

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

        # Settle gate satisfied by the sentinel's presence, not by age.
        Path(ready_dir, SID).touch()

        _write_jsonl(os.path.join(spool_dir, f'{SID}.jsonl'),
                     events if events is not None else [_event(ARID_A, EVENT_A_TS, EVENT_A_END)])

        _write_jsonl(os.path.join(markers_dir, f'{SID}.jsonl'), [
            {'muid': 'skill-event-muid-001', 'ts': MARKER_TS, 'sid': SID,
             'task_type': 'code_review', 'operation_type': 'CHAT'},
        ])

        # state.db is created only when a test asks for it. Its ABSENCE is the
        # shape test_compat_meter_completion_event runs in, and property 1.
        state_db = os.path.join(hermes_home, 'state.db')
        if skill_rows is not None or make_state_db:
            build_state_db(state_db, [{
                'id': SID, 'model': 'claude-sonnet-4-6', 'source': 'cli',
                'input_tokens': 100, 'output_tokens': 50,
                'cache_read': 10, 'cache_write': 5, 'reasoning': 0,
                'estimated_cost': '0', 'api_calls': 1,
                'started_at': EVENT_A_TS, 'ended_at': EVENT_B_END,
                'billing_provider': 'anthropic',
            }])
        if skill_rows is not None:
            add_skill_messages(state_db, skill_rows)

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
            'TZ': 'UTC',
            # Shadow is the C-9 default and ships nothing; these tests
            # exercise LIVE argv construction, so they opt in explicitly.
            'REVENIUM_EVENT_METERING_MODE': 'live',
        }
        rc, _inv, output = run_script(SCRIPTS_DIR / 'api-event-report.sh', env, inv_log)
        self.assertEqual(rc, 0, f'api-event-report.sh exit {rc}\n{output}')

        all_flags = []
        if os.path.exists(meter_log):
            with open(meter_log) as f:
                for line in f:
                    line = line.rstrip('\n')
                    if line:
                        all_flags.append(argv_to_flags(shlex.split(line)))
        by_txn = {f.get('--transaction-id'): f for f in all_flags}
        return by_txn, all_flags, output

    # --- Property 1 -------------------------------------------------------
    def test_no_skill_signal_emits_no_skill_flags(self):
        """No state.db at all: the shape the event-path golden runs in.

        Catches a regression that would corrupt the 64-97% of real sessions
        carrying no skill signal — the no-skill path IS the wire contract.
        """
        _by_txn, all_flags, _out = self._run()
        self.assertEqual(len(all_flags), 1,
                         'the completion must still ship when there is no skill signal')
        for f in SKILL_FLAGS:
            self.assertNotIn(f, all_flags[0],
                             f'{f} emitted for a session with no skill signal at all')

    # --- Property 2 -------------------------------------------------------
    def test_state_db_without_messages_table_still_meters(self):
        """An install predating Hermes' skill tools has no `messages` table.

        Catches a narrowing of the sqlite exception handling: an unhandled
        OperationalError here would strand the completion, turning an
        enrichment miss into a billing loss.
        """
        by_txn, all_flags, output = self._run(make_state_db=True)
        self.assertEqual(len(all_flags), 1,
                         'a missing messages table must not cost the row its metering')
        for f in SKILL_FLAGS:
            self.assertNotIn(f, all_flags[0], f'{f} emitted with no messages table present')
        self.assertNotIn('Traceback', output)
        self.assertIn(f'event:{ARID_A}', by_txn)

    # --- Property 3 -------------------------------------------------------
    def test_pre_1_4_cli_emits_no_skill_flags_even_with_signal(self):
        """A negative capability probe must suppress the whole family.

        The fleet host runs exactly this configuration today, so an ungated
        append would send unknown flags to a CLI that rejects them.

        Scope, established by mutation rather than assumed: suppression is
        gated TWICE — once in the heredoc, which skips the skill query
        entirely when the probe is negative, and once at the append block.
        The two are redundant by design, so removing either one alone leaves
        this test green; only removing BOTH is observable here, and that is
        the actual production failure. The individual gates are pinned
        structurally by test_suppression_is_gated_in_both_places.
        """
        _by_txn, all_flags, _out = self._run(
            skill_rows=[('skill_view', json.dumps({'name': 'sentry-watch'}), EARLY_TS)],
            skill_capable=False)
        self.assertEqual(len(all_flags), 1)
        for f in SKILL_FLAGS:
            self.assertNotIn(f, all_flags[0],
                             f'{f} sent to a CLI that does not advertise it')

    # --- Property 4 (the one that distinguishes this path) ----------------
    def test_two_events_straddling_a_skill_switch_get_different_skills(self):
        """PER-EVENT attribution: each call gets the skill in force AT it.

        The legacy path can only pick one skill per delta window. If this path
        is ever "unified" with it for symmetry, both events would carry
        'beta-skill' and this test fails — which is the point.
        """
        by_txn, all_flags, _out = self._run(
            events=[_event(ARID_A, EVENT_A_TS, EVENT_A_END),
                    _event(ARID_B, EVENT_B_TS, EVENT_B_END)],
            skill_rows=[
                ('skill_view', json.dumps({'name': 'alpha-skill'}), EARLY_TS),
                ('skill_manage', json.dumps({'name': 'beta-skill'}), SWITCH_TS),
            ])
        self.assertEqual(len(all_flags), 2, 'both events must ship')
        a = by_txn[f'event:{ARID_A}']
        b = by_txn[f'event:{ARID_B}']
        self.assertEqual(a.get('--skill-name'), 'alpha-skill',
                         'the earlier event must carry the skill in force when IT ran')
        self.assertEqual(a.get('--skill-invocation-trigger'), 'skill_view')
        self.assertEqual(b.get('--skill-name'), 'beta-skill',
                         'the later event must carry the skill opened before IT ran')
        self.assertEqual(b.get('--skill-invocation-trigger'), 'skill_manage')
        self.assertNotEqual(a.get('--skill-name'), b.get('--skill-name'),
                            'per-session attribution would make these identical')

    # --- Property 5 -------------------------------------------------------
    def test_event_preceding_every_skill_row_gets_no_skill_flags(self):
        """No backward extension, deliberately unlike the marker join.

        Catches someone copying the marker join's `if idx < 0: idx = 0` clamp
        into the skill resolver, which would attribute a call to a skill that
        was not opened until after it finished.
        """
        _by_txn, all_flags, _out = self._run(
            skill_rows=[('skill_view', json.dumps({'name': 'opened-later'}), LATE_TS)])
        self.assertEqual(len(all_flags), 1, 'the completion must still ship')
        for f in SKILL_FLAGS:
            self.assertNotIn(
                f, all_flags[0],
                f'{f} emitted for a call that finished before the skill was opened')

    # --- Property 6 -------------------------------------------------------
    def test_malformed_newest_payload_falls_through(self):
        """A payload that will not parse must not win and must not abort."""
        _by_txn, all_flags, output = self._run(
            events=[_event(ARID_B, EVENT_B_TS, EVENT_B_END)],
            skill_rows=[
                ('skill_view', json.dumps({'name': 'good-skill'}), EARLY_TS),
                ('skill_view', '{not json at all', SWITCH_TS),
            ])
        self.assertEqual(len(all_flags), 1)
        self.assertEqual(
            all_flags[0].get('--skill-name'), 'good-skill',
            'a malformed newest payload must fall through to the next-most-recent')
        self.assertNotIn('Traceback', output)

    # --- Provenance -------------------------------------------------------
    def test_provenance_comes_from_the_hub_lock_or_is_omitted(self):
        """Source/marketplace are read from lock.json — never invented."""
        _by_txn, all_flags, _out = self._run(
            skill_rows=[('skill_view', json.dumps({'name': 'sentry-watch'}), EARLY_TS)],
            lock_entry={'sentry-watch': {'source': 'skills.sh'}})
        self.assertEqual(all_flags[0].get('--skill-source'), 'skills.sh')
        self.assertEqual(all_flags[0].get('--skill-marketplace-name'), 'skills.sh')

        # 'official' is a SOURCE but not a marketplace.
        _by_txn2, all2, _out2 = self._run(
            skill_rows=[('skill_view', json.dumps({'name': 'sentry-watch'}), EARLY_TS)],
            lock_entry={'sentry-watch': {'source': 'official'}})
        self.assertEqual(all2[0].get('--skill-source'), 'official')
        self.assertNotIn('--skill-marketplace-name', all2[0],
                         "'official' names where a skill came from, not a marketplace")

        # Skill absent from the lockfile -> both omitted, name still ships.
        _by_txn3, all3, _out3 = self._run(
            skill_rows=[('skill_view', json.dumps({'name': 'hand-written'}), EARLY_TS)],
            lock_entry={'something-else': {'source': 'skills.sh'}})
        self.assertEqual(all3[0].get('--skill-name'), 'hand-written')
        self.assertNotIn('--skill-source', all3[0])
        self.assertNotIn('--skill-marketplace-name', all3[0])

    def test_kind_and_plugin_name_are_never_emitted(self):
        """We do not know what Revenium expects; an invented value is worse."""
        _by_txn, all_flags, _out = self._run(
            skill_rows=[('skill_view', json.dumps({'name': 'sentry-watch'}), EARLY_TS)],
            lock_entry={'sentry-watch': {'source': 'skills.sh'}})
        self.assertNotIn('--skill-kind', all_flags[0])
        self.assertNotIn('--skill-plugin-name', all_flags[0])

    # --- Guard on the guards ---------------------------------------------
    def test_suppression_is_gated_in_both_places(self):
        """Both capability gates must survive, and this is the only test that
        can tell if one of them does not.

        Structural, deliberately. The gates are redundant: with the probe
        negative, the heredoc gate leaves the timeline empty (so the append
        block's non-empty-name check suppresses anyway), and the append gate
        suppresses even if the timeline were populated. Each therefore MASKS
        the other from every behavioural assertion in this file — verified by
        mutation, not assumed. A tidy-up that deletes "the redundant one"
        would pass the whole suite while collapsing a two-deep guard on the
        billing path to a single point of failure.

        They are not interchangeable. The heredoc gate is also the cost gate:
        it is what keeps a pre-1.4 CLI from paying for a sqlite query per
        session file whose result can never be used.
        """
        body = (SCRIPTS_DIR / 'api-event-report.sh').read_text()
        self.assertIn(
            'if os.environ.get("SKILL_CAPABLE") == "true":', body,
            'the heredoc no longer gates the skill query on the capability '
            'probe — a pre-1.4 CLI now pays for a query per session file whose '
            'result it cannot use')
        self.assertIn(
            'if [[ "${SKILL_CLI_CAPABLE}" == "true" && -n "${skill_name_r}" ]]; then',
            body,
            'the append block no longer gates on BOTH the capability probe and '
            'a non-empty skill name — one of the two suppression paths is gone')

    def test_flag_tuple_covers_every_skill_flag_in_the_script(self):
        """Every suppression assertion above iterates SKILL_FLAGS.

        A fifth flag added to the append block without being added here would
        be invisible to all of them — it would ship to a pre-1.4 CLI, and to a
        call that preceded every skill row, with nothing failing.

        Scans CODE lines only. tests/test_capability_probe_idiom.py records
        what happens when a guard greps prose: it forced two production
        docstrings to be reworded. The append block's comment names
        --skill-kind and --skill-plugin-name precisely to say they are never
        emitted, and that comment must stay free to say so.
        """
        code = '\n'.join(
            line for line in (SCRIPTS_DIR / 'api-event-report.sh').read_text().splitlines()
            if not line.lstrip().startswith('#')
        )
        found = set()
        for token in code.replace('"', ' ').replace('(', ' ').replace(')', ' ').split():
            if token.startswith('--skill-'):
                found.add(token)
        unknown = sorted(found - set(SKILL_FLAGS))
        self.assertEqual(
            [], unknown,
            f'api-event-report.sh references skill flag(s) this module does not '
            f'know about: {unknown}. Add them to SKILL_FLAGS so the suppression '
            f'tests cover them.')
        self.assertEqual(
            {'--skill-name', '--skill-invocation-trigger', '--skill-source',
             '--skill-marketplace-name'}, found,
            'the four emitted flags must all still be referenced by the script')


if __name__ == '__main__':
    unittest.main()
