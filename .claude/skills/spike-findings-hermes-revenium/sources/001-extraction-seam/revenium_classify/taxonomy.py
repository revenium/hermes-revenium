"""Taxonomy access behind a two-method protocol.

The protocol is the whole point: `labels()` and `record(label)`. A file-backed
store (what Hermes uses today) and an HTTP-backed store (what a fleet of hosts
would need — see spike 003) are interchangeable behind it.
"""
from __future__ import annotations

import datetime
import fcntl
import json
import logging
import os
from pathlib import Path

logger = logging.getLogger("revenium_classify")

RECENT_DAYS = 7


class TaxonomyStore:
    """Interface. Implementations must be fail-open: never raise to the caller."""

    def labels(self) -> list:
        raise NotImplementedError

    def record(self, label: str) -> None:
        raise NotImplementedError


class InMemoryTaxonomy(TaxonomyStore):
    """For hosts with no filesystem (a guardrail worker) and for tests."""

    def __init__(self, seed: "list | None" = None):
        self._labels = list(seed or [])

    def labels(self) -> list:
        return list(self._labels)

    def record(self, label: str) -> None:
        if label and label != "unclassified" and label not in self._labels:
            self._labels.append(label)


class FileTaxonomy(TaxonomyStore):
    """JSON-file store with the original's recency ordering and locked mint-back."""

    def __init__(self, path):
        self.path = Path(path)

    def labels(self) -> list:
        """Recent-first (last_seen_at within RECENT_DAYS), then alpha. [] on any failure."""
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            labels = data.get("labels", {})
            if not isinstance(labels, dict):
                return []
            now = datetime.datetime.now(datetime.timezone.utc)
            recent_cutoff = now - datetime.timedelta(days=RECENT_DAYS)
            recent, older = [], []
            for key, meta in sorted(labels.items()):
                raw_ts = meta.get("last_seen_at") if isinstance(meta, dict) else None
                if raw_ts:
                    try:
                        ts = datetime.datetime.fromisoformat(raw_ts.rstrip("Z")).replace(
                            tzinfo=datetime.timezone.utc
                        )
                        if ts >= recent_cutoff:
                            recent.append((ts, key))
                            continue
                    except Exception:
                        pass
                older.append(key)
            recent.sort(key=lambda x: x[0], reverse=True)
            return [k for _, k in recent] + older
        except Exception:
            pass
        return []

    def record(self, label: str) -> None:
        """Append/refresh under a non-blocking sidecar lock; atomic replace. Fail-open."""
        if not label or label == "unclassified":
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            lock_path = self.path.parent / (self.path.name + ".lock")
            try:
                with open(lock_path, "a") as lockfd:
                    try:
                        fcntl.flock(lockfd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    except OSError as exc:
                        logger.warning("taxonomy persist skipped, lock contention for label=%s: %s", label, exc)
                        return
                    try:
                        data = json.loads(self.path.read_text(encoding="utf-8"))
                    except Exception:
                        data = {"labels": {}}
                    labels = data.get("labels", {})
                    if not isinstance(labels, dict):
                        labels = {}
                    now_iso = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                    if label not in labels:
                        labels[label] = {"description": None, "examples": [], "last_seen_at": now_iso}
                    else:
                        if not isinstance(labels[label], dict):
                            labels[label] = {}
                        labels[label]["last_seen_at"] = now_iso
                    data["labels"] = labels
                    tmp = self.path.parent / (self.path.name + ".tmp")
                    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
                    tmp.replace(self.path)
            except OSError as exc:
                logger.warning("taxonomy persist skipped, lock contention for label=%s: %s", label, exc)
                return
        except Exception as exc:
            logger.warning("mint-back failed for label=%s: %s", label, exc)
