"""Opt-in boundary shared by direct/catalog and explicitly bootstrapped installs.

No credentials or network here. Existing full installs retain their prior consent
through explicit pluginConsent or configured guardrail ruleIds in their owning
profile. Explicit plugin settings (including False) override that fallback.
"""

from functools import wraps
import json
import logging
from pathlib import Path


logger = logging.getLogger("revenium_classifier")
SEEDS = ("task-taxonomy.json", "job-taxonomy.json", "role-taxonomy.json")
_UNSET = object()


def _enabled(ctx, setting, paths):
    value = ctx.get_config(setting, _UNSET)
    if value is not _UNSET:
        return value is True
    # This is the integration's NON-SECRET config, not a credential store.
    # A fresh plugin-only install has no ruleIds and therefore stays inert.
    try:
        config = json.loads(paths.config_file.read_text(encoding="utf-8"))
        consent = config.get("pluginConsent", {})
        if isinstance(consent, dict) and consent.get(setting) is True:
            return True
        rules = config.get("ruleIds")
        return isinstance(rules, list) and bool(rules) and all(
            isinstance(rule, str) and bool(rule.strip()) for rule in rules
        )
    except (OSError, ValueError, AttributeError):
        return False


def _seed_taxonomies(paths):
    destinations = (paths.taxonomy_file, paths.job_taxonomy_file,
                    getattr(paths, "role_taxonomy_file", None) or paths.state_dir / "role-taxonomy.json")
    for name, destination in zip(SEEDS, destinations):
        # Exclusive create preserves learned labels and never replaces operator data.
        source = Path(__file__).parent / name
        data = source.read_text(encoding="utf-8")
        json.loads(data)
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            with destination.open("x", encoding="utf-8") as stream:
                stream.write(data)
        except FileExistsError:
            pass


def consented(ctx, callback, setting, resolve_paths):
    """Register hooks unconditionally (truthful manifest), gate work per event."""
    @wraps(callback)
    def handle(*args, **kwargs):
        try:
            # False/malformed settings must return before ANY state/session read.
            value = ctx.get_config(setting, _UNSET)
            if value is not _UNSET and value is not True:
                return
            sid = kwargs.get("session_id")
            if not isinstance(sid, str) or not sid:
                return
            paths = resolve_paths(sid)
            if not _enabled(ctx, setting, paths):
                return
            if setting == "classification_enabled":
                _seed_taxonomies(paths)
            return callback(*args, **kwargs)
        except Exception:
            # Fail closed on consent/config failure; never include user content.
            logger.warning("revenium-classifier consented hook unavailable")
    return handle
