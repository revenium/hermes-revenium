#!/usr/bin/env python3
"""Phase 68 job-attribution census harness.

Operator-invoked, stdlib only, read-only against every host. It is NOT a
`test_*.py` module, so unittest discovery never runs it; its contract is
pinned by `tests/test_phase68_attribution_census.py`.

Three subcommands:

  pull    read a host's markers, ledgers, `sessions` table and Revenium pages
          over ssh into a gitignored out-dir, digest every pulled file into
          MANIFEST.json, and stop paging only on an EMPTY page
  census  recompute every published quantity from one pull: sliced coverage,
          marker shapes, resolver rules, the zero-cost job census by cause,
          the ambiguous-root census, the counterfactual coverages
  audit   a name-aware redaction audit over a document

Rules this module holds itself to (D-11, D-11a):

  * Every remote command is a constant template in REMOTE_COMMAND_TEMPLATES
    and is run through validate_remote_command before it is sent. Nothing is
    created, modified or deleted on a measured host; output streams back to
    the local side.
  * Only aggregates leave scratch. census.json carries counts and exact
    dollar figures sliced by `agent`, never an identifier or a name, and no
    unsliced (all-agent) tenant figure. Identifying material lives in
    census-private.json and denylist.json, both mode 0600.
  * Dollar arithmetic is exact: Decimal for money, Fraction for ratios, and a
    percentage is rounded half-even to two places for display only.

Patterns (the 0600 writer, the read-only sqlite URI, the exit-code table) are
copied by value from tests/confidence_replay_harness.py; nothing is imported
from it.
"""
import argparse
import datetime
import hashlib
import json
import os
import re
import shlex
import sqlite3
import subprocess
import sys
import tarfile
import time
import urllib.parse
from decimal import Decimal, InvalidOperation
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

EXIT_OK = 0
EXIT_AUDIT = 1
EXIT_USAGE = 2
EXIT_BUDGET = 3      # plan 04
EXIT_LOCKED = 4      # plan 04
EXIT_NO_KEY = 5      # plan 04
EXIT_PREREG = 6      # plan 04
EXIT_DRIFT = 7
EXIT_REMOTE = 8
EXIT_PAGING = 9

WINDOW_DAYS = 30            # D-10
PAGE_SIZE = 100             # the CLI silently caps --page-size here
MAX_PAGES = 1000
DEFAULT_SLICE_AGENT = "Jupiter"

PAGE_ENVELOPE_KEYS = ("data", "content", "items", "rows")

# The only keys census.json may carry. `_write_aggregate` refuses the rest.
AGGREGATE_KEYS = frozenset({
    "window", "pulled_at", "coverage", "coverage_rows", "paging", "shapes",
    "jobs_per_file", "resolver_rules", "multi_job", "single_job", "zero_job",
    "unjoined", "zero_cost_jobs", "ambiguous_root", "counterfactual",
    "local_cost", "harness_sha256", "manifest_sha256",
})

# Generic vocabulary that may appear in a published record. Committed, so it
# must hold no person or customer name.
DENYLIST_ALLOW = frozenset({
    "code", "review", "pipeline", "research", "report", "daily", "session",
    "agent", "hermes", "jupiter", "revenium", "cron", "slack", "task", "test",
    "build", "deploy", "debug", "analysis", "summary", "update", "check",
    "data",
})

# Production writers this harness must never reference (checked by AST in the
# test module), plus the CLI verbs that write.
FORBIDDEN_WRITERS = frozenset({
    "_attach_assessment",
    "run_classification_async",
    "run_classification",
    "_write_job_marker",
    "_write_job_assessment",
    "_write_marker_pair",
    "_persist_job_type_to_taxonomy",
    "_persist_label_to_taxonomy",
    "meter",
    "outcome-update",
    "create",
})

# Remote commands. Constants only: every value substituted into a template is
# validated by validate_remote_command before the command is sent.
REMOTE_COMMAND_TEMPLATES = {
    "markers_tar": (
        "tar -C {state_dir} -cf - markers revenium-hermes.ledger "
        "revenium-jobs.ledger"),
    "event_ledger_cat": "cat {state_dir}/revenium-api-events.ledger 2>/dev/null",
    "sessions_schema": 'sqlite3 -readonly {db} ".schema sessions"',
    "sessions_dump": 'sqlite3 -readonly {db} ".dump sessions"',
    "completions_page": (
        "PATH={bin_prefix}:$PATH revenium metrics completions "
        "--from {from_iso} --to {to_iso} --page {page} --page-size 100 "
        "--output json"),
    "jobs_page": (
        "PATH={bin_prefix}:$PATH revenium jobs list --page {page} "
        "--page-size 100 --output json"),
    "cli_version": "PATH={bin_prefix}:$PATH revenium --version",
    "sqlite_version": "sqlite3 --version",
    "tenant": "PATH={bin_prefix}:$PATH revenium tenants get --output json",
}

