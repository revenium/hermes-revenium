"""quick-260918-lt6 -- batch root-session resolution must be byte-identical
to the per-session form.

`root_sid` decides two things that money depends on: whether a job is CREATED
for a session (`root_sid == sid` is the fail-open rootness gate in
hermes-report.sh) and which trace a completion rolls up under. A batch
implementation that disagrees with the per-session one on any input does not
make the tick faster -- it silently re-attributes billing.

So the gate here is equivalence, not correctness-in-isolation: every test
runs BOTH implementations over the SAME state.db and asserts they agree. The
corpus deliberately includes the shapes where a plausible batch
implementation drifts:

  * depth exhaustion, where the per-session form returns the 10th ancestor
    and NOT the input sid -- the single easiest case to get wrong, because
    every other failure path does fail open to the input
  * a cycle, which is the same code path as exhaustion but arrives there for
    a different reason
  * a sid absent from `sessions` entirely (pseudo-/event-path ids)
  * a parent that is itself NOT in the requested input set, which a
    `WHERE id IN (...)` optimisation would drop, turning a subagent into its
    own root
"""
import os
import subprocess
import sys
import sqlite3
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / 'skills' / 'revenium'
SIDECAR = SKILL / 'scripts' / 'get-root-session-id.py'

sys.path.insert(0, str(SKILL / 'scripts'))


