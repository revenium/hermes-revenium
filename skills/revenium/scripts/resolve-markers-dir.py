#!/usr/bin/env python3
"""Resolve a per-session state subdirectory (markers, api-events, ...) that
OWNS a given session identifier.

TRACE-03 (Phase 28) cron-side mirror, generalized in Phase 32 (EVT-03) to
cover a second subdirectory rather than growing a sibling sidecar file.
Deliberately reimplements `classifier._paths_for_session`'s per-session
resolution (skills/revenium/plugins/revenium-classifier/classifier.py:90-125)
rather than importing it, because the plugin module is only importable
inside Hermes' own virtual environment — which the cron process is not
running in. This repeats the exact shape already established and documented
by skills/revenium/scripts/get-root-session-id.py for the identical reason.

`hermes-report.sh` resolves a single un-namespaced markers directory from
`common.sh` for its whole process lifetime, with zero per-session branching.
In `gateway.multiplex_profiles` mode a SINGLE default gateway process serves
EVERY profile; sessions are namespaced `agent:<profile>:…` and each profile
keeps its own state under ~/.hermes/profiles/<profile>/. Without per-session
resolution, a namespaced profile's state (markers OR, as of Phase 32, the
api-events spool) is invisible to the cron reading the process-level
directory. This sidecar closes that read-side gap for both.

Production callers shell in via the bash wrappers in scripts/common.sh:

  markers_dir="$(resolve_markers_dir "${sid}")"
  spool_dir="$(resolve_spool_dir "${sid}")"

Nothing here is shared code with classifier.py or api_event_spool.py — a
parity test is the only mechanism keeping the (now three) implementations
honest.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import Optional

# `agent:<profile>:<rest>` namespace (multiplex). Capture the profile segment.
# Mirrors classifier.py's _NS_RE exactly.
_NS_RE = re.compile(r"^agent:([^:]+):")

# Phase 32 (EVT-03): map a subdirectory name to the process-level environment
# override common.sh declares for it, so both directories derive their
# defaults through the same precedence classifier.py / api_event_spool.py use
# on the plugin side. "markers" mirrors MARKERS_DIR's REVENIUM_MARKERS_DIR
# override; "api-events" mirrors EVENT_SPOOL_DIR's REVENIUM_EVENT_SPOOL_DIR
# override (common.sh's C-1 declarations).
_SUBDIR_ENV_OVERRIDE = {
    "markers": "REVENIUM_MARKERS_DIR",
    "api-events": "REVENIUM_EVENT_SPOOL_DIR",
}


def _module_state_subdir(subdir: str) -> Path:
    """The process-level <subdir> directory, resolved from the environment
    using the same variable names and precedence as common.sh's module-level
    path constants, so both sides derive identical defaults under identical
    environments."""
    hermes_home = Path(os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes")))
    state_dir = Path(os.environ.get("REVENIUM_STATE_DIR", str(hermes_home / "state" / "revenium")))
    override_env = _SUBDIR_ENV_OVERRIDE.get(subdir)
    if override_env:
        return Path(os.environ.get(override_env, str(state_dir / subdir)))
    return state_dir / subdir


def resolve_state_subdir(
    session_id: str,
    subdir: str = "markers",
    override: Optional[str] = None,
) -> str:
    """Resolve the <subdir> directory (e.g. "markers" or "api-events") that
    OWNS this session.

    Mirrors classifier._paths_for_session's directory resolution step for
    step: match the identifier against the `agent:<profile>:` namespace
    pattern anchored at the start; if there is no match, return the
    process-level <subdir> directory; if the captured profile segment is
    empty or names the default profile, return the process-level <subdir>
    directory; otherwise build the profile home under the process home's
    profiles subdirectory and, ONLY IF that path is an existing directory,
    return that profile's <subdir> directory under its own state directory.

    The profile-home directory-existence check is load-bearing security, not
    an optimisation: it is what makes a crafted profile segment harmless — a
    traversal-shaped segment would need an actually-matching directory under
    the profiles path to redirect anything, and path joining does not itself
    collapse parent references. Do not replace it with a string check, do
    not resolve or normalise the path before it, and do not remove it.

    Fail-open: any error, including the base cases above, returns the
    process-level <subdir> directory (never raises).
    """
    module_dir = Path(override) if override else _module_state_subdir(subdir)
    try:
        m = _NS_RE.match(session_id or "")
        if not m:
            return str(module_dir)
        profile = m.group(1)
        if not profile or profile == "default":
            return str(module_dir)
        hermes_home = Path(os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes")))
        profile_home = hermes_home / "profiles" / profile
        if not profile_home.is_dir():
            return str(module_dir)
        return str(profile_home / "state" / "revenium" / subdir)
    except Exception:
        return str(module_dir)


def resolve_markers_dir(
    session_id: str,
    markers_dir_override: Optional[str] = None,
) -> str:
    """Resolve the markers directory that OWNS this session.

    Thin wrapper over resolve_state_subdir("markers", ...) so every existing
    caller and the existing parity test stay byte-compatible with the
    pre-Phase-32 shape of this function.
    """
    return resolve_state_subdir(session_id, "markers", markers_dir_override)


def _main(argv: list) -> int:
    if len(argv) < 2 or not argv[1]:
        return 0
    subdir = argv[2] if len(argv) > 2 and argv[2] else "markers"
    print(resolve_state_subdir(argv[1], subdir))
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv))
