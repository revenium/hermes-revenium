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


def _main(argv: list) -> int:
    if len(argv) < 2 or not argv[1]:
        return 0
    print(get_root_session_id(argv[1]))
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv))
