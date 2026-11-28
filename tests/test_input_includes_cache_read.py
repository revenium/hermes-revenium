"""Every `meter completion` send path ships the input count the provider's
own usage object reports.

Hermes stores input with the cache read taken out for every provider except
Anthropic (hermes-agent `normalize_usage`). Revenium takes the cache read out
of the input itself on OpenAI-family models (OpenAI, Azure OpenAI, xAI,
Groq), so those rows must ship input + cache read; Anthropic rows ship the
stored input unchanged, and so do Gemini rows until Revenium settles how bare
Gemini names are priced. Covers the per-marker and markerless main-loop sends,
the auxiliary-usage send and the api-event send.
"""
import json
import os
import shlex
import shutil
import tempfile
import unittest

from tests._compat_helpers import (
    argv_to_flags,
    build_session_model_usage,
    build_shim,
    build_state_db,
    run_script,
    SCRIPTS_DIR,
    seed_parent_session_ids,
)

INPUT = 1000
CACHE_READ = 4000
CACHE_WRITE = 0


def _session(sid, model, provider):
    return {
        'id': sid, 'model': model, 'source': 'test',
        'input_tokens': INPUT, 'output_tokens': 50,
        'cache_read': CACHE_READ, 'cache_write': CACHE_WRITE,
        'reasoning': 0, 'estimated_cost': '0', 'api_calls': 1,
        'started_at': 1715514000.0, 'ended_at': 1715514000.0,
        'billing_provider': provider,
    }


def _write_jsonl(path, records):
    with open(path, 'w', encoding='utf-8') as f:
        for r in records:
            f.write(json.dumps(r, separators=(',', ':')) + '\n')


class _Sandbox:
    def __init__(self):
        self.tmpdir = tempfile.mkdtemp(prefix='input-includes-cache-read-')
        self.hermes_home = os.path.join(self.tmpdir, 'hh')
        self.state_dir = os.path.join(self.hermes_home, 'state', 'revenium')
        self.markers_dir = os.path.join(self.state_dir, 'markers')
        self.spool_dir = os.path.join(self.state_dir, 'api-events')
        self.state_db = os.path.join(self.hermes_home, 'state.db')
        os.makedirs(os.path.join(self.markers_dir, '.ready'), mode=0o700)
        os.makedirs(self.spool_dir, mode=0o700)
        shim_home = os.path.join(self.tmpdir, 'home')
        bin_dir = os.path.join(shim_home, '.local', 'bin')
        os.makedirs(bin_dir)
        build_shim(os.path.join(bin_dir, 'revenium'))
        self.meter_log = os.path.join(self.tmpdir, 'meter.log')
        self.inv_log = os.path.join(self.tmpdir, 'inv.log')
        self.env = {
            **os.environ,
            'HOME': shim_home,
            'HERMES_HOME': self.hermes_home,
            'REVENIUM_STATE_DIR': self.state_dir,
            'PATH': bin_dir + os.pathsep + os.environ.get('PATH', ''),
            'INVOCATIONS_LOG': self.inv_log,
            'METER_LOG': self.meter_log,
            'JOBS_LOG': os.path.join(self.tmpdir, 'jobs.log'),
            'TZ': 'UTC',
            'REVENIUM_ORGANIZATION_NAME': '',
            'REVENIUM_EVENT_METERING_MODE': 'live',
        }

    def run(self, script):
        rc, _inv, output = run_script(SCRIPTS_DIR / script, self.env, self.inv_log)
        sends = []
        if os.path.exists(self.meter_log):
            with open(self.meter_log) as f:
                sends = [argv_to_flags(shlex.split(line)) for line in f if line.strip()]
        return rc, output, sends

    def close(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)