_ISO_Z_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


class RemoteCommandError(Exception):
    """A command is not an allowlisted read-only template rendering."""


class PagingError(Exception):
    """A paged verb returned an unknown shape or never returned an empty
    page. Exits EXIT_PAGING rather than guessing."""


class RemoteError(Exception):
    """A remote command failed or its output could not be used."""


# ---------------------------------------------------------------------------
# Small shared helpers
# ---------------------------------------------------------------------------
def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def now_stamp():
    """ISO-8601 UTC, seconds precision, trailing Z: compares as a string."""
    return datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ")


def stamp_after(previous):
    """A stamp strictly later than `previous`. In production a pull stage
    takes longer than a second, so this never waits; it only matters on a
    fast local host, where an equal stamp would hide the stage order."""
    while True:
        stamp = now_stamp()
        if previous is None or stamp > previous:
            return stamp
        time.sleep(0.05)


def parse_json(text):
    """JSON with floats parsed to Decimal, so money is never a binary float."""
    return json.loads(text, parse_float=Decimal)


def _json_default(value):
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, Fraction):
        return f"{value.numerator}/{value.denominator}"
    raise TypeError(f"not JSON serialisable: {type(value).__name__}")


def _write_private_text(path, text):
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            fd = None
            handle.write(text)
    finally:
        if fd is not None:
            os.close(fd)


def _write_private_json(path, value):
    _write_private_text(
        path, json.dumps(value, indent=2, sort_keys=True,
                         default=_json_default) + "\n")


def _write_aggregate(path, aggregate):
    """Write census.json. A key outside AGGREGATE_KEYS is refused before
    anything is written, so an identifying field cannot ride along."""
    extra = sorted(set(aggregate) - AGGREGATE_KEYS)
    if extra:
        raise ValueError(f"aggregate keys outside the whitelist: {extra}")
    _write_private_json(path, aggregate)


def _ro_connect(db_path):
    """Open a database read-only: a missing file raises instead of being
    created."""
    uri = "file:" + urllib.parse.quote(str(db_path), safe="/") + "?mode=ro"
    return sqlite3.connect(uri, uri=True, timeout=2.0)


