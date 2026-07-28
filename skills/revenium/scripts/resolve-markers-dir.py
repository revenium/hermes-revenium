#!/usr/bin/env python3
"""Resolve the markers directory that OWNS a given session identifier.

TRACE-03 (Phase 28) cron-side mirror. Deliberately reimplements
`classifier._paths_for_session`'s markers-directory resolution
(skills/revenium/plugins/revenium-classifier/classifier.py:90-125) rather
than importing it, because the plugin module is only importable inside
Hermes' own virtual environment — which the cron process is not running in.
This repeats the exact shape already established and documented by
skills/revenium/scripts/get-root-session-id.py for the identical reason.

`hermes-report.sh` resolves a single un-namespaced markers directory from
`common.sh` for its whole process lifetime, with zero per-session branching.
In `gateway.multiplex_profiles` mode a SINGLE default gateway process serves
EVERY profile; sessions are namespaced `agent:<profile>:…` and each profile
keeps its own state under ~/.hermes/profiles/<profile>/. Without per-session
resolution, a namespaced profile's markers are invisible to the cron reading
the process-level directory. This sidecar closes that read-side gap.

Production callers shell in via the bash wrapper in scripts/common.sh:

  markers_dir="$(resolve_markers_dir "${sid}")"

Nothing here is shared code with classifier.py — Task 2's parity test is the
only mechanism keeping the two implementations honest.
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


def _module_markers_dir() -> Path:
    """The process-level markers directory, resolved from the environment
    using the same variable names and precedence as classifier.py's
    module-level path constants, so both sides derive identical defaults
    under identical environments."""
    hermes_home = Path(os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes")))
    state_dir = Path(os.environ.get("REVENIUM_STATE_DIR", str(hermes_home / "state" / "revenium")))
    return Path(os.environ.get("REVENIUM_MARKERS_DIR", str(state_dir / "markers")))


def resolve_markers_dir(
    session_id: str,
    markers_dir_override: Optional[str] = None,
) -> str:
    """Resolve the markers directory that OWNS this session.

    Mirrors classifier._paths_for_session's markers-directory resolution
    step for step: match the identifier against the `agent:<profile>:`
    namespace pattern anchored at the start; if there is no match, return
    the process-level markers directory; if the captured profile segment is
    empty or names the default profile, return the process-level markers
    directory; otherwise build the profile home under the process home's
    profiles subdirectory and, ONLY IF that path is an existing directory,
    return that profile's markers directory under its own state directory.

    The profile-home directory-existence check is load-bearing security, not
    an optimisation: it is what makes a crafted profile segment harmless — a
    traversal-shaped segment would need an actually-matching directory under
    the profiles path to redirect anything, and path joining does not itself
    collapse parent references. Do not replace it with a string check, do
    not resolve or normalise the path before it, and do not remove it.

    Fail-open: any error, including the base cases above, returns the
    process-level markers directory (never raises).
    """
    module_markers_dir = Path(markers_dir_override) if markers_dir_override else _module_markers_dir()
    try:
        m = _NS_RE.match(session_id or "")
        if not m:
            return str(module_markers_dir)
        profile = m.group(1)
        if not profile or profile == "default":
            return str(module_markers_dir)
        hermes_home = Path(os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes")))
        profile_home = hermes_home / "profiles" / profile
        if not profile_home.is_dir():
            return str(module_markers_dir)
        return str(profile_home / "state" / "revenium" / "markers")
    except Exception:
        return str(module_markers_dir)


def _main(argv: list) -> int:
    if len(argv) < 2 or not argv[1]:
        return 0
    print(resolve_markers_dir(argv[1]))
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv))