class InputIncludesCacheReadTests(unittest.TestCase):
    def setUp(self):
        self.box = _Sandbox()
        self.addCleanup(self.box.close)

    def _by_model(self, sends):
        return {s.get('--model'): s for s in sends}

    def assert_input(self, send, expected):
        self.assertEqual(send.get('--input-tokens'), str(expected), send)
        self.assertEqual(send.get('--cache-read-tokens'), str(CACHE_READ), send)

    def test_markerless_and_aux_sends(self):
        build_state_db(self.box.state_db, [
            _session('sid-openai', 'gpt-5.1', 'openai'),
            _session('sid-claude', 'claude-sonnet-4-6', 'anthropic'),
            _session('sid-gemini', 'gemini-2.5-pro', 'google'),
        ])
        seed_parent_session_ids(self.box.state_db, {'sid-openai': None, 'sid-claude': None, 'sid-gemini': None})
        build_session_model_usage(self.box.state_db, [{
            'session_id': 'sid-openai', 'model': 'gpt-5-mini', 'billing_provider': 'openai',
            'task': 'approval', 'api_call_count': 1,
            'input_tokens': 300, 'output_tokens': 10,
            'cache_read_tokens': CACHE_READ, 'cache_write_tokens': 0,
            'estimated_cost_usd': 0.001,
            'first_seen': 1715514500.0, 'last_seen': 1715514600.0,
        }])

        rc, output, sends = self.box.run('hermes-report.sh')
        self.assertEqual(rc, 0, output)
        sent = self._by_model(sends)

        self.assert_input(sent['gpt-5.1'], INPUT + CACHE_READ)
        self.assert_input(sent['claude-sonnet-4-6'], INPUT)
        self.assert_input(sent['gemini-2.5-pro'], INPUT)
        self.assert_input(sent['gpt-5-mini'], 300 + CACHE_READ)

    def test_provider_guess_decides_gpt_inside_another_word_with_no_provider(self):
        build_state_db(self.box.state_db, [_session('sid-local', 'llama-3-70b-gptq', '')])
        seed_parent_session_ids(self.box.state_db, {'sid-local': None})

        rc, output, sends = self.box.run('hermes-report.sh')
        self.assertEqual(rc, 0, output)
        send = self._by_model(sends)['llama-3-70b-gptq']

        self.assertEqual(send.get('--provider'), 'openai', send)
        self.assert_input(send, INPUT + CACHE_READ)

    def test_per_marker_send(self):
        build_state_db(self.box.state_db, [_session('sid-openai', 'gpt-5.1', 'openai')])
        seed_parent_session_ids(self.box.state_db, {'sid-openai': None})
        _write_jsonl(os.path.join(self.box.markers_dir, 'sid-openai.jsonl'), [{
            'muid': 'muid-openai', 'ts': 1715515000.5, 'sid': 'sid-openai',
            'task_type': 'code_review', 'operation_type': 'CHAT',
        }])

        rc, output, sends = self.box.run('hermes-report.sh')
        self.assertEqual(rc, 0, output)

        self.assert_input(self._by_model(sends)['gpt-5.1'], INPUT + CACHE_READ)

    def test_api_event_sends(self):
        sid = 'sid-event'
        open(os.path.join(self.box.markers_dir, '.ready', sid), 'w').close()

        def event(arid, model, provider, api_mode, ts):
            return {
                'v': 1, 'sid': sid, 'api_request_id': arid,
                'ts': ts, 'ended_at': ts + 0.5, 'duration_ms': 500,
                'platform': 'cli', 'model': model, 'response_model': model,
                'provider': provider, 'base_url': '', 'api_mode': api_mode,
                'finish_reason': 'stop',
                'input_tokens': INPUT, 'output_tokens': 50,
                'cache_read_tokens': CACHE_READ, 'cache_write_tokens': CACHE_WRITE,
                'reasoning_tokens': 0, 'total_tokens': INPUT + 50 + CACHE_READ,
            }

        _write_jsonl(os.path.join(self.box.spool_dir, f'{sid}.jsonl'), [
            event('arid-openai', 'gpt-5.1', 'openai', 'chat_completions', 1715514000.5),
            event('arid-gemini', 'gemini-2.5-pro', 'gemini', 'chat_completions', 1715514002.5),
            event('arid-claude', 'claude-sonnet-4-6', 'anthropic', 'anthropic_messages', 1715514004.5),
        ])
        _write_jsonl(os.path.join(self.box.markers_dir, f'{sid}.jsonl'), [{
            'muid': 'muid-event', 'ts': 1715513900.5, 'sid': sid,
            'task_type': 'code_review', 'operation_type': 'CHAT',
        }])

        rc, output, sends = self.box.run('api-event-report.sh')
        self.assertEqual(rc, 0, output)
        sent = self._by_model(sends)

        self.assert_input(sent['gpt-5.1'], INPUT + CACHE_READ)
        self.assert_input(sent['gemini-2.5-pro'], INPUT)
        self.assert_input(sent['claude-sonnet-4-6'], INPUT)


if __name__ == '__main__':
    unittest.main()