def _git_ignores(path):
    """True only when `git check-ignore -q` says the path is ignored. A path
    outside the repository makes git exit 128, which is a refusal too."""
    try:
        result = subprocess.run(
            ["git", "check-ignore", "-q", str(path)], cwd=str(ROOT),
            capture_output=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def _display_text(value):
    return "" if value is None else str(value)


# ---------------------------------------------------------------------------
# Exact arithmetic
# ---------------------------------------------------------------------------
def to_decimal(value):
    """A finite Decimal, or None for anything that is not a number."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, Decimal):
        out = value
    elif isinstance(value, int):
        out = Decimal(value)
    elif isinstance(value, float):
        out = Decimal(repr(value))
    elif isinstance(value, str):
        try:
            out = Decimal(value.strip())
        except InvalidOperation:
            return None
    else:
        return None
    return out if out.is_finite() else None


def decimal_text(value):
    return format(value, "f")


def display_pct(fraction):
    """A percentage for display only: ROUND_HALF_EVEN to two decimals with a
    trailing percent sign, computed in integers so a tie is a real tie."""
    if isinstance(fraction, str):
        numerator, denominator = fraction.split("/")
        fraction = Fraction(int(numerator), int(denominator))
    scaled = Fraction(fraction) * 10000  # hundredths of a percent
    quotient, remainder = divmod(scaled.numerator, scaled.denominator)
    twice = 2 * remainder
    if twice > scaled.denominator or (
            twice == scaled.denominator and quotient % 2 == 1):
        quotient += 1
    return f"{quotient // 100}.{quotient % 100:02d}%"


def fraction_text(fraction):
    return f"{fraction.numerator}/{fraction.denominator}"


def _has_job(row):
    value = row.get("agenticJobId")
    return value is not None and str(value).strip() != ""


def slice_rows(rows, agent):
    """Rows whose `agent` equals the slice exactly."""
    return [r for r in rows if isinstance(r, dict) and r.get("agent") == agent]


def row_cost(row):
    """Decimal cost of a row; a null or non-numeric `totalCost` is zero."""
    value = to_decimal(row.get("totalCost"))
    return value if value is not None else Decimal(0)


def coverage(rows, agent):
    """The one coverage function (D-06, D-09, D-11).

    `totalCost` of rows whose `agent` equals the slice and whose
    `agenticJobId` is non-empty, over the `totalCost` of every row of that
    slice. Rows of any other agent never enter either side.
    """
    sliced = slice_rows(rows, agent)
    cost_total = Decimal(0)
    cost_attributed = Decimal(0)
    rows_attributed = 0
    missing = 0
    for row in sliced:
        if to_decimal(row.get("totalCost")) is None:
            missing += 1
        cost = row_cost(row)
        cost_total += cost
        if _has_job(row):
            cost_attributed += cost
            rows_attributed += 1
    if cost_total:
        fraction = Fraction(cost_attributed) / Fraction(cost_total)
    else:
        fraction = Fraction(0, 1)
    rows_fraction = (Fraction(rows_attributed, len(sliced))
                     if sliced else Fraction(0, 1))
    return {
        "rows_total": len(sliced),
        "rows_attributed": rows_attributed,
        "cost_total": decimal_text(cost_total),
        "cost_attributed": decimal_text(cost_attributed),
        "fraction": fraction_text(fraction),
        "display_pct": display_pct(fraction),
        "rows_display_pct": display_pct(rows_fraction),
        "rows_missing_cost": missing,
    }


# ---------------------------------------------------------------------------
# Remote command allowlist (D-11, T-68-09)
# ---------------------------------------------------------------------------
_FORBIDDEN_TOKENS = frozenset({
    "rm", "mv", "cp", "tee", "mkdir", "touch", "chmod", "chown", "ln",
    "truncate", "dd", "install", "systemctl", "crontab", "kill", "pkill",
})
_UNSAFE_CHARS = ("\n", "\r", "\x00", "`", "$(", "${", ";", "&", "|", "<")
_CAT_ALLOWED_BASENAMES = frozenset({"revenium-api-events.ledger"})
_SQLITE_DOT_COMMANDS = frozenset({".schema sessions", ".dump sessions"})
_REVENIUM_FLAGS = frozenset({"--from", "--to", "--page", "--page-size",
                             "--output"})
_REVENIUM_VERBS = (("metrics", "completions"), ("jobs", "list"),
                   ("tenants", "get"))


def validate_remote_command(cmd):
    """Raise RemoteCommandError unless `cmd` is a read-only command this
    harness is allowed to send. Positive allowlist (tar -cf -, cat of one
    named ledger, sqlite3 -readonly with two dot-commands, three read verbs
    of the revenium CLI) plus a negative screen for redirection, chaining and
    write verbs."""
    if not isinstance(cmd, str) or not cmd.strip():
        raise RemoteCommandError("empty command")
    for char in _UNSAFE_CHARS:
        if char in cmd:
            raise RemoteCommandError(f"unsafe construct {char!r}")
    rest = cmd.replace("2>/dev/null", "")
    if ">" in rest:
        raise RemoteCommandError("output redirection")
    try:
        tokens = shlex.split(rest)
    except ValueError as exc:
        raise RemoteCommandError(f"unparseable: {exc}")
    while tokens and re.fullmatch(r"PATH=\S*", tokens[0]):
        tokens.pop(0)
    if not tokens:
        raise RemoteCommandError("no program")
    for token in tokens:
        if os.path.basename(token) in _FORBIDDEN_TOKENS:
            raise RemoteCommandError(f"forbidden token {token!r}")
    prog, args = tokens[0], tokens[1:]
    if prog == "tar":
        _validate_tar(args)
    elif prog == "cat":
        if (len(args) != 1
                or os.path.basename(args[0]) not in _CAT_ALLOWED_BASENAMES):
            raise RemoteCommandError("cat of an unlisted file")
    elif prog == "sqlite3":
        _validate_sqlite(args)
    elif prog == "revenium":
        _validate_revenium(args)
    else:
        raise RemoteCommandError(f"program not allowlisted: {prog!r}")


def _validate_tar(args):
    if len(args) < 5 or args[0] != "-C" or args[2:4] != ["-cf", "-"]:
        raise RemoteCommandError("tar is allowed only as -C <dir> -cf - names")
    for name in args[4:]:
        if name.startswith(("-", "/")) or ".." in name.split("/"):
            raise RemoteCommandError(f"tar member {name!r}")


def _validate_sqlite(args):
    if args == ["--version"]:
        return
    if (len(args) == 3 and args[0] == "-readonly"
            and not args[1].startswith("-")
            and args[1].endswith("state.db")
            and args[2] in _SQLITE_DOT_COMMANDS):
        return
    raise RemoteCommandError("sqlite3 must be -readonly with an allowlisted "
                             "dot-command")


def _validate_revenium(args):
    if args == ["--version"]:
        return
    head = tuple(args[:2])
    if head not in _REVENIUM_VERBS:
        raise RemoteCommandError("revenium verb is not a read verb")
    rest = args[2:]
    if len(rest) % 2:
        raise RemoteCommandError("revenium flag without a value")
    for flag, value in zip(rest[0::2], rest[1::2]):
        if flag not in _REVENIUM_FLAGS or value.startswith("--"):
            raise RemoteCommandError(f"revenium flag {flag!r}")


# ---------------------------------------------------------------------------
# Paging
# ---------------------------------------------------------------------------
def page_rows(text):
    """Rows of one page: a JSON list, or a dict holding a list under `data`,
    `content`, `items` or `rows`. Any other shape raises PagingError."""
    try:
        value = parse_json(text)
    except ValueError as exc:
        raise PagingError(f"page is not JSON: {exc}")
    rows = None
    if isinstance(value, list):
        rows = value
    elif isinstance(value, dict):
        for key in PAGE_ENVELOPE_KEYS:
            if isinstance(value.get(key), list):
                rows = value[key]
                break
    if rows is None:
        raise PagingError("page shape is not a list or a known envelope")
    if not all(isinstance(r, dict) for r in rows):
        raise PagingError("page rows are not objects")
    return rows


def load_rows(out_dir, kind):
    """Every row of every pulled page of `kind` (`completions` or `jobs`)."""
    rows = []
    pages = sorted((Path(out_dir) / kind).glob("page-*.json"))
    for page in pages:
        rows.extend(page_rows(page.read_text(encoding="utf-8")))
    return rows


# ---------------------------------------------------------------------------
# pull
# ---------------------------------------------------------------------------
def _ssh_prefix(args):
    prefix = shlex.split(args.ssh_cmd)
    if args.ssh_key:
        prefix += ["-i", args.ssh_key]
    prefix += ["-o", "BatchMode=yes", "-o", "ConnectTimeout=15"]
    prefix.append(args.ssh_target)
    return prefix


def run_remote(prefix, cmd, stdout_path=None, timeout=3600):
    """Validate, then run one remote command. Stdout is streamed straight
    into a local 0600 file when `stdout_path` is given (never through a
    remote temp file), else captured. Returns (returncode, bytes, stderr)."""
    validate_remote_command(cmd)
    argv = list(prefix) + [cmd]
    if stdout_path is not None:
        fd = os.open(str(stdout_path),
                     os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as handle:
            proc = subprocess.run(argv, stdout=handle,
                                  stderr=subprocess.PIPE, timeout=timeout)
        return proc.returncode, None, proc.stderr
    proc = subprocess.run(argv, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, timeout=timeout)
    return proc.returncode, proc.stdout, proc.stderr


def _safe_member_path(out_dir, name):
    if not name or name.startswith("/") or ".." in Path(name).parts:
        raise RemoteError("tar member escapes the out-dir")
    target = (Path(out_dir) / name).resolve()
    base = Path(out_dir).resolve()
    if target != base and base not in target.parents:
        raise RemoteError("tar member escapes the out-dir")
    return target


def extract_tar(tar_path, out_dir):
    """Extract regular files and directories only, every member checked to
    stay inside the out-dir, files written 0600 and directories 0700."""
    with tarfile.open(str(tar_path), "r:") as archive:
        for member in archive:
            target = _safe_member_path(out_dir, member.name)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True, mode=0o700)
            elif member.isfile():
                target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                source = archive.extractfile(member)
                fd = os.open(str(target),
                             os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                with os.fdopen(fd, "wb") as handle:
                    handle.write(source.read())
            else:
                raise RemoteError("tar member is not a file or directory")


def _pull_pages(prefix, out_dir, kind, template_key, fmt, max_pages):
    directory = Path(out_dir) / kind
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    pages_read = 0
    row_count = 0
    last_empty = False
    for page in range(max_pages):
        cmd = REMOTE_COMMAND_TEMPLATES[template_key].format(page=page, **fmt)
        code, data, _err = run_remote(prefix, cmd)
        if code != 0:
            raise RemoteError(f"{kind} page {page} exited {code}")
        text = data.decode("utf-8", errors="replace")
        rows = page_rows(text)
        _write_private_text(directory / f"page-{page:04d}.json", text)
        pages_read += 1
        if not rows:
            last_empty = True
            break
        row_count += len(rows)
    if not last_empty:
        raise PagingError(
            f"{kind}: no empty page within {max_pages} pages")
    return {"pages_read": pages_read, "rows": row_count,
            "last_page_empty": True, "first_page_index": 0,
            "max_pages": max_pages}


def _text_or_unavailable(prefix, template_key, fmt):
    cmd = REMOTE_COMMAND_TEMPLATES[template_key].format(**fmt)
    code, data, _err = run_remote(prefix, cmd, timeout=120)
    if code != 0:
        return "unavailable"
    return data.decode("utf-8", errors="replace").strip() or "unavailable"


def collect_files(out_dir):
    """sha256 and size of every pulled file. The manifest itself and the
    files `census` writes later are not pulled files."""
    skip = {"MANIFEST.json", "census.json", "census-private.json",
            "denylist.json"}
    base = Path(out_dir)
    files = {}
    for path in sorted(base.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        rel = path.relative_to(base).as_posix()
        if rel in skip:
            continue
        files[rel] = {"sha256": sha256_file(path), "size": path.stat().st_size}
    return files


def write_manifest(out_dir, meta):
    """Digest every pulled file and write MANIFEST.json (0600). `meta` holds
    everything that is not a digest: window, stamps, paging, versions."""
    manifest = dict(meta)
    manifest["files"] = collect_files(out_dir)
    manifest["harness_sha256"] = sha256_file(Path(__file__))
    _write_private_json(Path(out_dir) / "MANIFEST.json", manifest)
    return manifest


def _window(args):
    to_iso = args.to or now_stamp()
    if not _ISO_Z_RE.match(to_iso):
        raise ValueError("--to must be ISO-8601 UTC, seconds precision, Z")
    to_dt = datetime.datetime.strptime(to_iso, "%Y-%m-%dT%H:%M:%SZ")
    from_iso = args.from_
    if from_iso is None:
        from_iso = (to_dt - datetime.timedelta(days=WINDOW_DAYS)).strftime(
            "%Y-%m-%dT%H:%M:%SZ")
    if not _ISO_Z_RE.match(from_iso):
        raise ValueError("--from must be ISO-8601 UTC, seconds precision, Z")
    return from_iso, to_iso


def cmd_pull(args):
    out_dir = Path(args.out_dir).absolute()
    if not _git_ignores(out_dir):
        print("refused: --out-dir is not ignored by git "
              "(git check-ignore -q failed)", file=sys.stderr)
        return EXIT_USAGE
    try:
        from_iso, to_iso = _window(args)
    except ValueError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return EXIT_USAGE
    max_pages = args.max_pages

    home = args.remote_hermes_home.rstrip("/")
    fmt = {
        "state_dir": f"{home}/state/revenium",
        "db": f"{home}/state.db",
        "bin_prefix": args.bin_prefix,
        "from_iso": from_iso,
        "to_iso": to_iso,
    }
    prefix = _ssh_prefix(args)
    out_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    used = []
    try:
        # 1. markers and ledgers first (Pitfall 5: a prune can remove
        #    window-edge markers while the rest of the pull runs).
        tar_path = out_dir / "markers.tar"
        used.append("markers_tar")
        code, _d, err = run_remote(
            prefix, REMOTE_COMMAND_TEMPLATES["markers_tar"].format(**fmt),
            stdout_path=tar_path)
        if code != 0:
            raise RemoteError(f"markers tar exited {code}")
        extract_tar(tar_path, out_dir)
        used.append("event_ledger_cat")
        event_path = out_dir / "revenium-api-events.ledger"
        code, _d, _err = run_remote(
            prefix,
            REMOTE_COMMAND_TEMPLATES["event_ledger_cat"].format(**fmt),
            stdout_path=event_path)
        event_present = code == 0
        if not event_present:
            event_path.unlink(missing_ok=True)
        markers_at = stamp_after(None)

        # 2. the sessions table.
        used += ["sessions_schema", "sessions_dump"]
        for key, name in (("sessions_schema", "sessions.schema.sql"),
                          ("sessions_dump", "sessions.dump.sql")):
            code, _d, err = run_remote(
                prefix, REMOTE_COMMAND_TEMPLATES[key].format(**fmt),
                stdout_path=out_dir / name)
            if code != 0:
                raise RemoteError(f"{key} exited {code}")
        _rebuild_state_db(out_dir)
        sessions_at = stamp_after(markers_at)

        # 3. Revenium pages, until an EMPTY page.
        used += ["completions_page", "jobs_page"]
        paging = {
            "completions": _pull_pages(prefix, out_dir, "completions",
                                       "completions_page", fmt, max_pages),
            "jobs": _pull_pages(prefix, out_dir, "jobs", "jobs_page", fmt,
                                max_pages),
        }
        revenium_at = stamp_after(sessions_at)

        used += ["cli_version", "sqlite_version", "tenant"]
        versions = {
            "cli_version": _text_or_unavailable(prefix, "cli_version", fmt),
            "sqlite_version": _text_or_unavailable(prefix, "sqlite_version",
                                                   fmt),
        }
        tenant = _text_or_unavailable(prefix, "tenant", fmt)
    except RemoteCommandError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return EXIT_USAGE
    except PagingError as exc:
        print(f"paging failed: {exc}", file=sys.stderr)
        return EXIT_PAGING
    except (RemoteError, OSError, subprocess.TimeoutExpired,
            tarfile.TarError, sqlite3.Error) as exc:
        print(f"remote pull failed: {type(exc).__name__}: {exc}",
              file=sys.stderr)
        return EXIT_REMOTE

    write_manifest(out_dir, {
        "host_label": args.host_label,
        "slice_agent": args.agent,
        "window": {"from": from_iso, "to": to_iso, "days": WINDOW_DAYS},
        "markers_pulled_at": markers_at,
        "sessions_pulled_at": sessions_at,
        "revenium_pulled_at": revenium_at,
        "paging": paging,
        "templates_used": sorted(set(used)),
        "event_ledger_present": event_present,
        "tenant": tenant,
        **versions,
    })
    print(f"pulled {paging['completions']['rows']} completion rows over "
          f"{paging['completions']['pages_read']} pages", file=sys.stdout)
    return EXIT_OK


def _rebuild_state_db(out_dir):
    """Rebuild a local `state.db` holding the `sessions` table from the
    dump. The dump is data; nothing on the host is touched."""
    dump = (out_dir / "sessions.dump.sql").read_text(
        encoding="utf-8", errors="replace")
    if "CREATE TABLE" not in dump:
        raise RemoteError("sessions dump holds no CREATE TABLE")
    target = out_dir / "state.db"
    target.unlink(missing_ok=True)
    conn = sqlite3.connect(str(target))
    try:
        conn.executescript(dump)
        conn.commit()
    finally:
        conn.close()
    os.chmod(str(target), 0o600)


# ---------------------------------------------------------------------------
# Loading a pull
# ---------------------------------------------------------------------------
class DriftError(Exception):
    """A pulled file differs from its MANIFEST.json digest."""


def load_manifest(out_dir):
    path = Path(out_dir) / "MANIFEST.json"
    return json.loads(path.read_text(encoding="utf-8"))


def verify_manifest(out_dir, manifest):
    """Every pulled file must still hash to its manifest digest."""
    bad = 0
    for rel, meta in manifest.get("files", {}).items():
        path = Path(out_dir) / rel
        if not path.is_file() or sha256_file(path) != meta.get("sha256"):
            bad += 1
    if bad:
        raise DriftError(f"{bad} pulled file(s) differ from MANIFEST.json")


def _read_lines(path):
    try:
        return Path(path).read_text(
            encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []


# ---------------------------------------------------------------------------
# Deny-list and audit (D-11a)
# ---------------------------------------------------------------------------
_TOKEN_RE = re.compile(r"[a-z0-9]+")
_PERSON_COLUMNS = ("title", "display_name", "user_id", "user_name")


def _iter_marker_job_records(out_dir):
    for path in sorted((Path(out_dir) / "markers").glob("*.jsonl")):
        for line in _read_lines(path):
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if isinstance(rec, dict) and rec.get("kind") == "job":
                yield rec


def _session_text_values(out_dir):
    db = Path(out_dir) / "state.db"
    if not db.is_file():
        return
    try:
        conn = _ro_connect(db)
    except sqlite3.Error:
        return
    try:
        columns = [r[1] for r in conn.execute("PRAGMA table_info(sessions)")]
        wanted = [c for c in _PERSON_COLUMNS if c in columns]
        for column in wanted:
            for (value,) in conn.execute(
                    f'SELECT "{column}" FROM sessions'):
                if isinstance(value, str) and value:
                    yield value
    except sqlite3.Error:
        return
    finally:
        conn.close()


def build_denylist(out_dir):
    """Tokens (length >= 4, lower-cased, not purely digits) from every
    job id, job name, job type and person-bearing `sessions` column in the
    pulled corpus, minus DENYLIST_ALLOW. Also each full job id, for exact
    substring matching. Lives in scratch only."""
    ids, texts = set(), []
    for rec in _iter_marker_job_records(out_dir):
        ids.add(_display_text(rec.get("agentic_job_id")))
        texts += [_display_text(rec.get("job_name")),
                  _display_text(rec.get("job_type"))]
    for line in _read_lines(Path(out_dir) / "revenium-jobs.ledger"):
        parts = line.split(":", 3)
        if len(parts) >= 3 and parts[0] == "JOB":
            ids.add(parts[1])
    for kind, id_key, name_key, type_key in (
            ("completions", "agenticJobId", "agenticJobName",
             "agenticJobType"),
            ("jobs", "agenticJobId", "name", "type")):
        try:
            rows = load_rows(out_dir, kind)
        except (PagingError, OSError):
            rows = []
        for row in rows:
            ids.add(_display_text(row.get(id_key)))
            texts += [_display_text(row.get(name_key)),
                      _display_text(row.get(type_key))]
    texts += list(_session_text_values(out_dir))
    ids.discard("")
    tokens = set()
    for text in list(ids) + texts:
        for token in _TOKEN_RE.findall(text.lower()):
            if len(token) >= 4 and not token.isdigit():
                tokens.add(token)
    tokens -= DENYLIST_ALLOW
    return {"tokens": sorted(tokens),
            "deny_exact": sorted(i for i in ids if len(i) >= 4)}


_HEX_ID_RE = re.compile(r"(?<![0-9A-Za-z])[0-9a-f]{32,33}(?![0-9A-Za-z])")
_SESSION_ID_RE = re.compile(r"\d{8}_\d{6}_[0-9a-f]+")
_JOB_SUFFIX_RE = re.compile(
    r"(?<![A-Za-z0-9_])[a-z0-9]+(?:_[a-z0-9]+)*_[0-9a-f]{4}(?![A-Za-z0-9_])")
_IPV4_RE = re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])")
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
_PEM_RE = re.compile(r"\.pem")
_UBUNTU_RE = re.compile(r"ubuntu", re.IGNORECASE)
_TENANT_RE = re.compile(r"3By1Ra6|aL7ZRO2")
SHAPE_REGEXES = (_HEX_ID_RE, _SESSION_ID_RE, _JOB_SUFFIX_RE, _IPV4_RE,
                 _EMAIL_RE, _PEM_RE, _UBUNTU_RE, _TENANT_RE)


def mask_token(token):
    """First two characters, then asterisks: the audit never prints a name."""
    return token[:2] + "*" * max(len(token) - 2, 0)


def audit_text(text, denylist=None):
    """[(line_number, masked_token)] for every hit in `text`."""
    hits = []
    word_re = None
    exact = []
    if denylist:
        tokens = sorted(set(denylist.get("tokens", [])), key=len,
                        reverse=True)
        if tokens:
            word_re = re.compile(
                r"(?<![a-z0-9])(?:" + "|".join(re.escape(t) for t in tokens)
                + r")(?![a-z0-9])")
        exact = [e.lower() for e in denylist.get("deny_exact", []) if e]
    for number, line in enumerate(text.splitlines(), 1):
        lowered = line.lower()
        if word_re is not None:
            for match in word_re.finditer(lowered):
                hits.append((number, mask_token(match.group(0))))
        for needle in exact:
            if needle in lowered:
                hits.append((number, mask_token(needle)))
        for regex in SHAPE_REGEXES:
            for match in regex.finditer(line):
                hits.append((number, mask_token(match.group(0))))
    return hits


def cmd_audit(args):
    path = Path(args.path)
    if not args.shapes_only and not args.denylist:
        print("usage: pass --denylist <file> or --shapes-only",
              file=sys.stderr)
        return EXIT_USAGE
    denylist = None
    if args.denylist:
        try:
            denylist = json.loads(Path(args.denylist).read_text())
        except (OSError, ValueError) as exc:
            print(f"usage: cannot read the deny-list: {type(exc).__name__}",
                  file=sys.stderr)
            return EXIT_USAGE
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        print(f"usage: cannot read the document: {type(exc).__name__}",
              file=sys.stderr)
        return EXIT_USAGE
    hits = audit_text(text, None if args.shapes_only else denylist)
    for number, masked in hits:
        print(f"line {number}: {masked}")
    return EXIT_AUDIT if hits else EXIT_OK


# ---------------------------------------------------------------------------
# census
# ---------------------------------------------------------------------------
def build_census(out_dir, manifest, agent):
    """Every aggregate the record publishes from one pull. Returns
    (aggregate, private): `aggregate` holds counts and exact dollars only."""
    completions = load_rows(out_dir, "completions")
    cov = coverage(completions, agent)
    aggregate = {
        "window": dict(manifest["window"]),
        "pulled_at": {
            "markers": manifest["markers_pulled_at"],
            "sessions": manifest["sessions_pulled_at"],
            "revenium": manifest["revenium_pulled_at"],
        },
        "coverage": cov,
        "coverage_rows": {
            "rows_total": cov["rows_total"],
            "rows_attributed": cov["rows_attributed"],
            "rows_display_pct": cov["rows_display_pct"],
            "rows_missing_cost": cov["rows_missing_cost"],
        },
        "paging": manifest["paging"],
        "harness_sha256": sha256_file(Path(__file__)),
        "manifest_sha256": sha256_file(Path(out_dir) / "MANIFEST.json"),
    }
    private = {"host_label": manifest.get("host_label"),
               "slice_agent": agent}
    return aggregate, private


def cmd_census(args):
    out_dir = Path(args.out_dir).absolute()
    if not _git_ignores(out_dir):
        print("refused: --out-dir is not ignored by git", file=sys.stderr)
        return EXIT_USAGE
    try:
        manifest = load_manifest(out_dir)
    except (OSError, ValueError) as exc:
        print(f"usage: no readable MANIFEST.json: {type(exc).__name__}",
              file=sys.stderr)
        return EXIT_USAGE
    try:
        verify_manifest(out_dir, manifest)
    except DriftError as exc:
        print(f"drift: {exc}", file=sys.stderr)
        return EXIT_DRIFT
    agent = args.agent or manifest.get("slice_agent") or DEFAULT_SLICE_AGENT
    try:
        aggregate, private = build_census(out_dir, manifest, agent)
    except PagingError as exc:
        print(f"paging: {exc}", file=sys.stderr)
        return EXIT_PAGING
    _write_aggregate(out_dir / "census.json", aggregate)
    _write_private_json(out_dir / "census-private.json", private)
    _write_private_json(out_dir / "denylist.json", build_denylist(out_dir))
    print("census written")
    return EXIT_OK


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _parser():
    parser = argparse.ArgumentParser(prog="job_attribution_harness")
    sub = parser.add_subparsers(dest="command", required=True)

    pull = sub.add_parser("pull", help="read-only pull of one host")
    pull.add_argument("--ssh-cmd", default="ssh")
    pull.add_argument("--ssh-target", required=True)
    pull.add_argument("--ssh-key")
    pull.add_argument("--host-label", required=True)
    pull.add_argument("--remote-hermes-home", default="~/.hermes")
    pull.add_argument("--bin-prefix", default="/home/linuxbrew/.linuxbrew/bin")
    pull.add_argument("--agent", default=DEFAULT_SLICE_AGENT)
    pull.add_argument("--to")
    pull.add_argument("--from", dest="from_")
    pull.add_argument("--out-dir", required=True)
    pull.add_argument("--max-pages", type=int, default=MAX_PAGES,
                      help=argparse.SUPPRESS)

    census = sub.add_parser("census", help="aggregates from one pull")
    census.add_argument("--out-dir", required=True)
    census.add_argument("--agent")

    audit = sub.add_parser("audit", help="name-aware redaction audit")
    audit.add_argument("path")
    audit.add_argument("--denylist")
    audit.add_argument("--shapes-only", action="store_true")
    return parser


def main(argv=None):
    parser = _parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else EXIT_USAGE
    if args.command == "pull":
        return cmd_pull(args)
    if args.command == "census":
        return cmd_census(args)
    return cmd_audit(args)


if __name__ == "__main__":
    sys.exit(main())
