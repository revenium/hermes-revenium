"""Phase 68 plan 03: contract tests for the job-attribution census harness.

`tests/job_attribution_harness.py` is operator-invoked, stdlib only and
read-only against every host. These tests carry one fake host through the real
`pull` subcommand (a stand-in `ssh` that runs each remote command under a
temporary home), then check the census arithmetic, the privacy of every
aggregate, the remote-command allowlist and the redaction audit.

Nothing here touches a real host, a real tenant, or the network.
"""
import contextlib
import io
import json
import os
import re
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
    }

    def test_every_template_is_accepted(self):
        self.assertGreaterEqual(len(H.REMOTE_COMMAND_TEMPLATES), 9)
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
            'tokens': ['zq7jobtypesentinel', 'person'],
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
        rc, _o, _e = self._audit('A PERSON was named.\n',
                                 '--denylist', str(self.denylist))
        self.assertEqual(rc, H.EXIT_AUDIT)
        rc, _o, _e = self._audit('personnel are not a person-name hit?\n',
                                 '--denylist', str(self.denylist))
        # "person-name" splits on the hyphen, so the whole word "person" hits
        self.assertEqual(rc, H.EXIT_AUDIT)
        rc, _o, _e = self._audit('personnel only\n',
                                 '--denylist', str(self.denylist))
        self.assertEqual(rc, H.EXIT_OK)


if __name__ == '__main__':
    unittest.main()
