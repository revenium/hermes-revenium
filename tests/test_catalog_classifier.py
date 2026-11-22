"""Catalog plugin opt-in, self-containment and compatibility (offline fixtures)."""
import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from tests.test_repository import _setup_plugin_env, _restore_plugin_env
from tests.test_phase29_hook_registration import (
    _load_plugin_module, _classifier_submodule, _seed_substantive_session_jsonl,
)

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "skills/revenium/plugins/revenium-classifier"
SPEC = importlib.util.spec_from_file_location("catalog_consent_test", PLUGIN / "catalog_consent.py")
assert SPEC and SPEC.loader
GATE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GATE)


class Context:
    def __init__(self, **settings):
        self.settings = settings
        self.hooks = {}

    def get_config(self, key, default=None):
        return self.settings.get(key, default)

    def register_hook(self, name, callback):
        self.hooks[name] = callback


class CatalogConsentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="catalog-consent-")
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.paths = SimpleNamespace(config_file=root / "config.json", state_dir=root,
                                     taxonomy_file=root / "task-taxonomy.json",
                                     job_taxonomy_file=root / "job-taxonomy.json")

    def config(self, data):
        self.paths.config_file.write_text(json.dumps(data))

    def invoke(self, ctx, setting="classification_enabled"):
        callback = Mock()
        resolver = Mock(return_value=self.paths)
        hook = GATE.consented(ctx, callback, setting, resolver)
        hook(session_id="fixture-session")
        return callback, resolver

    def test_fresh_default_no_processing_or_state_writes(self):
        callback, _ = self.invoke(Context())
        callback.assert_not_called()
        self.assertEqual(list(self.paths.state_dir.iterdir()), [])

    def test_false_and_malformed_consent_stop_before_state_reads(self):
        self.config({"ruleIds": ["existing-rule"]})
        for value in (False, None, "true", 1, {}, []):
            callback, resolver = self.invoke(Context(classification_enabled=value))
            callback.assert_not_called()
            resolver.assert_not_called()

    def test_true_seeds_and_invokes(self):
        callback, _ = self.invoke(Context(classification_enabled=True))
        callback.assert_called_once_with(session_id="fixture-session")
        for name in GATE.SEEDS:
            self.assertEqual((self.paths.state_dir / name).read_bytes(), (PLUGIN / name).read_bytes())

    def test_seed_never_overwrites_learned_taxonomies(self):
        self.paths.taxonomy_file.write_text('{"labels":{"custom_task":{}}}')
        self.invoke(Context(classification_enabled=True))
        self.assertIn("custom_task", self.paths.taxonomy_file.read_text())

    def test_role_seed_honors_resolved_override(self):
        self.paths.role_taxonomy_file = self.paths.state_dir / "custom" / "roles.json"
        self.invoke(Context(classification_enabled=True))
        self.assertEqual(self.paths.role_taxonomy_file.read_bytes(),
                         (PLUGIN / "role-taxonomy.json").read_bytes())
        self.assertFalse((self.paths.state_dir / "role-taxonomy.json").exists())

    def test_collection_independent_and_does_not_seed(self):
        ctx = Context(collection_enabled=True, classification_enabled=False)
        callback, _ = self.invoke(ctx, "collection_enabled")
        callback.assert_called_once()
        callback, _ = self.invoke(ctx)
        callback.assert_not_called()
        self.assertEqual(list(self.paths.state_dir.iterdir()), [])

    def test_prior_full_install_consent_retained(self):
        for config in ({"ruleIds": ["existing-rule"]},
                       {"pluginConsent": {"classification_enabled": True, "collection_enabled": True}}):
            self.config(config)
            for setting in ("classification_enabled", "collection_enabled"):
                callback, _ = self.invoke(Context(), setting)
                callback.assert_called_once()
                callback, resolver = self.invoke(Context(**{setting: False}), setting)
                callback.assert_not_called()
                resolver.assert_not_called()

    def test_invalid_legacy_config_fails_closed(self):
        for config in ({}, {"ruleIds": []}, {"ruleIds": "rule"}, {"ruleIds": [None]},
                       {"pluginConsent": {"classification_enabled": "true"}}, []):
            self.config(config)
            callback, _ = self.invoke(Context())
            callback.assert_not_called()
        self.paths.config_file.write_text("not json")
        callback, _ = self.invoke(Context())
        callback.assert_not_called()

    def test_config_error_fails_closed(self):
        ctx = Context()
        ctx.get_config = Mock(side_effect=RuntimeError("secret error"))
        with self.assertLogs("revenium_classifier", level="WARNING") as logs:
            callback, _ = self.invoke(ctx)
        callback.assert_not_called()
        self.assertNotIn("secret error", str(logs.output))

    def test_change_to_false_takes_effect_without_reregister(self):
        ctx = Context(collection_enabled=True)
        callback = Mock()
        hook = GATE.consented(ctx, callback, "collection_enabled", lambda sid: self.paths)
        hook(session_id="fixture")
        ctx.settings["collection_enabled"] = False
        hook(session_id="fixture")
        callback.assert_called_once()

    def test_seed_copies_match_canonical_seeds(self):
        for name in GATE.SEEDS:
            self.assertEqual((PLUGIN / name).read_bytes(), (ROOT / "skills/revenium" / name).read_bytes())

    def test_actual_registered_classification_produces_marker_pair(self):
        snap, added, hh, sd, md = _setup_plugin_env(self.tmp.name)
        try:
            mod_name = "catalog_classification_fixture"
            mod = _load_plugin_module(mod_name)
            classifier = _classifier_submodule(mod_name)
            ctx = Context(classification_enabled=True, collection_enabled=False)
            mod.register(ctx)
            self.assertEqual(set(ctx.hooks), {"on_session_end", "on_session_finalize", "post_llm_call", "post_api_request"})
            sid = "catalog-fixture"
            _seed_substantive_session_jsonl(hh, sid)
            with patch.object(classifier, "_classify_via_llm", new=AsyncMock(return_value="code_review")), \
                 patch.object(classifier, "_infer_jobs_via_llm", new=AsyncMock(return_value=[])), \
                 patch.object(classifier, "call_llm", side_effect=AssertionError("No live model calls")):
                ctx.hooks["on_session_finalize"](session_id=sid, platform="cli", reason="shutdown")
            records = [json.loads(line) for line in (Path(md) / f"{sid}.jsonl").read_text().splitlines()]
            self.assertEqual({r["task_type"] for r in records}, {"code_review"})
            self.assertEqual({r["operation_type"] for r in records}, {"GUARDRAIL", "CHAT"})
            self.assertTrue((Path(md) / ".ready" / sid).exists())
        finally:
            _restore_plugin_env(snap, added)

    def test_actual_collection_is_opt_in_and_content_free(self):
        snap, added, hh, sd, md = _setup_plugin_env(self.tmp.name)
        try:
            mod = _load_plugin_module("catalog_collection_fixture")
            ctx = Context(classification_enabled=False, collection_enabled=False)
            mod.register(ctx)
            kwargs = dict(session_id="catalog-api", api_request_id="request-1",
                          started_at=1000.0, ended_at=1001.0, api_duration=1.0,
                          model="fixture-model", provider="fixture-provider",
                          usage={"input_tokens": 10, "output_tokens": 5},
                          response={"content": "private-response"},
                          assistant_message={"content": "private-message"})
            hook = ctx.hooks["post_api_request"]
            with patch.object(mod, "run_classification", side_effect=AssertionError("No classification")), \
                 patch("socket.socket", side_effect=AssertionError("No network")):
                hook(**kwargs)
                self.assertFalse((Path(sd) / "api-events").exists())
                ctx.settings["collection_enabled"] = True
                hook(**kwargs)
            text = (Path(sd) / "api-events/catalog-api.jsonl").read_text()
            record = json.loads(text)
            self.assertEqual(record["input_tokens"], 10)
            self.assertEqual(record["output_tokens"], 5)
            self.assertNotIn("private-response", text)
            self.assertNotIn("private-message", text)
            self.assertFalse((Path(md) / "catalog-api.jsonl").exists())
        finally:
            _restore_plugin_env(snap, added)

    def test_standalone_copy_loads_without_sibling_skill_tree(self):
        import shutil
        import sys
        standalone = Path(self.tmp.name) / "plugin-only"
        shutil.copytree(PLUGIN, standalone, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        name = "catalog_standalone_fixture"
        spec = importlib.util.spec_from_file_location(
            name, standalone / "__init__.py", submodule_search_locations=[str(standalone)])
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        try:
            spec.loader.exec_module(module)
            ctx = Context(classification_enabled=False, collection_enabled=False)
            module.register(ctx)
            with patch.object(module, "run_classification", side_effect=AssertionError("disabled")), \
                 patch.object(module, "spool_api_request", side_effect=AssertionError("disabled")):
                for callback in ctx.hooks.values():
                    callback(session_id="standalone", completed=True, interrupted=False)
            self.assertEqual(len(ctx.hooks), 4)
            self.assertFalse((standalone.parent / "scripts").exists())
        finally:
            for key in list(sys.modules):
                if key == name or key.startswith(name + "."):
                    del sys.modules[key]

    def test_manifest_catalog_contract(self):
        manifest = (PLUGIN / "plugin.yaml").read_text()
        draft = (ROOT / "docs/catalog-entry.draft.yaml").read_text()
        for text in (manifest, draft):
            self.assertIn('requires_hermes: ">=0.23.3"', text)
            self.assertIn("requires_env: []", text)
            for hook in ("on_session_end", "on_session_finalize", "post_llm_call", "post_api_request"):
                self.assertIn("- " + hook, text)
        self.assertIn("subdir: skills/revenium/plugins/revenium-classifier", draft)
        self.assertNotIn("revenium_cost_estimate", draft)


if __name__ == "__main__":
    unittest.main()
