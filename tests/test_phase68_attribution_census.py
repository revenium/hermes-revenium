"""Phase 68 plan 03: contract tests for the job-attribution census harness.

`tests/job_attribution_harness.py` is operator-invoked, stdlib only and
read-only against every host. These tests carry one fake host through the real
`pull` subcommand (a stand-in `ssh` that runs each remote command under a
temporary home), then check the census arithmetic, the privacy of every
aggregate, the remote-command allowlist and the redaction audit.

Nothing here touches a real host, a real tenant, or the network.
"""
import calendar
import contextlib
import io
import json
import os
import re
import shlex
import shutil
import sqlite3
import stat
import tempfile
import textwrap
import unittest
from decimal import Decimal
from fractions import Fraction
from pathlib import Path

from tests import job_attribution_harness as H
from tests._compat_helpers import (
    SCRIPTS_DIR,
    argv_to_flags,
    build_shim,
    build_state_db,
    run_script,
    seed_parent_session_ids,
)

ROOT = Path(__file__).resolve().parents[1]

# Distinctive strings planted in every identifying field. None may reach an
# aggregate file.
SENT_SID = 'zq7sidsentinel'
SENT_MUID = 'zq7muidsentinel'
SENT_JOB_ID = 'zq7jobidsentinel_ab12'
SENT_JOB_NAME = 'Zq7 JobNameSentinel run'
SENT_JOB_TYPE = 'zq7jobtypesentinel'
SENT_TITLE = 'zq7titlesentinel Person'
SENT_TENANT = 'zq7tenantsentinel'

SLICE = 'Jupiter'


def _scratch_root():
    """A directory that `git check-ignore` ignores (`.cache/` is ignored by
    the committed .gitignore), so `pull` accepts it as an out-dir."""
    base = ROOT / '.cache'
    base.mkdir(exist_ok=True)
    return tempfile.mkdtemp(prefix='gsd-p68-census-', dir=str(base))


def _cleanup(path):
    shutil.rmtree(path, ignore_errors=True)
    cache = ROOT / '.cache'
    try:
        cache.rmdir()  # only succeeds when empty
    except OSError:
        pass


