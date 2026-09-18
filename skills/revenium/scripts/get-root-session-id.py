#!/usr/bin/env python3
"""Walk state.db.sessions.parent_session_id to the root delegator.

TRACE-01 path foundation for v1.4 (Phase 21). Mirrors the existing
classifier._walk_to_root_session helper (max_depth=10 circular guard,
fail-open to input sid on any error). No consumer wires into this in
Phase 21; Phase 22 wires it into hermes-report.sh + tool-event-report.sh.

Production callers shell in via the bash wrapper in scripts/common.sh:

  root_sid="$(get_root_session_id "${sid}")"

Tests import the function directly and pass `state_db_path=<tempdir>/state.db`.

Per D-03, classifier._walk_to_root_session is NOT refactored in Phase 21 —
this sidecar is the canonical implementation going forward; Phase 22 may
DRY-cleanup the classifier path.
"""
from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path
from typing import Optional


def _resolve_state_db(state_db_path: Optional[str]) -> Path:
    if state_db_path is not None:
        return Path(state_db_path)
    hermes_home = Path(os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes")))
    return hermes_home / "state.db"


def get_root_session_id(
    sid: str,
    state_db_path: Optional[str] = None,
    max_depth: int = 10,
) -> str:
    """Walk state.db.sessions.parent_session_id chain to the root delegator.

    Returns the input sid on any error path: missing state.db, sqlite errors,
    missing rows, schema mismatches, or pathological corrupted parent chains
    that exceed max_depth. Never raises (D-04/D-05 invariant carried from
    classifier.py:73-76).
    """
    if not sid:
        return sid
    state_db = _resolve_state_db(state_db_path)
    if not state_db.exists():
        return sid
    try:
        uri = f"file:{state_db}?mode=ro"
        with sqlite3.connect(uri, uri=True) as conn:
            current = sid
            for _ in range(max_depth):
                row = conn.execute(
                    "SELECT parent_session_id FROM sessions WHERE id = ?",
                    (current,),
                ).fetchone()
                if row is None or row[0] is None:
                    return current
                current = row[0]
            return current
    except sqlite3.OperationalError:
        return sid
    except Exception:
        return sid


def _walk_parent_map(sid: str, parents: dict, max_depth: int = 10) -> str:
    """Walk an in-memory {id: parent_session_id} map to the root delegator.

    Deliberately mirrors get_root_session_id's loop STATEMENT FOR STATEMENT
    rather than sharing code with it, because the two differ only in where a
    parent comes from and the pair is pinned by an equivalence test. Three
    behaviours are easy to get wrong and are load-bearing:

      * a sid ABSENT from the map returns itself -- the per-session form's
        `row is None` branch, which is how an id that is not in `sessions`
        at all (a pseudo- or event-path id) resolves.
      * a NULL parent returns the CURRENT node, not the input sid.
      * DEPTH EXHAUSTION returns `current` -- the node reached after
        max_depth hops -- NOT the input sid. Only the exception paths fail
        open to the input, and conflating the two would silently re-parent
        every session on a pathological chain.
    """
    current = sid
    for _ in range(max_depth):
        if current not in parents:
            return current
        parent = parents[current]
        if parent is None:
            return current
        current = parent
    return current


def get_root_session_ids(
    sids,
    state_db_path: Optional[str] = None,
    max_depth: int = 10,
) -> dict:
    """Resolve many sids in ONE process against ONE query.

    Exists purely to remove a per-session python3 cold start. Measured on a
    live host 2026-09-18: the per-session form costs 0.189s per call of which
    0.129s is bare interpreter startup, so a 2,995-session tick spent ~565s
    (~9.4 min) resolving roots -- roughly two thirds of it starting Python
    over and over to ask one question of the same database.

    Returns {sid: root_sid} for every input sid. Fail-open is identity, the
    same contract the per-session form carries: a missing or unreadable
    state.db maps every sid to ITSELF rather than raising or omitting it, so
    a caller can always index the result.
    """
    out = {}
    unique = []
    seen = set()
    for sid in sids:
        if sid in seen:
            continue
        seen.add(sid)
        unique.append(sid)

    # An empty sid resolves to itself in the per-session form (the `if not
    # sid` guard returns it unchanged), so it must here too.
    resolvable = [s for s in unique if s]
    for sid in unique:
        out[sid] = sid
    if not resolvable:
        return out

    state_db = _resolve_state_db(state_db_path)
    if not state_db.exists():
        return out

    try:
        uri = f"file:{state_db}?mode=ro"
        parents = {}
        with sqlite3.connect(uri, uri=True) as conn:
            # The WHOLE table, not a WHERE id IN (...) restricted to the
            # inputs: resolution follows parent links OUT of the input set,
            # and a parent that was not itself requested would be missing
            # from a restricted map and be mistaken for an absent row --
            # terminating the walk early and returning a subagent as its own
            # root. One full scan is also cheaper than chunking a large IN
            # list across sqlite's variable limit.
            for row_id, row_parent in conn.execute(
                "SELECT id, parent_session_id FROM sessions"
            ):
                if row_id is not None:
                    parents[str(row_id)] = (
                        None if row_parent is None else str(row_parent)
                    )
    except sqlite3.OperationalError:
        return out
    except Exception:
        return out

    for sid in resolvable:
        out[sid] = _walk_parent_map(sid, parents, max_depth=max_depth)
    return out


def _main(argv: list) -> int:
    # Batch mode: sids arrive one per line on stdin, results leave as
    # "<sid>\t<root_sid>". TSV because a session id cannot contain a tab (the
    # producing ids are timestamp/hex or 'agent:<profile>:...' forms) while a
    # caller splitting on whitespace would break on nothing at all -- and the
    # bash side reads it with `cut`, which wants a single-character delimiter.
    if len(argv) >= 2 and argv[1] == "--batch":
        sids = [line.rstrip("\n") for line in sys.stdin]
        sids = [s for s in sids if s]
        resolved = get_root_session_ids(sids)
        for sid in sids:
            print(f"{sid}\t{resolved.get(sid, sid)}")
        return 0
    if len(argv) < 2 or not argv[1]:
        return 0
    print(get_root_session_id(argv[1]))
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv))
