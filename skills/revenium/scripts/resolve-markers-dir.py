#!/usr/bin/env python3
"""Resolve a per-session state subdirectory (markers, api-events, ...) that
OWNS a given session identifier.

TRACE-03 (Phase 28) cron-side mirror, generalized in Phase 32 (EVT-03) to
cover a second subdirectory rather than growing a sibling sidecar file.
Deliberately reimplements `classifier._paths_for_session`'s per-session
resolution (skills/revenium/plugins/revenium-classifier/classifier.py)
rather than importing it, because the plugin module is only importable
inside Hermes' own virtual environment — which the cron process is not
running in. This repeats the exact shape already established and documented
by skills/revenium/scripts/get-root-session-id.py for the identical reason.

`hermes-report.sh` resolves a single un-namespaced markers directory from
`common.sh` for its whole process lifetime, with zero per-session branching.
In `gateway.multiplex_profiles` mode a SINGLE default gateway process serves
EVERY profile, and each profile keeps its own state under
~/.hermes/profiles/<profile>/. Without per-session resolution, a profile's
state (markers OR, as of Phase 32, the api-events spool) is invisible to the
cron reading the process-level directory. This sidecar closes that read-side
gap for both.

Production callers shell in via the bash wrappers in scripts/common.sh:

  markers_dir="$(resolve_markers_dir "${sid}")"
  spool_dir="$(resolve_spool_dir "${sid}")"

Nothing here is shared code with classifier.py or api_event_spool.py — a
parity test is the only mechanism keeping the (now three) implementations
honest. Phase 59 (D-18): the resolution source changed from the session id
(a session-KEY-shaped `agent:<profile>:` pattern that, per the diagnosis
that root-caused this fix, could never match a real session id) to the
session ROW's `profile_name` column; any future change to either
implementation must land in both.
"""
from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path
from typing import Optional

# Phase 59 (D-18, paths-for-session-regex-may-never-match): profile values
# that mean "the process-level home" -- both spellings. Mirrors
# classifier.py's DEFAULT_PROFILE_SLOTS exactly (duplicated deliberately;
# see the module docstring's parity paragraph). session.py:1086 mints the
# LITERAL "main" as the gateway's static namespace for the default
# profile's slot; the predecessor resolution special-cased only "default",
# so `agent:main:…` resolved profile "main", looked for a directory that
# does not exist, and failed open -- correct behaviour reached by accident.
# Both spellings now mean the process-level home, explicitly.
DEFAULT_PROFILE_SLOTS = frozenset({"default", "main"})

# Phase 32 (EVT-03): map a subdirectory name to the process-level environment
# override common.sh declares for it, so both directories derive their
# defaults through the same precedence classifier.py / api_event_spool.py use
# on the plugin side. "markers" mirrors MARKERS_DIR's REVENIUM_MARKERS_DIR
# override; "api-events" mirrors EVENT_SPOOL_DIR's REVENIUM_EVENT_SPOOL_DIR
# override (common.sh's C-1 declarations).
_SUBDIR_ENV_OVERRIDE = {
    "markers": "REVENIUM_MARKERS_DIR",
    "api-events": "REVENIUM_EVENT_SPOOL_DIR",
    # Phase 42 (D-15): the job-assessments sidecar's third subdirectory.
    "job-assessments": "REVENIUM_JOB_ASSESSMENTS_DIR",
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


def _profile_name_for_session(session_id: str) -> "Optional[str]":
    """Byte-for-byte mirror of `classifier._profile_name_for_session`
    (D-18) -- deliberately duplicated, not imported (see module docstring:
    the plugin module is only importable inside Hermes' own virtual
    environment, which this cron-side process is not running in).

    Resolve the owning profile from the session ROW's `profile_name`
    column rather than from the predecessor `_NS_RE` pattern matched
    against the session id. Task 1 checkpoint, option-b: try the
    process-level database (`${HERMES_HOME}/state.db`) first; if it has no
    row for this session id, fall back to a BOUNDED scan of the existing
    profile homes under `${HERMES_HOME}/profiles/` -- one read-only open
    per existing profile home, in SORTED order, first match wins, and only
    when that directory exists at all. `sessions.profile_name` is the
    ONLY source.

    Returns the owning profile as a non-empty `str`, or `None` meaning "no
    answer, use the process paths" -- for a falsy session id; when no
    database has a row for it at all; when the found row's `profile_name`
    is NULL, non-`str`, empty, or whitespace-only; or when it names either
    spelling of the default slot (`DEFAULT_PROFILE_SLOTS`).

    Each database is opened through `sqlite3.connect(f"file:{db}?mode=ro",
    uri=True, timeout=2.0)`. The session id is always a bound parameter,
    never interpolated. A `sessions` table with no `profile_name` column
    raises `sqlite3.OperationalError` on the query; that exception IS the
    probe and is treated as "no usable row in this database," falling
    through to the next source rather than raising. Every connection this
    function opens is closed on every path. Never raises.
    """
    if not session_id:
        return None

    def _row_profile_name(db_path: Path):
        conn = None
        try:
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=2.0)
            try:
                row = conn.execute(
                    "SELECT profile_name FROM sessions WHERE id = ?", (session_id,)
                ).fetchone()
            except sqlite3.OperationalError:
                return (False, None)
            if row is None:
                return (False, None)
            return (True, row[0])
        except Exception:
            return (False, None)
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass

    try:
        hermes_home = Path(os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes")))
        found, value = _row_profile_name(hermes_home / "state.db")
        if not found:
            profiles_dir = hermes_home / "profiles"
            if profiles_dir.is_dir():
                try:
                    profile_dirnames = sorted(
                        d.name for d in profiles_dir.iterdir() if d.is_dir()
                    )
                except Exception:
                    profile_dirnames = []
                for dirname in profile_dirnames:
                    found, value = _row_profile_name(
                        profiles_dir / dirname / "state.db"
                    )
                    if found:
                        break
        if not found:
            return None
        if not isinstance(value, str):
            return None
        if not value.strip() or value in DEFAULT_PROFILE_SLOTS:
            return None
        return value
    except Exception:
        return None


def resolve_state_subdir(
    session_id: str,
    subdir: str = "markers",
    override: Optional[str] = None,
) -> str:
    """Resolve the <subdir> directory (e.g. "markers" or "api-events") that
    OWNS this session.

    Mirrors classifier._paths_for_session's directory resolution step for
    step (D-18): resolve the owning profile from the session ROW's
    `profile_name` via `_profile_name_for_session`; if that resolves to
    `None` (no row anywhere, a NULL/empty/whitespace-only value, or a
    default-slot spelling), return the process-level <subdir> directory;
    otherwise build the profile home under the process home's profiles
    subdirectory and, ONLY IF that path is an existing directory, return
    that profile's <subdir> directory under its own state directory.

    The profile-home directory-existence check is load-bearing security, not
    an optimisation: it is what makes a crafted profile value harmless — a
    traversal-shaped value would need an actually-matching directory under
    the profiles path to redirect anything, and path joining does not itself
    collapse parent references. Do not replace it with a string check, do
    not resolve or normalise the path before it, and do not remove it.

    Fail-open: any error, including the base cases above, returns the
    process-level <subdir> directory (never raises).
    """
    module_dir = Path(override) if override else _module_state_subdir(subdir)
    try:
        profile = _profile_name_for_session(session_id)
        if not profile:
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