def _run_main(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = H.main(argv)
    return rc, out.getvalue(), err.getvalue()


def _json_text(value):
    return json.dumps(value)


def tracer_rows(agent=SLICE, n=137, start=0):
    """`n` completion rows for `agent`. Even indices carry a job id."""
    costs = (0.1, 0.2, 0.3, 0.05, 0.15)
    rows = []
    for i in range(start, start + n):
        rows.append({
            'agent': agent,
            'agenticJobId': SENT_JOB_ID if i % 2 == 0 else None,
            'agenticJobName': SENT_JOB_NAME if i % 2 == 0 else None,
            'agenticJobType': SENT_JOB_TYPE if i % 2 == 0 else None,
            'transactionId': f'{SENT_SID}1-150-{SENT_MUID}{i}',
            'totalCost': costs[i % 5],
            'requestTime': '2026-10-01T00:00:00Z',
        })
    return rows


class FakeHost:
    """A fake remote host: a HERMES_HOME under a temp root, a fake `revenium`
    on a bin dir, and a stand-in `ssh` that logs each invocation and runs its
    last argument with `bash -c` under HOME=<root>."""

    def __init__(self, tmp):
        self.tmp = Path(tmp)
        self.root = self.tmp / 'host'
        self.hermes = self.root / '.hermes'
        self.state = self.hermes / 'state' / 'revenium'
        self.markers = self.state / 'markers'
        self.bin = self.root / 'bin'
        self.fake = self.root / 'fake'
        self.ssh_log = self.tmp / 'ssh.log'
        self.ssh = self.tmp / 'fake-ssh'
        for d in (self.markers, self.bin, self.fake / 'completions',
                  self.fake / 'jobs'):
            d.mkdir(parents=True, exist_ok=True)
        self._write_ssh()
        self._write_revenium()

    def _write_ssh(self):
        self.ssh.write_text(textwrap.dedent(f'''\
            #!/usr/bin/env bash
            printf '%s\\n' "$*" >> '{self.ssh_log}'
            cmd="${{@: -1}}"
            export HOME='{self.root}'
            exec bash -c "$cmd"
        '''))
        self.ssh.chmod(0o755)

    def _write_revenium(self):
        script = self.bin / 'revenium'
        script.write_text(textwrap.dedent(f'''\
            #!/usr/bin/env python3
            import json, os, sys
            args = sys.argv[1:]
            fake = '{self.fake}'
            if args[:1] == ['--version']:
                print('revenium version 9.9.9')
                sys.exit(0)
            if args[:2] == ['tenants', 'get']:
                print(json.dumps({{'id': '{SENT_TENANT}'}}))
                sys.exit(0)
            if args[:2] == ['metrics', 'completions']:
                kind = 'completions'
            elif args[:2] == ['jobs', 'list']:
                kind = 'jobs'
            else:
                sys.stderr.write('unexpected verb: %r\\n' % (args,))
                sys.exit(64)
            page = int(args[args.index('--page') + 1])
            for name in ('page-%d.json' % page, 'repeat.json'):
                p = os.path.join(fake, kind, name)
                if os.path.isfile(p):
                    sys.stdout.write(open(p).read())
                    sys.exit(0)
            print('[]')
        '''))
        script.chmod(0o755)

    # -- host content ------------------------------------------------------
    def write_marker_file(self, sid, records):
        with open(self.markers / f'{sid}.jsonl', 'w') as handle:
            for rec in records:
                handle.write(json.dumps(rec, separators=(',', ':')) + '\n')

    def write_ledgers(self, hermes=(), jobs=(), events=None):
        (self.state / 'revenium-hermes.ledger').write_text(
            ''.join(line + '\n' for line in hermes))
        (self.state / 'revenium-jobs.ledger').write_text(
            ''.join(line + '\n' for line in jobs))
        if events is not None:
            (self.state / 'revenium-api-events.ledger').write_text(
                ''.join(line + '\n' for line in events))

    def write_sessions(self, rows, with_parent=True):
        db = self.hermes / 'state.db'
        conn = sqlite3.connect(str(db))
        parent = ', parent_session_id TEXT' if with_parent else ''
        conn.execute(
            'CREATE TABLE sessions (id TEXT PRIMARY KEY, source TEXT, '
            'started_at REAL, input_tokens INTEGER, output_tokens INTEGER, '
            'estimated_cost_usd REAL, title TEXT' + parent + ')')
        for row in rows:
            if with_parent:
                conn.execute('INSERT INTO sessions VALUES (?,?,?,?,?,?,?,?)',
                             row)
            else:
                conn.execute('INSERT INTO sessions VALUES (?,?,?,?,?,?,?)',
                             row[:7])
        conn.commit()
        conn.close()

    def write_pages(self, kind, pages):
        for index, rows in enumerate(pages):
            (self.fake / kind / f'page-{index}.json').write_text(
                _json_text(rows))

    def pull_argv(self, out_dir, extra=()):
        return ['pull', '--ssh-cmd', str(self.ssh), '--ssh-target', 'fake',
                '--ssh-key', 'KEY', '--host-label', 't',
                '--bin-prefix', str(self.bin), '--agent', SLICE,
                '--to', '2026-10-08T00:00:00Z', '--out-dir', str(out_dir),
                *extra]


def _tracer_host(tmp):
    host = FakeHost(tmp)
    host.write_marker_file(f'{SENT_SID}1', [
        {'muid': f'{SENT_MUID}0', 'ts': 1000.0, 'sid': f'{SENT_SID}1',
         'task_type': 'code_review', 'operation_type': 'GUARDRAIL'},
        {'muid': f'{SENT_MUID}1', 'ts': 1000.1, 'sid': f'{SENT_SID}1',
         'task_type': 'code_review', 'operation_type': 'CHAT'},
        {'kind': 'job', 'ts': 1001.0, 'sid': f'{SENT_SID}1',
         'agentic_job_id': SENT_JOB_ID, 'job_name': SENT_JOB_NAME,
         'job_type': SENT_JOB_TYPE, 'status': 'SUCCESS'},
    ])
    host.write_ledgers(
        hermes=[f'HERMES:{SENT_SID}1:150:1790000000:{SENT_MUID}0'],
        jobs=[f'JOB:{SENT_JOB_ID}:created:1790000000'])
    host.write_sessions([
        (f'{SENT_SID}1', 'cli', 1790000000.0, 100, 50, 1.5, SENT_TITLE, None),
        (f'{SENT_SID}2', 'cli', 1790000100.0, 10, 5, 0.25, 'plain', None),
        (f'{SENT_SID}3', 'cli', 1790000200.0, 10, 5, 0.25, 'plain',
         f'{SENT_SID}1'),
    ])
    rows = tracer_rows()
    host.write_pages('completions', [rows[:100], rows[100:], []])
    host.write_pages('jobs', [[{'agenticJobId': SENT_JOB_ID,
                                'name': SENT_JOB_NAME,
                                'type': SENT_JOB_TYPE,
                                'created': '2026-10-01T00:00:00Z'}], []])
    return host


class CensusTracerTests(unittest.TestCase):
    """One fake host, end to end, through the real `pull` subcommand."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = _scratch_root()
        cls.host = _tracer_host(cls.tmp)
        cls.out = Path(cls.tmp) / 'pulled'
        cls.rc, cls.stdout, cls.stderr = _run_main(
            cls.host.pull_argv(cls.out))
        cls.manifest = None
        if (cls.out / 'MANIFEST.json').exists():
            cls.manifest = json.loads(
                (cls.out / 'MANIFEST.json').read_text())
        cls.census_rc = None
        if cls.rc == 0:
            cls.census_rc, _o, _e = _run_main(
                ['census', '--out-dir', str(cls.out)])

    @classmethod
    def tearDownClass(cls):
        _cleanup(cls.tmp)

    def _census(self):
        return json.loads((self.out / 'census.json').read_text())

    def test_pull_exits_zero_and_writes_every_layer(self):
        self.assertEqual(self.rc, H.EXIT_OK, self.stderr)
        for rel in ('MANIFEST.json', 'revenium-hermes.ledger',
                    'revenium-jobs.ledger', 'state.db', 'sessions.schema.sql',
                    'sessions.dump.sql', 'completions/page-0000.json',
                    'jobs/page-0000.json'):
            self.assertTrue((self.out / rel).exists(), rel)
        self.assertTrue(
            (self.out / 'markers' / f'{SENT_SID}1.jsonl').exists())

    def test_manifest_digests_equal_the_real_file_digests(self):
        files = self.manifest['files']
        self.assertGreater(len(files), 6)
        for rel, meta in files.items():
            self.assertEqual(meta['sha256'], H.sha256_file(self.out / rel),
                             rel)
            self.assertEqual(meta['size'], (self.out / rel).stat().st_size)

    def test_markers_are_pulled_before_sessions_before_revenium(self):
        m = self.manifest
        stamp = re.compile(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$')
        for key in ('markers_pulled_at', 'sessions_pulled_at',
                    'revenium_pulled_at'):
            self.assertRegex(m[key], stamp)
        self.assertLess(m['markers_pulled_at'], m['sessions_pulled_at'])
        self.assertLess(m['sessions_pulled_at'], m['revenium_pulled_at'])

    def test_paging_stops_only_on_an_empty_page(self):
        paging = self.manifest['paging']['completions']
        self.assertEqual(paging['pages_read'], 3)
        self.assertTrue(paging['last_page_empty'])
        self.assertEqual(paging['first_page_index'], 0)
        rows = H.load_rows(self.out, 'completions')
        self.assertEqual(len(rows), 137)

    def test_census_coverage_block_matches_hand_computed_values(self):
        self.assertEqual(self.census_rc, H.EXIT_OK)
        rows = tracer_rows()
        total = sum(Fraction(str(r['totalCost'])) for r in rows)
        attributed = sum(Fraction(str(r['totalCost'])) for r in rows
                         if r['agenticJobId'])
        frac = attributed / total
        cov = self._census()['coverage']
        self.assertEqual(cov['rows_total'], 137)
        self.assertEqual(cov['rows_attributed'], 69)
        self.assertEqual(cov['fraction'],
                         f'{frac.numerator}/{frac.denominator}')
        # independent half-even rounding to two decimals
        hundredths = frac * 10000
        q, r = divmod(hundredths.numerator, hundredths.denominator)
        if 2 * Fraction(r, hundredths.denominator) > 1 or (
                2 * Fraction(r, hundredths.denominator) == 1 and q % 2):
            q += 1
        self.assertEqual(cov['display_pct'], f'{q // 100}.{q % 100:02d}%')
        self.assertEqual(Decimal(cov['cost_total']),
                         Decimal(total.numerator) / Decimal(total.denominator))

    def test_every_written_file_is_mode_0600_and_keys_are_whitelisted(self):
        for name in ('census.json', 'census-private.json', 'MANIFEST.json',
                     'denylist.json'):
            mode = stat.S_IMODE((self.out / name).stat().st_mode)
            self.assertEqual(mode, 0o600, name)
        self.assertLessEqual(set(self._census()), H.AGGREGATE_KEYS)

    def test_no_identifier_reaches_an_aggregate(self):
        text = (self.out / 'census.json').read_text().lower()
        for sentinel in (SENT_SID, SENT_MUID, SENT_JOB_ID, SENT_JOB_NAME,
                         SENT_JOB_TYPE, SENT_TITLE, SENT_TENANT,
                         'jobnamesentinel', 'titlesentinel'):
            self.assertNotIn(sentinel.lower(), text, sentinel)

    def test_denylist_holds_name_tokens_and_drops_allow_listed_words(self):
        deny = json.loads((self.out / 'denylist.json').read_text())
        tokens = set(deny['tokens'])
        for expected in ('jobnamesentinel', 'zq7jobtypesentinel',
                         'zq7titlesentinel', 'person'):
            self.assertIn(expected, tokens)
        self.assertIn(SENT_JOB_ID, deny['deny_exact'])
        self.assertFalse(tokens & H.DENYLIST_ALLOW)
        self.assertTrue(all(len(t) >= 4 for t in tokens))
        self.assertTrue(all(t == t.lower() for t in tokens))

    def test_the_tenant_answer_is_recorded_in_the_manifest_only(self):
        self.assertIn(SENT_TENANT, json.dumps(self.manifest['tenant']))
        self.assertNotIn(SENT_TENANT,
                         (self.out / 'census.json').read_text())

    def test_census_refuses_when_a_pulled_file_drifted(self):
        copy = Path(self.tmp) / 'drifted'
        shutil.copytree(self.out, copy)
        with open(copy / 'revenium-hermes.ledger', 'a') as handle:
            handle.write('HERMES:tampered:1:1:m\n')
        (copy / 'census.json').unlink(missing_ok=True)
        rc, _o, _e = _run_main(['census', '--out-dir', str(copy)])
        self.assertEqual(rc, H.EXIT_DRIFT)
        self.assertFalse((copy / 'census.json').exists())


class PagingFailureTests(unittest.TestCase):
    def test_a_verb_that_never_returns_an_empty_page_exits_paging(self):
        tmp = _scratch_root()
        try:
            host = _tracer_host(tmp)
            full = tracer_rows(n=100)
            (host.fake / 'completions' / 'repeat.json').write_text(
                _json_text(full))
            for page in (0, 1, 2):
                (host.fake / 'completions' / f'page-{page}.json').unlink()
            out = Path(tmp) / 'pulled'
            rc, _o, err = _run_main(
                host.pull_argv(out, ['--max-pages', '5']))
            self.assertEqual(rc, H.EXIT_PAGING, err)
            self.assertFalse((out / 'census.json').exists())
        finally:
            _cleanup(tmp)

    def test_an_unknown_page_shape_exits_paging_rather_than_guessing(self):
        tmp = _scratch_root()
        try:
            host = _tracer_host(tmp)
            (host.fake / 'completions' / 'page-0.json').write_text(
                '{"unexpected": 1}')
            out = Path(tmp) / 'pulled'
            rc, _o, _e = _run_main(host.pull_argv(out))
            self.assertEqual(rc, H.EXIT_PAGING)
        finally:
            _cleanup(tmp)

    def test_a_dict_envelope_with_a_list_is_read(self):
        self.assertEqual(
            H.page_rows('{"content": [{"a": 1}]}'), [{'a': 1}])
        self.assertEqual(H.page_rows('[]'), [])
        with self.assertRaises(H.PagingError):
            H.page_rows('"text"')


class OutDirGuardTests(unittest.TestCase):
    def test_an_out_dir_git_does_not_ignore_exits_usage_with_no_remote_command(
            self):
        tmp = _scratch_root()
        outside = tempfile.mkdtemp(prefix='gsd-p68-outside-')
        try:
            host = _tracer_host(tmp)
            rc, _o, err = _run_main(
                host.pull_argv(Path(outside) / 'pulled'))
            self.assertEqual(rc, H.EXIT_USAGE, err)
            self.assertFalse(host.ssh_log.exists()
                             and host.ssh_log.read_text().strip())
        finally:
            shutil.rmtree(outside, ignore_errors=True)
            _cleanup(tmp)

    def test_a_non_empty_out_dir_is_refused_before_any_remote_command(self):
        tmp = _scratch_root()
        try:
            host = _tracer_host(tmp)
            out = Path(tmp) / 'pulled'
            out.mkdir()
            stale = out / 'completions-page-99.json'
            stale.write_text('[]')
            rc, _o, err = _run_main(host.pull_argv(out))
            self.assertEqual(rc, H.EXIT_USAGE, err)
            self.assertIn('not empty', err)
            self.assertEqual(sorted(p.name for p in out.iterdir()),
                             [stale.name])
            self.assertFalse(host.ssh_log.exists()
                             and host.ssh_log.read_text().strip())
        finally:
            _cleanup(tmp)

    def test_an_existing_empty_out_dir_is_still_accepted(self):
        tmp = _scratch_root()
        try:
            host = _tracer_host(tmp)
            out = Path(tmp) / 'pulled'
            out.mkdir()
            rc, _o, err = _run_main(host.pull_argv(out))
            self.assertEqual(rc, H.EXIT_OK, err)
        finally:
            _cleanup(tmp)

    def test_a_tracked_looking_path_inside_the_repo_is_refused_too(self):
        tmp = _scratch_root()
        try:
            host = _tracer_host(tmp)
            rc, _o, _e = _run_main(
                host.pull_argv(ROOT / 'tests' / 'zz-not-ignored'))
            self.assertEqual(rc, H.EXIT_USAGE)
            self.assertFalse((ROOT / 'tests' / 'zz-not-ignored').exists())
        finally:
            _cleanup(tmp)


class ArithmeticTests(unittest.TestCase):
    def _row(self, agent, cost, job=None):
        return {'agent': agent, 'agenticJobId': job,
                'totalCost': H.parse_json(cost)}

    def test_costs_are_exact_decimals_not_floats(self):
        rows = [self._row(SLICE, '0.1', 'j'), self._row(SLICE, '0.2')]
        cov = H.coverage(rows, SLICE)
        self.assertEqual(Decimal(cov['cost_total']), Decimal('0.3'))
        self.assertEqual(cov['cost_total'], '0.3')
        self.assertEqual(cov['fraction'], '1/3')
        self.assertEqual(cov['display_pct'], '33.33%')

    def test_json_parse_keeps_decimal_precision(self):
        value = H.parse_json('{"c": 0.30000000000000004}')['c']
        self.assertIsInstance(value, Decimal)
        self.assertEqual(value, Decimal('0.30000000000000004'))

    def test_display_pct_rounds_half_even_to_two_places(self):
        self.assertEqual(H.display_pct(Fraction(1, 8)), '12.50%')
        # 0.125% -> 12.5 hundredths -> tie -> even (12)
        self.assertEqual(H.display_pct(Fraction(125, 100000)), '0.12%')
        self.assertEqual(H.display_pct(Fraction(375, 100000)), '0.38%')
        self.assertEqual(H.display_pct(Fraction(0, 1)), '0.00%')

    def test_a_second_agent_changes_nothing_and_is_never_aggregated(self):
        mine = [self._row(SLICE, '1.50', 'j'), self._row(SLICE, '0.50')]
        other = [self._row('Hermes-ent', '99.00', 'x'),
                 self._row('Hermes-ent', '1.00')]
        solo = H.coverage(mine, SLICE)
        mixed = H.coverage(mine + other, SLICE)
        self.assertEqual(solo, mixed)
        self.assertEqual(set(solo), {
            'rows_total', 'rows_attributed', 'cost_total', 'cost_attributed',
            'fraction', 'display_pct', 'rows_display_pct',
            'rows_missing_cost'})

    def test_agent_match_is_exact_and_null_cost_counts_as_zero(self):
        rows = [self._row(SLICE, '1.0', 'j'),
                self._row('jupiter', '5.0', 'j'),
                {'agent': SLICE, 'agenticJobId': 'j', 'totalCost': None}]
        cov = H.coverage(rows, SLICE)
        self.assertEqual(cov['rows_total'], 2)
        self.assertEqual(cov['rows_missing_cost'], 1)
        self.assertEqual(cov['fraction'], '1/1')

    def test_an_empty_slice_is_zero_over_one(self):
        cov = H.coverage([], SLICE)
        self.assertEqual(cov['fraction'], '0/1')
        self.assertEqual(cov['display_pct'], '0.00%')


class RemoteCommandAllowlistTests(unittest.TestCase):
    SAMPLE = {
        'state_dir': '~/.hermes/state/revenium',
        'db': '~/.hermes/state.db',
        'bin_prefix': '/home/linuxbrew/.linuxbrew/bin',
        'from_iso': '2026-09-08T00:00:00Z',
        'to_iso': '2026-10-08T00:00:00Z',
        'page': 0,
        'hermes_home': '~/.hermes',
        'columns': 'session_id, role, content, timestamp, id',
        'sid_list': "'20261001_000001_ab12cd', 'a:b.c-d'",
        'order_by': 'session_id, timestamp, id',
        'file_list': 'api-events/20261001_000001_ab12cd.jsonl',
    }

    def test_every_template_is_accepted(self):
        self.assertGreaterEqual(len(H.REMOTE_COMMAND_TEMPLATES), 14)
        for name, template in H.REMOTE_COMMAND_TEMPLATES.items():
            cmd = template.format(**self.SAMPLE)
            H.validate_remote_command(cmd)  # must not raise

    def test_dangerous_commands_are_rejected(self):
        bad = {
            'redirect': 'cat ~/.hermes/state/revenium/revenium-api-events.'
                        'ledger > /tmp/x',
            'append': 'cat ~/.hermes/state/revenium/revenium-api-events.'
                      'ledger >> /tmp/x',
            'rm': 'rm -rf ~/.hermes',
            'mv': 'mv a b',
            'cp': 'cp a b',
            'tee': 'cat a | tee b',
            'mkdir': 'mkdir x',
            'touch': 'touch x',
            'chmod': 'chmod 600 x',
            'sed-i': 'sed -i s/a/b/ x',
            'crontab': 'crontab -r',
            'systemctl': 'systemctl restart hermes',
            'kill': 'kill -9 1',
            'sqlite-rw': 'sqlite3 ~/.hermes/state.db ".dump sessions"',
            'sqlite-write': 'sqlite3 -readonly ~/.hermes/state.db '
                            '"DELETE FROM sessions"',
            'sqlite-shell': 'sqlite3 -readonly ~/.hermes/state.db '
                            '".shell id"',
            'tar-extract': 'tar -xf - -C ~',
            'chain': 'cat ~/.hermes/state/revenium/revenium-api-events.'
                     'ledger; rm x',
            'subshell': 'cat $(echo x)',
            'rev-meter': 'revenium meter completion --model m',
            'rev-jobs-create': 'revenium jobs create --name x',
            'rev-outcome': 'revenium jobs outcome j',
            'rev-config': 'revenium config set a b',
            'unknown': 'curl http://example.com',
        }
        for label, cmd in bad.items():
            with self.subTest(label):
                with self.assertRaises(H.RemoteCommandError):
                    H.validate_remote_command(cmd)

    def test_a_2_devnull_redirect_is_the_only_one_allowed(self):
        H.validate_remote_command(
            'cat ~/.hermes/state/revenium/revenium-api-events.ledger '
            '2>/dev/null')
        with self.assertRaises(H.RemoteCommandError):
            H.validate_remote_command(
                'cat ~/.hermes/state/revenium/revenium-api-events.ledger '
                '2>/tmp/x')

    def test_every_command_a_real_pull_sent_is_an_allowlisted_rendering(self):
        tmp = _scratch_root()
        try:
            host = _tracer_host(tmp)
            rc, _o, err = _run_main(
                host.pull_argv(Path(tmp) / 'pulled'))
            self.assertEqual(rc, H.EXIT_OK, err)
            sent = [line.split(' ', 7)[-1] for line in
                    host.ssh_log.read_text().splitlines() if line]
            self.assertGreaterEqual(len(sent), 9)
            for cmd in sent:
                H.validate_remote_command(cmd)
            joined = '\n'.join(sent)
            self.assertNotIn(' meter ', joined)
            self.assertNotIn('rm ', joined)
        finally:
            _cleanup(tmp)

    def test_the_harness_never_references_a_production_writer(self):
        import ast
        tree = ast.parse(
            (ROOT / 'tests' / 'job_attribution_harness.py').read_text())
        seen = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                seen.add(node.id)
            elif isinstance(node, ast.Attribute):
                seen.add(node.attr)
        self.assertFalse(seen & H.FORBIDDEN_WRITERS,
                         seen & H.FORBIDDEN_WRITERS)

    def test_forbidden_writers_names_the_classifier_writers(self):
        for name in ('run_classification_async', '_write_job_marker',
                     'meter', 'outcome-update', 'create'):
            self.assertIn(name, H.FORBIDDEN_WRITERS)


class AuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix='gsd-p68-audit-')
        cls.denylist = Path(cls.tmp) / 'denylist.json'
        cls.denylist.write_text(json.dumps({
            'tokens': ['zq7jobtypesentinel', 'zqperson', 'coverage', 'false'],
            'deny_exact': [SENT_JOB_ID],
        }))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _audit(self, text, *extra):
        doc = Path(self.tmp) / 'doc.md'
        doc.write_text(text)
        return _run_main(['audit', str(doc), *extra])

    def test_a_planted_name_exits_1_and_only_the_masked_token_is_printed(self):
        rc, out, err = self._audit(
            'Clean line.\nThe report names zq7jobtypesentinel here.\n',
            '--denylist', str(self.denylist))
        self.assertEqual(rc, H.EXIT_AUDIT)
        self.assertIn('line 2:', out)
        self.assertIn('zq' + '*' * (len('zq7jobtypesentinel') - 2), out)
        self.assertNotIn('zq7jobtypesentinel', out + err)

    def test_a_session_id_shape_exits_1(self):
        rc, out, _e = self._audit('sid 20260518_063001_a1b2c3d4 here\n',
                                  '--shapes-only')
        self.assertEqual(rc, H.EXIT_AUDIT)
        self.assertIn('line 1:', out)
        self.assertNotIn('20260518_063001_a1b2c3d4', out)

    def test_a_clean_document_exits_0(self):
        rc, out, _e = self._audit(
            'Coverage was 97.14% of Jupiter slice dollars over 30 days.\n'
            'The commit abc is 0123456789abcdef0123456789abcdef01234567.\n',
            '--denylist', str(self.denylist))
        self.assertEqual(rc, H.EXIT_OK, out)

    def test_hex_lengths_32_and_33_are_muids_and_40_and_64_are_allowed(self):
        h32 = 'a' * 32
        h33 = 'b' * 33
        h40 = 'c' * 40
        h64 = 'd' * 64
        for token, expect in ((h32, 1), (h33, 1), (h40, 0), (h64, 0)):
            rc, _o, _e = self._audit(f'x {token} y\n', '--shapes-only')
            self.assertEqual(rc, expect, len(token))

    def test_other_redaction_shapes_are_caught(self):
        for text in ('host 10.1.2.3 up', 'mail a.b@example.org', 'key a.pem',
                     'login ubuntu', 'tenant 3By1Ra6', 'tenant aL7ZRO2',
                     'job daily_report_9f3a'):
            with self.subTest(text):
                rc, _o, _e = self._audit(text + '\n', '--shapes-only')
                self.assertEqual(rc, H.EXIT_AUDIT)

    def test_an_exact_job_id_substring_is_caught(self):
        rc, out, _e = self._audit(f'see {SENT_JOB_ID} please\n',
                                  '--denylist', str(self.denylist))
        self.assertEqual(rc, H.EXIT_AUDIT)
        self.assertNotIn(SENT_JOB_ID, out)

    def test_audit_without_a_denylist_or_shapes_only_is_a_usage_error(self):
        rc, _o, _e = self._audit('clean\n')
        self.assertEqual(rc, H.EXIT_USAGE)

    def test_matching_is_whole_word_and_case_insensitive(self):
        rc, _o, _e = self._audit('A ZQPERSON was named.\n',
                                 '--denylist', str(self.denylist))
        self.assertEqual(rc, H.EXIT_AUDIT)
        rc, _o, _e = self._audit('zqpersonnel are not a zqperson-name hit?\n',
                                 '--denylist', str(self.denylist))
        # "zqperson-name" splits on the hyphen, so the whole word hits
        self.assertEqual(rc, H.EXIT_AUDIT)
        rc, _o, _e = self._audit('zqpersonnel only\n',
                                 '--denylist', str(self.denylist))
        self.assertEqual(rc, H.EXIT_OK)

    def test_a_deny_listed_generic_word_the_repo_already_publishes_is_exempt(self):
        aggregate = json.dumps({'coverage': {'ok': False, 'cost': '1.00'}},
                               indent=2)
        rc, out, _e = self._audit(aggregate + '\n',
                                  '--denylist', str(self.denylist))
        self.assertEqual(rc, H.EXIT_OK, out)

    def test_the_exemption_never_hides_a_real_corpus_identifier(self):
        text = json.dumps({'coverage': 'zq7jobtypesentinel'}) + '\n'
        rc, out, err = self._audit(text, '--denylist', str(self.denylist))
        self.assertEqual(rc, H.EXIT_AUDIT)
        self.assertNotIn('zq7jobtypesentinel', out + err)
        rc, _o, _e = self._audit(f'see {SENT_JOB_ID} please\n',
                                 '--denylist', str(self.denylist))
        self.assertEqual(rc, H.EXIT_AUDIT)

    def test_no_public_vocab_restores_the_strict_match(self):
        rc, _o, _e = self._audit('coverage was measured\n',
                                 '--denylist', str(self.denylist),
                                 '--no-public-vocab')
        self.assertEqual(rc, H.EXIT_AUDIT)

    def test_audit_text_exempts_only_what_the_vocabulary_holds(self):
        vocab = H.public_vocabulary()
        self.assertIn('coverage', vocab)
        self.assertNotIn('zq7jobtypesentinel', vocab)
        hits = H.audit_text('zq7jobtypesentinel and coverage\n',
                            {'tokens': ['zq7jobtypesentinel', 'coverage']},
                            vocab)
        self.assertEqual([masked for _n, masked in hits],
                         ['zq' + '*' * (len('zq7jobtypesentinel') - 2)])

    def test_the_record_cannot_exempt_its_own_words(self):
        import io
        import tarfile
        from unittest import mock
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode='w') as tar:
            for name, body in ((H.RECORD_REL_PATH, b'zqrecordonly'),
                               ('docs/other.md', b'zqotherdoc')):
                info = tarfile.TarInfo(name)
                info.size = len(body)
                tar.addfile(info, io.BytesIO(body))
        done = mock.Mock(returncode=0, stdout=buf.getvalue())
        with mock.patch.object(H.subprocess, 'run', return_value=done):
            vocab = H.public_vocabulary()
        self.assertIn('zqotherdoc', vocab)
        self.assertNotIn('zqrecordonly', vocab)



# ---------------------------------------------------------------------------
# Plan 03 task 2: resolver replay, shape census, D-07, D-18, D-15a
# ---------------------------------------------------------------------------
WINDOW_FROM = '2026-09-08T00:00:00Z'
WINDOW_TO = '2026-10-08T00:00:00Z'


def _epoch(iso):
    return calendar.timegm(__import__('time').strptime(iso, '%Y-%m-%dT%H:%M:%SZ'))


IN_WIN = float(_epoch('2026-09-20T00:00:00Z'))
OUT_WIN = float(_epoch('2026-08-01T00:00:00Z'))


class Layout:
    """A pulled-host layout built directly on disk (no ssh), plus a manifest,
    so census arithmetic can be tested fast and exactly."""

    def __init__(self, tmp, with_parent=True):
        self.out = Path(tmp) / 'pulled'
        for sub in ('markers', 'completions', 'jobs'):
            (self.out / sub).mkdir(parents=True)
        self.with_parent = with_parent
        self.sessions = []
        self.rows = []
        self.hermes = []
        self.jobs = []
        self.events = None

    def marker_file(self, sid, shape, jobs=None):
        """Write `<sid>.jsonl` from a shape string. Returns (muids, job ids)."""
        muids, job_ids, records = [], [], []
        jobs = list(jobs or [])
        for index, char in enumerate(shape):
            if char == 'T':
                muid = f'{sid}-m{index}'
                muids.append(muid)
                first = shape.index('T') == index
                records.append({
                    'muid': muid, 'ts': 1000.0 + 10 * index, 'sid': sid,
                    'task_type': 'code_review',
                    'operation_type': ('GUARDRAIL' if first and
                                       shape.count('T') > 1 else 'CHAT'),
                    'trace_id': sid})
            else:
                job_id = jobs.pop(0) if jobs else f'j{index}x{sid}'
                job_ids.append(job_id)
                records.append({
                    'kind': 'job', 'ts': 1000.0 + 10 * index, 'sid': sid,
                    'agentic_job_id': job_id, 'job_name': 'a job',
                    'job_type': 'a_type', 'status': 'SUCCESS'})
        path = self.out / 'markers' / f'{sid}.jsonl'
        with open(path, 'w') as handle:
            for rec in records:
                handle.write(json.dumps(rec, separators=(',', ':')) + '\n')
        return muids, job_ids

    def session(self, sid, parent=None, tokens=1500, cost=1.0, started=IN_WIN):
        self.sessions.append((sid, started, tokens, 0, 0, 0, cost, parent))

    def row(self, sid, cost, job=None, muid=None, total=1500, agent=SLICE,
            txn=None):
        txn = txn or (f'{sid}-{total}-{muid}' if muid else f'{sid}-{total}')
        self.rows.append({'agent': agent, 'agenticJobId': job,
                          'transactionId': txn, 'totalCost': cost})

    def finish(self):
        db = self.out / 'state.db'
        conn = sqlite3.connect(str(db))
        extra = ', parent_session_id TEXT' if self.with_parent else ''
        conn.execute(
            'CREATE TABLE sessions (id TEXT PRIMARY KEY, started_at REAL, '
            'input_tokens INTEGER, output_tokens INTEGER, '
            'cache_read_tokens INTEGER, cache_write_tokens INTEGER, '
            'estimated_cost_usd REAL' + extra + ')')
        for sid, started, tokens, out_t, cr, cw, cost, parent in self.sessions:
            if self.with_parent:
                conn.execute('INSERT INTO sessions VALUES (?,?,?,?,?,?,?,?)',
                             (sid, started, tokens, out_t, cr, cw, cost,
                              parent))
            else:
                conn.execute('INSERT INTO sessions VALUES (?,?,?,?,?,?,?)',
                             (sid, started, tokens, out_t, cr, cw, cost))
        conn.commit()
        conn.close()
        (self.out / 'revenium-hermes.ledger').write_text(
            ''.join(line + '\n' for line in self.hermes))
        (self.out / 'revenium-jobs.ledger').write_text(
            ''.join(line + '\n' for line in self.jobs))
        if self.events is not None:
            (self.out / 'revenium-api-events.ledger').write_text(
                ''.join(line + '\n' for line in self.events))
        (self.out / 'completions' / 'page-0000.json').write_text(
            _json_text(self.rows))
        (self.out / 'completions' / 'page-0001.json').write_text('[]')
        (self.out / 'jobs' / 'page-0000.json').write_text('[]')
        return H.write_manifest(self.out, {
            'host_label': 't', 'slice_agent': SLICE,
            'window': {'from': WINDOW_FROM, 'to': WINDOW_TO, 'days': 30},
            'markers_pulled_at': '2026-10-08T00:00:01Z',
            'sessions_pulled_at': '2026-10-08T00:00:02Z',
            'revenium_pulled_at': '2026-10-08T00:00:03Z',
            'paging': {'completions': {'pages_read': 2, 'rows': len(self.rows),
                                       'last_page_empty': True,
                                       'first_page_index': 0},
                       'jobs': {'pages_read': 1, 'rows': 0,
                                'last_page_empty': True,
                                'first_page_index': 0}},
            'event_ledger_present': self.events is not None,
            'tenant': 'unavailable'})

    def census(self):
        manifest = self.finish()
        aggregate, private = H.build_census(self.out, manifest, SLICE)
        return aggregate, private


class _Scratch(unittest.TestCase):
    def setUp(self):
        self.tmp = _scratch_root()
        self.addCleanup(_cleanup, self.tmp)


# -- resolver replay pinned to both reporters ------------------------------
SHAPES = ('TJ', 'TTJ', 'TTJJ', 'TTJJTTTT', 'JTT', 'TT')


def _shape_records(sid, shape):
    """Marker records for a shape; the first two task markers are the
    production GUARDRAIL + CHAT pair, the rest are CHAT. Job ids are
    `eqjob<n>`; every marker carries a distinct, ascending ts."""
    records, task_n, job_n = [], 0, 0
    ts0 = 1715515000.0
    for index, char in enumerate(shape):
        ts = ts0 + 10 * index
        if char == 'T':
            guardrail = task_n == 0 and shape.count('T') > 1
            records.append({
                'muid': f'muid{index:03d}', 'ts': ts, 'sid': sid,
                'task_type': 'code_review',
                'operation_type': 'GUARDRAIL' if guardrail else 'CHAT',
                'trace_id': sid})
            task_n += 1
        else:
            job_n += 1
            records.append({
                'kind': 'job', 'ts': ts, 'sid': sid,
                'agentic_job_id': f'eqjob{job_n}', 'job_name': 'Eq job',
                'job_type': 'eq_type', 'status': 'SUCCESS'})
    return records


def _write_jsonl(path, records):
    with open(path, 'w', encoding='utf-8') as handle:
        for rec in records:
            handle.write(json.dumps(rec, separators=(',', ':')) + '\n')


def _event_record(sid, arid, ts, ended_at):
    return {
        'v': 1, 'sid': sid, 'api_request_id': arid, 'ts': ts,
        'ended_at': ended_at, 'duration_ms': 500, 'platform': 'cli',
        'model': 'claude-sonnet-4-6', 'response_model': 'claude-sonnet-4-6',
        'provider': 'anthropic', 'base_url': 'https://api.anthropic.com',
        'api_mode': 'anthropic_messages', 'finish_reason': 'stop',
        'input_tokens': 100, 'output_tokens': 50, 'cache_read_tokens': 0,
        'cache_write_tokens': 0, 'reasoning_tokens': 0, 'total_tokens': 150}


def _seed_event_sessions_db(db_path, sid):
    """sessions with parent_session_id and profile_name, a confirmed root
    (copied by value from tests/test_event_path_owning_job_id.py)."""
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            'CREATE TABLE sessions (id TEXT PRIMARY KEY, model TEXT, '
            'source TEXT, input_tokens INTEGER, output_tokens INTEGER, '
            'cache_read_tokens INTEGER, cache_write_tokens INTEGER, '
            'reasoning_tokens INTEGER, estimated_cost_usd REAL, '
            'api_call_count INTEGER, started_at REAL, ended_at REAL, '
            'billing_provider TEXT, parent_session_id TEXT, '
            'profile_name TEXT)')
        conn.execute(
            'INSERT INTO sessions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
            (sid, 'claude-sonnet-4-6', 'test', 100, 50, 0, 0, 0, 0.0, 1,
             1715514000.0, 1715514000.0, 'anthropic', None, None))
        conn.commit()
    finally:
        conn.close()


def _completions(meter_log):
    out = []
    if os.path.exists(meter_log):
        with open(meter_log) as handle:
            for line in handle:
                line = line.rstrip('\n')
                if line:
                    argv = shlex.split(line)
                    if argv[:2] == ['meter', 'completion']:
                        out.append(argv_to_flags(argv))
    return out


def run_legacy_reporter(shape, sid):
    """Drive hermes-report.sh on one confirmed-root session holding `shape`.
    Returns {muid: --agentic-job-id or None} for every shipped completion."""
    tmpdir = tempfile.mkdtemp(prefix='gsd-p68-legacy-')
    try:
        hermes_home = os.path.join(tmpdir, 'hh')
        state_dir = os.path.join(hermes_home, 'state', 'revenium')
        markers_dir = os.path.join(state_dir, 'markers')
        os.makedirs(markers_dir, mode=0o700)
        shim_home = os.path.join(tmpdir, 'home')
        bin_dir = os.path.join(shim_home, '.local', 'bin')
        os.makedirs(bin_dir)
        state_db = os.path.join(hermes_home, 'state.db')
        build_state_db(state_db, [{
            'id': sid, 'model': 'claude-sonnet-4-6', 'source': 'test',
            'input_tokens': 1000, 'output_tokens': 500, 'cache_read': 0,
            'cache_write': 0, 'reasoning': 0, 'estimated_cost': '0',
            'api_calls': 1, 'started_at': 1715514000.0,
            'ended_at': 1715514000.0, 'billing_provider': 'anthropic'}])
        seed_parent_session_ids(state_db, {sid: None})
        _write_jsonl(os.path.join(markers_dir, f'{sid}.jsonl'),
                     _shape_records(sid, shape))
        build_shim(os.path.join(bin_dir, 'revenium'))
        meter_log = os.path.join(tmpdir, 'meter.log')
        inv_log = os.path.join(tmpdir, 'inv.log')
        env = {**os.environ, 'HOME': shim_home, 'HERMES_HOME': hermes_home,
               'REVENIUM_STATE_DIR': state_dir,
               'PATH': bin_dir + os.pathsep + os.environ.get('PATH', ''),
               'INVOCATIONS_LOG': inv_log, 'METER_LOG': meter_log,
               'JOBS_LOG': os.path.join(tmpdir, 'jobs.log'), 'TZ': 'UTC',
               'REVENIUM_ORGANIZATION_NAME': ''}
        rc, _inv, out = run_script(SCRIPTS_DIR / 'hermes-report.sh', env,
                                   inv_log)
        if rc != 0:
            raise AssertionError(f'hermes-report.sh rc={rc}: {out}')
        prefix = f'{sid}-1500-'
        shipped = {}
        for flags in _completions(meter_log):
            txn = flags['--transaction-id']
            if not txn.startswith(prefix):
                raise AssertionError(f'unexpected transaction id {txn}')
            shipped[txn[len(prefix):]] = flags.get('--agentic-job-id')
        return shipped
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def run_event_reporter(shape, sid):
    """Drive api-event-report.sh with one event timed onto each CHAT marker.
    Returns {muid: --agentic-job-id or None} for CHAT markers."""
    tmpdir = tempfile.mkdtemp(prefix='gsd-p68-event-')
    try:
        hermes_home = os.path.join(tmpdir, 'hh')
        state_dir = os.path.join(hermes_home, 'state', 'revenium')
        spool_dir = os.path.join(state_dir, 'api-events')
        markers_dir = os.path.join(state_dir, 'markers')
        ready_dir = os.path.join(markers_dir, '.ready')
        for d in (spool_dir, markers_dir, ready_dir):
            os.makedirs(d, mode=0o700)
        shim_home = os.path.join(tmpdir, 'home')
        bin_dir = os.path.join(shim_home, '.local', 'bin')
        os.makedirs(bin_dir)
        build_shim(os.path.join(bin_dir, 'revenium'))
        records = _shape_records(sid, shape)
        _write_jsonl(os.path.join(markers_dir, f'{sid}.jsonl'), records)
        Path(ready_dir, sid).touch()
        _seed_event_sessions_db(os.path.join(hermes_home, 'state.db'), sid)
        events, by_arid = [], {}
        for index, rec in enumerate(records):
            if rec.get('kind') == 'job' or rec['operation_type'] != 'CHAT':
                continue
            arid = f'{sid}:t{index}:api:{index}'
            by_arid[f'event:{arid}'] = rec['muid']
            events.append(_event_record(sid, arid, rec['ts'] + 0.5,
                                        rec['ts'] + 1.0))
        _write_jsonl(os.path.join(spool_dir, f'{sid}.jsonl'), events)
        with open(os.path.join(state_dir, 'revenium-jobs.ledger'), 'w') as fh:
            for rec in records:
                if rec.get('kind') == 'job':
                    fh.write(f"JOB:{rec['agentic_job_id']}:created:"
                             "1715515200.0\n")
        meter_log = os.path.join(tmpdir, 'meter.log')
        inv_log = os.path.join(tmpdir, 'inv.log')
        env = {**os.environ, 'HOME': shim_home, 'HERMES_HOME': hermes_home,
               'REVENIUM_STATE_DIR': state_dir,
               'PATH': os.environ.get('PATH', ''),
               'INVOCATIONS_LOG': inv_log, 'METER_LOG': meter_log,
               'TZ': 'UTC', 'REVENIUM_EVENT_METERING_MODE': 'live'}
        rc, _inv, out = run_script(SCRIPTS_DIR / 'api-event-report.sh', env,
                                   inv_log)
        if rc != 0:
            raise AssertionError(f'api-event-report.sh rc={rc}: {out}')
        shipped = {}
        for flags in _completions(meter_log):
            shipped[by_arid[flags['--transaction-id']]] = flags.get(
                '--agentic-job-id')
        return shipped
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


class ResolverEquivalenceTests(unittest.TestCase):
    """`resolve_owner` returns, for every task marker, the `--agentic-job-id`
    the legacy reporter ships and, for every CHAT marker, the one the event
    reporter ships. Driven end to end on a confirmed-root session, so it
    holds before and after plan 02's positive-root gate lands."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix='gsd-p68-eq-')
        cls.legacy, cls.event, cls.replay = {}, {}, {}
        for shape in SHAPES:
            sid = f'eq-{shape.lower()}-sid'
            path = Path(cls.tmp) / f'{sid}.jsonl'
            _write_jsonl(path, _shape_records(sid, shape))
            cls.replay[shape] = H.replay_marker_file(path)
            cls.legacy[shape] = run_legacy_reporter(shape, sid)
            cls.event[shape] = run_event_reporter(shape, sid)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _expected(self, shape, chat_only=False):
        return {t['muid']: t['owner'] for t in self.replay[shape]['tasks']
                if not chat_only or t['operation_type'] == 'CHAT'}

    def test_legacy_reporter_ships_the_owner_the_replay_computes(self):
        for shape in SHAPES:
            with self.subTest(shape=shape):
                expected = self._expected(shape)
                self.assertEqual(set(self.legacy[shape]), set(expected))
                self.assertEqual(self.legacy[shape], expected)

    def test_event_reporter_ships_the_owner_the_replay_computes(self):
        for shape in SHAPES:
            with self.subTest(shape=shape):
                expected = self._expected(shape, chat_only=True)
                self.assertTrue(expected)
                self.assertEqual(self.event[shape], expected)

    def test_the_two_reporters_agree_with_each_other_on_every_shape(self):
        for shape in SHAPES:
            with self.subTest(shape=shape):
                for muid, owner in self.event[shape].items():
                    self.assertEqual(self.legacy[shape][muid], owner)

    def _rules(self, shape):
        return [(t['rule'], t['owner']) for t in self.replay[shape]['tasks']]

    def test_ttjj_binds_both_task_markers_forward_to_the_first_job(self):
        self.assertEqual(self._rules('TTJJ'),
                         [('forward', 'eqjob1'), ('forward', 'eqjob1')])

    def test_ttjjtttt_binds_the_four_trailing_markers_by_fallback_to_job_two(
            self):
        rules = self._rules('TTJJTTTT')
        self.assertEqual(rules[:2], [('forward', 'eqjob1')] * 2)
        self.assertEqual(rules[2:], [('fallback', 'eqjob2')] * 4)

    def test_jtt_is_bound_by_fallback_and_tt_has_no_owner(self):
        self.assertEqual(self._rules('JTT'), [('fallback', 'eqjob1')] * 2)
        self.assertEqual(self._rules('TT'), [('none', None)] * 2)
        self.assertEqual(self._rules('TJ'), [('forward', 'eqjob1')])
        self.assertEqual(self._rules('TTJ'), [('forward', 'eqjob1')] * 2)

    def test_resolve_owner_is_a_pure_position_function(self):
        jobs = [(5, 'a'), (9, 'b')]
        self.assertEqual(H.resolve_owner(1, jobs), ('a', 'forward'))
        self.assertEqual(H.resolve_owner(6, jobs), ('b', 'forward'))
        self.assertEqual(H.resolve_owner(12, jobs), ('b', 'fallback'))
        self.assertEqual(H.resolve_owner(3, []), (None, 'none'))

    def test_the_loader_matches_the_reporters_on_odd_lines(self):
        path = Path(self.tmp) / 'odd.jsonl'
        lines = [
            '',                                       # blank: no position
            'not json',                               # torn: skipped
            '[1, 2]',                                 # non-dict: skipped
            json.dumps({'kind': 'future', 'x': 1}),   # unknown kind: counted
            json.dumps({'muid': 'm1', 'ts': 1, 'sid': 's',
                        'task_type': 'code_review',
                        'operation_type': 'CHAT'}),
            json.dumps({'kind': 'job', 'agentic_job_id': 'a b:c',
                        'job_type': 't', 'status': 'S'}),
            json.dumps({'kind': 'job', 'agentic_job_id': 'nokeys'}),
            json.dumps({'muid': 'm2', 'ts': 1, 'sid': 's',
                        'task_type': 'ack', 'operation_type': 'CHAT'}),
            'x' * 5000,                               # over 4 KB: skipped
        ]
        path.write_text('\n'.join(lines) + '\n')
        replay = H.replay_marker_file(path)
        self.assertEqual(replay['shape'], 'TJ')
        self.assertEqual(replay['jobs'][0]['id'], 'a_b_c')
        self.assertEqual(replay['jobs'][0]['pos'], 3)
        self.assertEqual(replay['tasks'][0]['owner'], 'a_b_c')

    def test_a_rejudge_marker_is_not_a_second_job_or_boundary(self):
        def job(job_id):
            return {'kind': 'job', 'agentic_job_id': job_id,
                    'job_type': 't', 'status': 'S'}

        def task(muid):
            return {'muid': muid, 'ts': 1, 'sid': 's',
                    'task_type': 'code_review', 'operation_type': 'CHAT'}

        path = Path(self.tmp) / 'rejudge.jsonl'
        _write_jsonl(path, [job('A'), job('B'), task('m1'), job('A')])
        replay = H.replay_marker_file(path)
        self.assertEqual(replay['shape'], 'JJTJ')
        self.assertEqual(replay['job_count'], 2)
        self.assertEqual([j['pos'] for j in replay['jobs']], [1, 2])
        self.assertEqual(replay['tasks'][0]['owner'], 'B')


class ShapeCensusTests(_Scratch):
    def test_shapes_and_jobs_per_file_are_counted(self):
        lay = Layout(self.tmp)
        for sid, shape in (('s1', 'TTJ'), ('s2', 'TTJJ'), ('s3', 'TT'),
                           ('s4', 'JTT')):
            lay.marker_file(sid, shape)
            lay.session(sid)
        agg, _priv = lay.census()
        self.assertEqual(agg['shapes'],
                         {'JTT': 1, 'TT': 1, 'TTJ': 1, 'TTJJ': 1})
        self.assertEqual({int(k): v for k, v in agg['jobs_per_file'].items()},
                         {0: 1, 1: 2, 2: 1})

    def test_resolver_rules_bind_dollars_by_rule(self):
        lay = Layout(self.tmp)
        muids, jobs = lay.marker_file('s1', 'TTJJTTTT')
        lay.session('s1')
        for muid in muids:
            lay.row('s1', 1.0, job=jobs[0], muid=muid)
        lay.row('s1', 5.0)  # a markerless-shaped row on the same session
        agg, _p = lay.census()
        rules = agg['resolver_rules']
        self.assertEqual((rules['forward']['markers'],
                          Decimal(rules['forward']['cost'])), (2, Decimal(2)))
        self.assertEqual((rules['fallback']['markers'],
                          Decimal(rules['fallback']['cost'])), (4, Decimal(4)))
        self.assertEqual(rules['none']['markers'], 0)
        self.assertEqual((rules['no_marker']['rows'],
                          Decimal(rules['no_marker']['cost'])),
                         (1, Decimal(5)))

    def test_multi_single_and_zero_job_populations_carry_dollars(self):
        lay = Layout(self.tmp)
        lay.marker_file('m1', 'TTJJ')
        lay.session('m1', cost=2.0)
        lay.row('m1', 3.0, job='jm')
        lay.marker_file('o1', 'TTJ')
        lay.session('o1', cost=1.0)
        lay.row('o1', 4.0, job='jo')
        lay.marker_file('z1', 'TT')
        lay.session('z1', cost=0.5)
        lay.session('nomark', cost=0.25)
        lay.row('nomark', 1.0)
        agg, _p = lay.census()
        self.assertEqual(agg['multi_job']['sessions'], 1)
        self.assertEqual(Decimal(agg['multi_job']['cost']), Decimal(3))
        self.assertEqual(Decimal(agg['multi_job']['local_cost']), Decimal(2))
        self.assertEqual(agg['single_job']['sessions'], 1)
        self.assertFalse(agg['single_job']['testable_by_judge'])
        self.assertEqual(agg['zero_job']['marker_files']['sessions'], 1)
        self.assertEqual(agg['zero_job']['markerless_sessions']['sessions'], 1)
        self.assertEqual(
            Decimal(agg['zero_job']['markerless_sessions']['cost']), Decimal(1))

    def test_unjoined_rows_are_counted_with_their_dollars(self):
        lay = Layout(self.tmp)
        lay.marker_file('s1', 'TTJ')
        lay.session('s1')
        lay.row('s1', 1.0, job='j')
        lay.row('ghost', 2.5, job='j')
        lay.row('s1', 9.0, txn='no-such-id')
        agg, _p = lay.census()
        self.assertEqual(agg['unjoined']['rows'], 2)
        self.assertEqual(Decimal(agg['unjoined']['cost']), Decimal('11.5'))

    def test_the_longest_known_sid_wins_the_transaction_id_join(self):
        known = {'abc', 'abc-def'}
        rows = [{'transactionId': 'abc-def-100-m1'},
                {'transactionId': 'abc-100'},
                {'transactionId': 'event:abc-def:t1:api:1'},
                {'transactionId': 'abc-def-xyz-m1'}]
        joined, unjoined = H.join_rows(rows, known)
        self.assertEqual([(s, m) for _r, s, m in joined],
                         [('abc-def', 'm1'), ('abc', None), ('abc-def', None)])
        self.assertEqual(len(unjoined), 1)

    def test_local_cost_totals_sessions_inside_the_window_only(self):
        lay = Layout(self.tmp)
        lay.session('in1', cost=1.25)
        lay.session('in2', cost=0.75)
        lay.session('old', cost=100.0, started=OUT_WIN)
        agg, _p = lay.census()
        self.assertEqual(agg['local_cost']['sessions'], 2)
        self.assertEqual(Decimal(agg['local_cost']['cost']), Decimal(2))

    def test_the_aggregate_carries_every_key_and_no_identifier(self):
        lay = Layout(self.tmp)
        muids, jobs = lay.marker_file('zq7leaksid', 'TTJJ',
                                      jobs=['zq7leakjob_ab12', 'zq7leakjob2'])
        lay.session('zq7leaksid')
        lay.row('zq7leaksid', 1.0, job=jobs[0], muid=muids[0])
        lay.jobs = [f'JOB:{jobs[0]}:created:{IN_WIN}']
        agg, priv = lay.census()
        # plan 04 added the judge-half keys to the whitelist; the census
        # alone fills exactly the plan-03 keys.
        self.assertEqual(set(agg), H.AGGREGATE_KEYS - H.JUDGE_AGGREGATE_KEYS)
        text = json.dumps(agg, default=str).lower()
        for needle in ('zq7leaksid', 'zq7leakjob', muids[0].lower()):
            self.assertNotIn(needle, text)
        labels = priv['multi_job_labels']
        self.assertEqual(set(labels), {'S1'})
        self.assertEqual(set(labels['S1']['jobs']), {'J1', 'J2'})
        self.assertEqual(labels['S1']['sid'], 'zq7leaksid')


# -- D-07 --------------------------------------------------------------------
def _created(job_id, ts=IN_WIN + 1000):
    return f'JOB:{job_id}:created:{ts}'


class ZeroCostCensusTests(_Scratch):
    def _cause_layout(self, lay):
        """One zero-cost job per cause, plus a costed sibling and a job
        created outside the window."""
        # (d) genuinely no spend: a zero-token session.
        lay.marker_file('sd', 'TTJ', jobs=['jd'])
        lay.session('sd', tokens=0, cost=0.0)
        # (c) created, session never metered, real spend locally.
        lay.marker_file('sc', 'TTJ', jobs=['jc'])
        lay.session('sc', tokens=1500)
        # (b) event path withheld: the event shipped before the job existed.
        lay.marker_file('sb', 'TTJ', jobs=['jb'])
        lay.session('sb', tokens=1500)
        lay.events = [f'API:sb:t1:api:1|sb|{IN_WIN + 10}']
        # (a) sibling absorbed: TTJJ binds both tasks to the first job.
        lay.marker_file('sa', 'TTJJ', jobs=['ja1', 'ja2'])
        lay.session('sa', tokens=1500)
        lay.hermes.append(f'HERMES:sa:1500:{IN_WIN}:sa-m0')
        lay.row('sa', 2.0, job='ja1', muid='sa-m0')
        # unexplained: metered, bound, spent, yet zero cost.
        lay.marker_file('su', 'TTJ', jobs=['ju'])
        lay.session('su', tokens=1500)
        lay.hermes.append(f'HERMES:su:1500:{IN_WIN}:su-m0')
        # outside the window: never counted.
        lay.marker_file('so', 'TTJ', jobs=['jold'])
        lay.session('so', tokens=1500, started=OUT_WIN)
        lay.jobs = [_created(j) for j in ('jd', 'jc', 'jb', 'ja1', 'ja2', 'ju')]
        lay.jobs.append(_created('jold', OUT_WIN + 1000))

    def test_one_job_per_cause_yields_one_count_in_each_bucket(self):
        lay = Layout(self.tmp)
        self._cause_layout(lay)
        agg, _p = lay.census()
        zc = agg['zero_cost_jobs']
        self.assertEqual(zc['by_cause'], {
            'd_no_spend': 1, 'c_never_metered': 1,
            'b_event_path_withheld': 1, 'a_sibling_absorbed': 1,
            'unexplained': 1})
        self.assertEqual(zc['created_in_window'], 6)
        self.assertEqual(zc['zero_cost'], 5)  # ja1 carries dollars
        self.assertEqual(zc['multi_cause'], 0)
        self.assertEqual(zc['unexplained_no_marker_file'], 0)
        self.assertEqual(zc['event_ledger_lines'], 1)

    def test_a_job_with_no_marker_file_is_unexplained_and_counted_apart(self):
        lay = Layout(self.tmp)
        lay.jobs = [_created('jn')]
        agg, _p = lay.census()
        zc = agg['zero_cost_jobs']
        self.assertEqual(zc['by_cause']['unexplained'], 1)
        self.assertEqual(zc['unexplained_no_marker_file'], 1)
        self.assertEqual(sum(zc['by_cause'].values()), 1)

    def test_a_job_matching_two_causes_is_counted_once_by_precedence(self):
        lay = Layout(self.tmp)
        lay.marker_file('sdc', 'TTJJ', jobs=['jdc1', 'jdc2'])
        lay.session('sdc', tokens=1500)
        lay.jobs = [_created('jdc1'), _created('jdc2')]
        agg, _p = lay.census()
        zc = agg['zero_cost_jobs']
        # jdc1 is (c) only; jdc2 is (c) and (a), counted under (c).
        self.assertEqual(zc['by_cause']['c_never_metered'], 2)
        self.assertEqual(zc['by_cause']['a_sibling_absorbed'], 0)
        self.assertEqual(zc['multi_cause'], 1)
        self.assertEqual(sum(zc['by_cause'].values()), zc['zero_cost'])

    def test_with_no_event_ledger_cause_b_is_zero_by_construction(self):
        lay = Layout(self.tmp)
        lay.marker_file('sb', 'TTJ', jobs=['jb'])
        lay.session('sb', tokens=1500)
        lay.jobs = [_created('jb')]
        agg, _p = lay.census()
        zc = agg['zero_cost_jobs']
        self.assertEqual(zc['event_ledger_lines'], 0)
        self.assertEqual(zc['by_cause']['b_event_path_withheld'], 0)

    def test_a_job_with_sliced_cost_above_zero_is_not_counted(self):
        lay = Layout(self.tmp)
        lay.marker_file('s1', 'TTJ', jobs=['j1'])
        lay.session('s1')
        lay.row('s1', 1.5, job='j1', muid='s1-m0')
        lay.row('s1', 99.0, job='j1', muid='s1-m1', agent='Hermes-ent')
        lay.jobs = [_created('j1')]
        agg, _p = lay.census()
        self.assertEqual(agg['zero_cost_jobs']['zero_cost'], 0)

    def test_a_job_only_another_agent_paid_for_is_zero_cost_here(self):
        lay = Layout(self.tmp)
        lay.marker_file('s1', 'TTJ', jobs=['j1'])
        lay.session('s1')
        lay.row('s1', 50.0, job='j1', muid='s1-m0', agent='Hermes-ent')
        lay.jobs = [_created('j1')]
        agg, _p = lay.census()
        self.assertEqual(agg['zero_cost_jobs']['zero_cost'], 1)


# -- D-18 --------------------------------------------------------------------
class AmbiguousRootCensusTests(_Scratch):
    def test_cycles_no_row_sessions_and_the_dollars_legacy_shipped(self):
        lay = Layout(self.tmp)
        lay.session('R')                      # confirmed root
        lay.session('C', parent='R')          # an ordinary child
        lay.session('S', parent='S')          # self-loop
        lay.session('A', parent='B')          # A-B-A cycle
        lay.session('B', parent='A')
        lay.marker_file('X', 'TTJ')           # marker session with no row
        costs = {'R': 4.0, 'C': 0.5, 'S': 1.0, 'A': 2.0, 'B': 0.25}
        for sid, cost in costs.items():
            lay.row(sid, cost, job='j' + sid)
        lay.row('R', 3.0)                     # not owner-attributed
        agg, _p = lay.census()
        amb = agg['ambiguous_root']
        self.assertTrue(amb['has_parent_column'])
        self.assertEqual((amb['root'], amb['child']), (1, 4))
        self.assertEqual(amb['cycles'], 2)
        self.assertEqual(amb['cyclic_sessions'], 3)
        self.assertEqual(amb['no_row_marker_sessions'], 1)
        self.assertEqual(amb['ambiguous_sessions'], 4)
        self.assertEqual(amb['owner_attributed_rows'], 3)
        self.assertEqual(Decimal(amb['owner_attributed_cost']),
                         Decimal('3.25'))

    def test_a_table_without_the_parent_column_makes_every_session_ambiguous(
            self):
        lay = Layout(self.tmp, with_parent=False)
        lay.session('s1')
        lay.session('s2')
        lay.marker_file('s3', 'TTJ')
        lay.row('s1', 1.0, job='j1')
        lay.row('s2', 2.0, job='j2')
        lay.row('s2', 4.0)
        agg, _p = lay.census()
        amb = agg['ambiguous_root']
        self.assertFalse(amb['has_parent_column'])
        self.assertEqual(amb['ambiguous_sessions'], 3)
        self.assertIsNone(amb['root'])
        self.assertEqual(Decimal(amb['owner_attributed_cost']), Decimal(3))

    def test_the_walk_is_the_production_sidecars_own(self):
        sidecar = H.load_sidecar()
        self.assertTrue(hasattr(sidecar, '_walk_parent_map'))
        self.assertEqual(H.SIDECAR.name, 'get-root-session-id.py')
        self.assertEqual(
            sidecar._walk_parent_map('A', {'A': 'B', 'B': 'A'}), 'A')

    def test_a_clean_host_reports_nothing_ambiguous(self):
        lay = Layout(self.tmp)
        lay.session('R1')
        lay.session('R2')
        lay.session('K', parent='R1')
        lay.marker_file('R1', 'TTJ')
        lay.row('R1', 1.0, job='j')
        agg, _p = lay.census()
        amb = agg['ambiguous_root']
        self.assertEqual((amb['cycles'], amb['ambiguous_sessions'],
                          amb['no_row_marker_sessions']), (0, 0, 0))
        self.assertEqual(Decimal(amb['owner_attributed_cost']), Decimal(0))


class CounterfactualTests(_Scratch):
    def test_before_after_d17_and_after_m1_are_exact_fractions(self):
        lay = Layout(self.tmp)
        lay.session('R1')                     # confirmed root, one job
        lay.marker_file('R1', 'TTJ')
        lay.row('R1', 4.0, job='j1')
        lay.row('R1', 3.0)                    # unattributed
        lay.session('M')                      # confirmed root, two jobs
        lay.marker_file('M', 'TTJJ')
        lay.row('M', 2.0, job='jm')
        lay.session('S', parent='S')          # ambiguous self-loop
        lay.row('S', 1.0, job='js')
        agg, _p = lay.census()
        cf = agg['counterfactual']
        self.assertEqual(cf['before']['fraction'], '7/10')
        self.assertEqual(cf['before']['display_pct'], '70.00%')
        self.assertEqual(cf['after_d17']['fraction'], '3/5')
        self.assertEqual(cf['after_d17']['display_pct'], '60.00%')
        self.assertEqual(cf['after_m1']['fraction'], '2/5')
        self.assertEqual(cf['after_m1']['display_pct'], '40.00%')
        self.assertEqual(Decimal(cf['before']['delta_cost_from_before']), 0)
        self.assertEqual(Decimal(cf['after_d17']['delta_cost_from_before']),
                         Decimal(1))
        self.assertEqual(Decimal(cf['after_m1']['delta_cost_from_before']),
                         Decimal(3))
        self.assertEqual(Decimal(cf['after_m1']['cost_attributed']),
                         Decimal(4))

    def test_a_session_both_ambiguous_and_multi_job_is_removed_once(self):
        lay = Layout(self.tmp)
        lay.session('Q', parent='Q')
        lay.marker_file('Q', 'TTJJ')
        lay.row('Q', 2.0, job='jq')
        lay.row('Q', 2.0)
        agg, _p = lay.census()
        cf = agg['counterfactual']
        self.assertEqual(cf['after_d17']['fraction'], '0/1')
        self.assertEqual(cf['after_m1']['fraction'], '0/1')
        self.assertEqual(Decimal(cf['after_m1']['delta_cost_from_before']),
                         Decimal(2))


if __name__ == '__main__':
    unittest.main()