def _load_sidecar():
    import importlib.util
    spec = importlib.util.spec_from_file_location('grsi', SIDECAR)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class RootSidBatchEquivalenceTests(unittest.TestCase):
    """Both implementations, same DB, same answers."""

    def _build_db(self, path, rows):
        conn = sqlite3.connect(path)
        try:
            conn.execute(
                'CREATE TABLE sessions (id TEXT PRIMARY KEY, parent_session_id TEXT)'
            )
            conn.executemany(
                'INSERT INTO sessions (id, parent_session_id) VALUES (?, ?)', rows
            )
            conn.commit()
        finally:
            conn.close()

    def _corpus(self):
        """(rows, sids) covering every shape that can diverge."""
        rows = [
            ('top', None),                 # top-level: NULL parent
            ('child', 'top'),              # one level deep
            ('grandchild', 'child'),       # deeper chain
            ('great', 'grandchild'),
        ]
        # A chain LONGER than max_depth=10, so the walk exhausts its budget.
        rows.append(('deep0', None))
        for i in range(1, 15):
            rows.append((f'deep{i}', f'deep{i - 1}'))
        # A cycle: a <-> b. Exhausts depth for a different reason.
        rows.append(('cyc_a', 'cyc_b'))
        rows.append(('cyc_b', 'cyc_a'))
        # A session whose parent is NOT itself in the requested sid set.
        rows.append(('orphan_parent', None))
        rows.append(('has_unrequested_parent', 'orphan_parent'))

        sids = [
            'top', 'child', 'grandchild', 'great',
            'deep14', 'deep9', 'deep0',
            'cyc_a', 'cyc_b',
            'has_unrequested_parent',
            'absent_from_table',   # never inserted
            '',                    # empty string
        ]
        return rows, sids

    def test_batch_matches_per_session_across_corpus(self):
        mod = _load_sidecar()
        rows, sids = self._corpus()
        with tempfile.TemporaryDirectory(prefix='gsd-lt6-') as tmp:
            db = os.path.join(tmp, 'state.db')
            self._build_db(db, rows)

            per_session = {s: mod.get_root_session_id(s, state_db_path=db) for s in sids}
            batch = mod.get_root_session_ids(sids, state_db_path=db)

            for s in sids:
                self.assertEqual(
                    per_session[s], batch[s],
                    f'batch and per-session disagree for {s!r}: '
                    f'{batch[s]!r} vs {per_session[s]!r} -- this is a billing '
                    f'attribution change, not a perf detail',
                )

    def test_depth_exhaustion_returns_ancestor_not_input(self):
        """Pins the one case where NOT failing open to the input is correct."""
        mod = _load_sidecar()
        rows, _ = self._corpus()
        with tempfile.TemporaryDirectory(prefix='gsd-lt6-depth-') as tmp:
            db = os.path.join(tmp, 'state.db')
            self._build_db(db, rows)
            got = mod.get_root_session_id('deep14', state_db_path=db)
            self.assertNotEqual(
                'deep14', got,
                'depth exhaustion must return the ancestor reached, not the input',
            )
            self.assertEqual('deep4', got, 'ten hops from deep14 lands on deep4')
            self.assertEqual(
                got, mod.get_root_session_ids(['deep14'], state_db_path=db)['deep14'],
            )

    def test_missing_state_db_is_identity_in_both(self):
        mod = _load_sidecar()
        missing = '/nonexistent/state.db'
        sids = ['a', 'b', '']
        for s in sids:
            self.assertEqual(s, mod.get_root_session_id(s, state_db_path=missing))
        batch = mod.get_root_session_ids(sids, state_db_path=missing)
        self.assertEqual({s: s for s in sids}, batch)

    def test_batch_cli_emits_tsv_matching_per_session_cli(self):
        """The wire format the bash side actually consumes."""
        rows, sids = self._corpus()
        with tempfile.TemporaryDirectory(prefix='gsd-lt6-cli-') as tmp:
            hermes_home = os.path.join(tmp, 'hh')
            os.makedirs(hermes_home)
            db = os.path.join(hermes_home, 'state.db')
            self._build_db(db, rows)
            env = {**os.environ, 'HERMES_HOME': hermes_home}

            non_empty = [s for s in sids if s]
            r = subprocess.run(
                [sys.executable, str(SIDECAR), '--batch'],
                input='\n'.join(non_empty) + '\n',
                env=env, capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(0, r.returncode, r.stderr)

            got = {}
            for line in r.stdout.splitlines():
                if not line:
                    continue
                sid, _, root = line.partition('\t')
                got[sid] = root
            self.assertEqual(
                set(non_empty), set(got), 'batch must emit one row per input sid'
            )

            for s in non_empty:
                single = subprocess.run(
                    [sys.executable, str(SIDECAR), s],
                    env=env, capture_output=True, text=True, timeout=30,
                )
                self.assertEqual(0, single.returncode, single.stderr)
                self.assertEqual(
                    single.stdout.strip(), got[s],
                    f'CLI batch/per-session mismatch for {s!r}',
                )

    def test_parent_outside_requested_set_still_resolves(self):
        """Guards against a `WHERE id IN (<inputs>)` optimisation.

        Restricting the map to the requested sids makes an unrequested parent
        look like an absent row, which terminates the walk early and returns a
        subagent as its own root -- i.e. it would be treated as a job-creating
        root session.
        """
        mod = _load_sidecar()
        rows, _ = self._corpus()
        with tempfile.TemporaryDirectory(prefix='gsd-lt6-outside-') as tmp:
            db = os.path.join(tmp, 'state.db')
            self._build_db(db, rows)
            only_child = mod.get_root_session_ids(
                ['has_unrequested_parent'], state_db_path=db
            )
            self.assertEqual(
                'orphan_parent', only_child['has_unrequested_parent'],
                'the parent was not in the requested set but must still be '
                'followed; returning the input would promote a subagent to a root',
            )


class RootSidMapBashSeamTests(unittest.TestCase):
    """common.sh's fast path must agree with its own fallback.

    The map is an optimisation with a safety-critical failure mode: a MISS
    must fall through to the per-session python3 call, NOT return the input
    sid. Returning the input would promote every un-mapped subagent into a
    root, and `root_sid == sid` is the gate that decides whether a job is
    created -- so the cheap wrong answer is a billing change, not a slow one.
    """

    COMMON = SKILL / 'scripts' / 'common.sh'

    def _db(self, tmp):
        hermes_home = os.path.join(tmp, 'hh')
        os.makedirs(hermes_home, exist_ok=True)
        db = os.path.join(hermes_home, 'state.db')
        conn = sqlite3.connect(db)
        try:
            conn.execute(
                'CREATE TABLE sessions (id TEXT PRIMARY KEY, parent_session_id TEXT)'
            )
            conn.executemany(
                'INSERT INTO sessions (id, parent_session_id) VALUES (?, ?)',
                [('root1', None), ('kid1', 'root1'), ('kid2', 'kid1'),
                 ('root2', None), ('kid3', 'root2')],
            )
            conn.commit()
        finally:
            conn.close()
        return hermes_home

    def _run(self, script, hermes_home):
        env = {
            **os.environ,
            'HERMES_HOME': hermes_home,
            'REVENIUM_STATE_DIR': os.path.join(hermes_home, 'state', 'revenium'),
        }
        return subprocess.run(
            ['bash', '-c', script], env=env,
            capture_output=True, text=True, timeout=60,
        )

    def test_map_path_and_fallback_path_agree(self):
        with tempfile.TemporaryDirectory(prefix='gsd-lt6-seam-') as tmp:
            hh = self._db(tmp)
            mapf = os.path.join(tmp, 'map.tsv')
            script = '\n'.join([
                'set -uo pipefail',
                'source "%s"' % self.COMMON,
                'SIDS="root1 kid1 kid2 kid3"',
                'echo "--- nomap ---"',
                'for s in $SIDS; do echo "$s=$(get_root_session_id "$s")"; done',
                'printf "%s\\n" $SIDS | build_root_sid_map "' + mapf + '"',
                'export ROOT_SID_MAP_FILE="' + mapf + '"',
                'echo "--- withmap ---"',
                'for s in $SIDS; do echo "$s=$(get_root_session_id "$s")"; done',
            ])
            r = self._run(script, hh)
            self.assertEqual(0, r.returncode, r.stderr)
            out = r.stdout
            nomap = out.split('--- nomap ---')[1].split('--- withmap ---')[0].strip()
            withmap = out.split('--- withmap ---')[1].strip()
            self.assertTrue(nomap, 'no output captured: %r' % out)
            self.assertEqual(
                nomap, withmap,
                'the batch map must produce byte-identical roots to the '
                'per-session path',
            )
            # The values must be the REAL roots, not identity -- otherwise both
            # halves could agree by being equally wrong.
            self.assertIn('kid2=root1', nomap)
            self.assertIn('kid3=root2', nomap)

    def test_map_miss_falls_through_rather_than_returning_input(self):
        """THE safety property: a sid absent from the map is not a root."""
        with tempfile.TemporaryDirectory(prefix='gsd-lt6-miss-') as tmp:
            hh = self._db(tmp)
            mapf = os.path.join(tmp, 'partial.tsv')
            Path(mapf).write_text('root1\troot1\nkid1\troot1\n')  # omits kid2
            script = '\n'.join([
                'set -uo pipefail',
                'source "%s"' % self.COMMON,
                'export ROOT_SID_MAP_FILE="' + mapf + '"',
                'echo "kid2=$(get_root_session_id kid2)"',
            ])
            r = self._run(script, hh)
            self.assertEqual(0, r.returncode, r.stderr)
            self.assertIn(
                'kid2=root1', r.stdout,
                'a map MISS must fall through to the per-session resolver; '
                'returning the input sid would turn an un-mapped subagent into '
                'a job-creating root',
            )

    def test_absent_map_file_is_todays_behaviour(self):
        with tempfile.TemporaryDirectory(prefix='gsd-lt6-absent-') as tmp:
            hh = self._db(tmp)
            script = '\n'.join([
                'set -uo pipefail',
                'source "%s"' % self.COMMON,
                'export ROOT_SID_MAP_FILE="' + os.path.join(tmp, 'nope.tsv') + '"',
                'echo "kid2=$(get_root_session_id kid2)"',
            ])
            r = self._run(script, hh)
            self.assertEqual(0, r.returncode, r.stderr)
            self.assertIn('kid2=root1', r.stdout)

    def test_substring_sid_does_not_match_wrong_row(self):
        """Anchored whole-field match, not a substring grep."""
        with tempfile.TemporaryDirectory(prefix='gsd-lt6-substr-') as tmp:
            hh = self._db(tmp)
            mapf = os.path.join(tmp, 'map.tsv')
            # 'kid1' is a substring of 'kid1extra'; a grep-based lookup could
            # return kid1extra's root depending on file order.
            Path(mapf).write_text('kid1extra\tWRONG\nkid1\troot1\n')
            script = '\n'.join([
                'set -uo pipefail',
                'source "%s"' % self.COMMON,
                'export ROOT_SID_MAP_FILE="' + mapf + '"',
                'echo "kid1=$(get_root_session_id kid1)"',
            ])
            r = self._run(script, hh)
            self.assertEqual(0, r.returncode, r.stderr)
            self.assertIn('kid1=root1', r.stdout)
            self.assertNotIn('WRONG', r.stdout)
    def test_fast_path_is_actually_exercised_not_silently_falling_back(self):
        """Guards this whole test class against vacuity.

        If build_root_sid_map ever produced an empty or broken file, every
        lookup would MISS, fall back to the per-session resolver, and
        test_map_path_and_fallback_path_agree would still pass -- comparing
        the fallback against itself while the optimisation did nothing.

        A python3 that always fails discriminates the two paths cleanly: with
        a populated map the answer comes from the file (root1); without one
        the fallback's own `|| printf sid` guard yields the input (kid2). If
        this ever reports kid2 WITH a map, the fast path is dead code.
        """
        with tempfile.TemporaryDirectory(prefix='gsd-lt6-vac-') as tmp:
            hh = self._db(tmp)
            stub_dir = os.path.join(tmp, 'stub')
            os.makedirs(stub_dir)
            stub = os.path.join(stub_dir, 'python3')
            Path(stub).write_text('#!/bin/sh\nexit 97\n')
            os.chmod(stub, 0o755)

            mapf = os.path.join(tmp, 'map.tsv')
            # Built with a REAL python3, before the stub shadows it.
            build = '\n'.join([
                'set -uo pipefail',
                'source "%s"' % self.COMMON,
                'printf "%s\\n" root1 kid1 kid2 | build_root_sid_map "' + mapf + '"',
            ])
            rb = self._run(build, hh)
            self.assertEqual(0, rb.returncode, rb.stderr)
            self.assertTrue(
                os.path.getsize(mapf) > 0,
                'the map must be non-empty, or every later lookup silently '
                'falls back and this class proves nothing',
            )

            env_prefix = 'export PATH="%s:$PATH"\n' % stub_dir
            with_map = env_prefix + '\n'.join([
                'set -uo pipefail',
                'source "%s"' % self.COMMON,
                'export ROOT_SID_MAP_FILE="' + mapf + '"',
                'echo "kid2=$(get_root_session_id kid2)"',
            ])
            r1 = self._run(with_map, hh)
            self.assertEqual(0, r1.returncode, r1.stderr)
            self.assertIn(
                'kid2=root1', r1.stdout,
                'with a populated map and a broken python3, the answer can '
                'ONLY have come from the map -- if this is kid2, the fast '
                'path is never taken and the optimisation is dead code',
            )

            without_map = env_prefix + '\n'.join([
                'set -uo pipefail',
                'source "%s"' % self.COMMON,
                'echo "kid2=$(get_root_session_id kid2)"',
            ])
            r2 = self._run(without_map, hh)
            self.assertEqual(0, r2.returncode, r2.stderr)
            self.assertIn(
                'kid2=kid2', r2.stdout,
                'without a map and with python3 broken, the documented '
                'fail-open is the input sid; if this changed, the '
                'discriminator above no longer discriminates',
            )
class BatchFailureMustNotPublishIdentityTests(unittest.TestCase):
    """A batch build that cannot read state.db must emit NOTHING.

    Found in review of #129. The original shape pre-seeded an identity map,
    returned it on any database error, and exited 0 -- so an unreadable
    state.db during the map build published `child -> child` for every
    session in the tick. The shell side treats a populated entry as
    authoritative and never falls through, so every subagent would be
    promoted to a root. `root_sid == sid` is the gate that decides whether a
    job is CREATED, making this a billing-attribution change that looks
    exactly like success: exit 0, a full map, no warning.

    Identity is the correct fail-open for a DIRECT caller of
    get_root_session_id / get_root_session_ids -- it mirrors the per-session
    contract. It is only poison when written into a lookup table another
    layer trusts. These tests pin that distinction, because collapsing the
    two is how the bug arose.
    """

    def _db(self, tmp, readable=True):
        hermes_home = os.path.join(tmp, 'hh')
        os.makedirs(hermes_home, exist_ok=True)
        db = os.path.join(hermes_home, 'state.db')
        conn = sqlite3.connect(db)
        try:
            conn.execute(
                'CREATE TABLE sessions (id TEXT PRIMARY KEY, parent_session_id TEXT)'
            )
            conn.executemany(
                'INSERT INTO sessions (id, parent_session_id) VALUES (?, ?)',
                [('root1', None), ('kid1', 'root1')],
            )
            conn.commit()
        finally:
            conn.close()
        if not readable:
            os.chmod(db, 0o000)
        return hermes_home, db

    def test_unreadable_db_emits_nothing_and_signals_failure(self):
        with tempfile.TemporaryDirectory(prefix='gsd-lt6-dbfail-') as tmp:
            hh, db = self._db(tmp, readable=False)
            try:
                r = subprocess.run(
                    [sys.executable, str(SIDECAR), '--batch'],
                    input='kid1\n',
                    env={**os.environ, 'HERMES_HOME': hh},
                    capture_output=True, text=True, timeout=30,
                )
                self.assertEqual(
                    '', r.stdout.strip(),
                    'a batch build that could not read state.db must emit NO '
                    'rows; emitting kid1->kid1 publishes a subagent as a '
                    'job-creating root for the whole tick',
                )
                self.assertNotEqual(
                    0, r.returncode,
                    'it must also signal failure, so build_root_sid_map does '
                    'not mistake silence for an empty-but-valid map',
                )
            finally:
                os.chmod(db, 0o644)

    def test_missing_db_emits_nothing(self):
        with tempfile.TemporaryDirectory(prefix='gsd-lt6-nodb-') as tmp:
            hh = os.path.join(tmp, 'hh')
            os.makedirs(hh)
            r = subprocess.run(
                [sys.executable, str(SIDECAR), '--batch'],
                input='kid1\n',
                env={**os.environ, 'HERMES_HOME': hh},
                capture_output=True, text=True, timeout=30,
            )
            self.assertEqual('', r.stdout.strip())
            self.assertNotEqual(0, r.returncode)

    def test_end_to_end_a_failed_build_leaves_lookups_falling_through(self):
        """The property that matters: a failed build must not poison the tick.

        Builds the map against an unreadable database, then makes the
        database readable again -- exactly Greptile's transient case -- and
        asserts the lookup still resolves kid1 to its real root via the
        per-session fallback rather than returning kid1.
        """
        with tempfile.TemporaryDirectory(prefix='gsd-lt6-transient-') as tmp:
            hh, db = self._db(tmp, readable=False)
            mapf = os.path.join(tmp, 'map.tsv')
            common = SKILL / 'scripts' / 'common.sh'
            build = '\n'.join([
                'set -uo pipefail',
                'source "%s"' % common,
                'printf "%s\\n" kid1 | build_root_sid_map "' + mapf + '"',
            ])
            env = {**os.environ, 'HERMES_HOME': hh,
                   'REVENIUM_STATE_DIR': os.path.join(hh, 'state', 'revenium')}
            rb = subprocess.run(['bash', '-c', build], env=env,
                                capture_output=True, text=True, timeout=60)
            self.assertEqual(0, rb.returncode, rb.stderr)
            self.assertEqual(
                0, os.path.getsize(mapf),
                'a failed build must leave an EMPTY map, never a map of '
                'identity answers',
            )

            # The database recovers before the loop runs.
            os.chmod(db, 0o644)
            lookup = '\n'.join([
                'set -uo pipefail',
                'source "%s"' % common,
                'export ROOT_SID_MAP_FILE="' + mapf + '"',
                'echo "kid1=$(get_root_session_id kid1)"',
            ])
            rl = subprocess.run(['bash', '-c', lookup], env=env,
                                capture_output=True, text=True, timeout=60)
            self.assertEqual(0, rl.returncode, rl.stderr)
            self.assertIn(
                'kid1=root1', rl.stdout,
                'after a failed build the lookup must fall through to the '
                'per-session resolver, which retries the database itself; '
                'kid1=kid1 here would mean the tick was poisoned',
            )

    def test_direct_callers_still_get_identity_fail_open(self):
        """The distinction: identity is still correct for direct callers."""
        mod = _load_sidecar()
        missing = '/nonexistent/state.db'
        self.assertEqual('a', mod.get_root_session_id('a', state_db_path=missing))
        self.assertEqual(
            {'a': 'a'}, mod.get_root_session_ids(['a'], state_db_path=missing),
            'get_root_session_ids keeps its documented identity fail-open; '
            'only the CLI batch EMITTER withholds, because only its output '
            'is trusted as authoritative by another layer',
        )
        self.assertIsNone(
            mod._load_parent_map(state_db_path=missing),
            'None is the "could not read" signal and must stay distinct from '
            'an empty dict, which means "read it, no rows"',
        )

if __name__ == '__main__':
    unittest.main()
