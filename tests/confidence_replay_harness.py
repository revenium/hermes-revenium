#!/usr/bin/env python3
"""Phase 67 (TRU-03) on-host replay harness for the evaluator's `confidence`.

Committed, stdlib-only, operator-invoked tool. NOT a `test_*.py` module -- the
filename deliberately does not match the discovery pattern, so it never runs
as part of `python3 -m unittest discover`. Phase 70 re-runs it on a model
change.

What it measures. For each arc in a pool, and for each prompt arm, it drives
the deployed classifier module's OWN `_evaluate_outcome_via_llm` and
`_validate_assessment`, and counts a confidence omission only when the
production validator emits a log record whose unformatted format string equals
`INSTRUMENT_FORMAT`, the string Phase 70 greps in `agent.log`. Every arm's
prompt is the real `_build_outcome_evaluation_prompt` output, edited by
count-asserted text surgery on the head of the prompt (the instruction text
before the first `Task arc:` line). The tail, which holds the job name and the
transcript, is reattached byte for byte.

The one difference from production is the `provider` and `model` keyword
arguments on the model call. Production's `temperature`, `max_tokens` and
`timeout` reach the call untouched because the harness replaces only the
module's `call_llm` global (with a function that adds those two kwargs) and
its `_build_outcome_evaluation_prompt` global (with a function that applies
the arm).

What it never does. It writes no sidecar line, no marker, no taxonomy entry
and no ledger line, and it persists no response text, transcript text, job
name or job id. It calls no function in `FORBIDDEN_WRITERS`; a test walks this
file's AST to prove it. A per-call record holds only the whitelisted scalar
fields in `PER_CALL_RECORD_KEYS`, and arcs are keyed by the first 16 hex
characters of the sha256 of the job id.

Concurrency. The research sketch swapped the module's prompt builder per call
and restored it afterwards, which is unsafe once two calls run at once: one
call's restore lands inside another's window. Here the arm and the per-call
diagnostics travel in a `contextvars.ContextVar` (`_CALL_CTX`). The builder
and model-call replacements are installed once, and they read the context at
call time. `asyncio.to_thread`, which production uses for the model call,
copies the calling context into its worker thread, so the model-call
replacement sees the same context dict as the coroutine that awaits it.

The host-only parts (plan 03) import Hermes' `agent.auxiliary_client`
lazily, so this module imports anywhere, including the local test run.
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import contextvars
import hashlib
import importlib.util
import inspect
import json
import logging
import math
import os
import re
import sqlite3
import statistics
import sys
import time
import urllib.parse
import uuid
from collections import Counter, namedtuple
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PLUGIN_DIR = (
    ROOT / "skills" / "revenium" / "plugins" / "revenium-classifier")

REPLAY_MODEL = "z-ai/glm-5.2"
REPLAY_PROVIDER = "openrouter"

# The production log format string the validator emits when `confidence` is
# absent, null, non-numeric or outside [0,1]. Matched by equality with
# `record.msg`, never by rendered text (so model output is never formatted).
INSTRUMENT_FORMAT = (
    "revenium-classifier: rejected assessment, confidence outside [0,1]: %r"
)

# Every log format string `_validate_assessment` and `_evaluate_outcome_via_llm`
# can emit, mapped to a short token. The classifier line each was read from is
# in the trailing comment. An unknown format maps to "other".
VALIDATOR_TOKENS = {
    # _evaluate_outcome_via_llm
    "revenium-classifier: outcome evaluation response truncated "
    "(finish_reason=length) for job=%s -- distinct from a malformed "
    "response, see _EVAL_MAX_TOKENS": "truncated",  # classifier.py:1157
    "revenium-classifier outcome evaluation LLM call failed: %r":
        "llm_call_failed",  # classifier.py:1194
    # _validate_assessment
    "revenium-classifier: rejected assessment, unrecognised or operator-only "
    "economic_mechanism: %r": "mechanism_rejected",  # classifier.py:2300
    "revenium-classifier: rejected assessment, non-numeric hours/rate: %r":
        "hours_rate_nonnumeric",  # classifier.py:2310
    "revenium-classifier: assessment abstained, bound exceeded: %r":
        "bound_exceeded",  # classifier.py:2319
    INSTRUMENT_FORMAT: "confidence_omitted",  # classifier.py:2327
    "revenium-classifier: assessment abstained, disordered or invalid value "
    "bounds: %r": "value_bounds",  # classifier.py:2342
    "revenium-classifier: rejected assessment, unsupported or mismatched "
    "currency: %r (configured %r)": "currency",  # classifier.py:2357
    "revenium-classifier: valuation implementation %r unresolved, falling "
    "back to the built-in derivation": "valuation_unresolved",  # :2413
    "revenium-classifier: failed to reset the valuation delegation marker; "
    "delegated-builtin lower bound will not apply for this call":
        "valuation_reset_failed",  # classifier.py:2432
    "revenium-classifier: valuation implementation %r raised, falling back "
    "to the built-in derivation": "valuation_raised",  # classifier.py:2440
    "revenium-classifier: assessment abstained, revenue valuation "
    "implementation %r could not be attributed to this session's owning "
    "profile with certainty on this host":
        "valuation_unattributed",  # classifier.py:2501
    "revenium-classifier: assessment abstained, valuation implementation %r "
    "returned an invalid or out-of-bounds value: %r":
        "valuation_invalid_value",  # classifier.py:2621
}

TASK_ARC_BOUNDARY = "\n\nTask arc: "

# ---------------------------------------------------------------------------
# Arm strings. Copied verbatim from the plan's <arm_spec>.
# ---------------------------------------------------------------------------
CONFIDENCE_LINE = (
    "  - confidence: a number from 0 to 1 reflecting how well the transcript "
    "supports this estimate\n"
)
# Today's orphan bullet at the head of the trailer.
TRAILER_CONFIDENCE_BULLET = CONFIDENCE_LINE + "\n"
PREAMBLE_ONLY_CLAUSE = (
    "then supply ONLY the fields listed under that mechanism's own block "
    "below -- do not mix fields from a different block."
)
PREAMBLE_ALWAYS_CLAUSE = (
    "then supply the fields listed directly below, which every response "
    "carries whichever mechanism you choose, plus ONLY the fields listed "
    "under that mechanism's own block below -- do not mix fields from a "
    "different block."
)
MECHANISM_BULLET_TAIL = 'or "newly_enabled_work"\n\n'
REQUIRED_SENTENCE = (
    "confidence is required in every JSON object you output, whichever "
    "mechanism you choose. A response that supplies hours and a rate but no "
    "confidence is discarded in full.\n\n"
)
ABSTAIN_FIELD_CLAUSE = "Do not invent a number to fill the field."
ABSTAIN_SCOPED_CLAUSE = (
    "Do not invent an hours estimate or a loaded rate to fill those fields."
)
# Occurs twice, once in each counterfactual block, by design.
COUNTERFACTUAL_BASIS_LINE = (
    "  - basis: one sentence naming what work was avoided\n\n"
)
NEWLY_ENABLED_BASIS_LINE = (
    "  - basis: one sentence naming the work that would not have happened at "
    "all without an AI agent\n\n"
)

ArmEdit = namedtuple("ArmEdit", ["old", "new", "expected_count"])


class ArmSurgeryError(Exception):
    """An arm's text surgery did not match the real prompt as expected: the
    builder drifted, or the arm is unknown. Never swallowed."""


_PROMOTE_EDITS = (
    ArmEdit(TRAILER_CONFIDENCE_BULLET, "", 1),
    ArmEdit(PREAMBLE_ONLY_CLAUSE, PREAMBLE_ALWAYS_CLAUSE, 1),
    ArmEdit(MECHANISM_BULLET_TAIL,
            'or "newly_enabled_work"\n' + CONFIDENCE_LINE + "\n", 1),
)

_PER_BLOCK_EDITS = (
    ArmEdit(TRAILER_CONFIDENCE_BULLET, "", 1),
    ArmEdit(
        COUNTERFACTUAL_BASIS_LINE,
        COUNTERFACTUAL_BASIS_LINE[:-1] + CONFIDENCE_LINE + "\n", 2),
    ArmEdit(
        NEWLY_ENABLED_BASIS_LINE,
        NEWLY_ENABLED_BASIS_LINE[:-1] + CONFIDENCE_LINE + "\n", 1),
)

# Arm A0 has no text edits; its config transform removes `rateCard`
# (see `_arm_config`), which reproduces the pre-PR-#140 prompt.
#   B "promote"       M1, declaration scope
#   C "per-block"     M1, proximity
#   D "required"      M2: B plus a sentence that confidence is required
#   E "abstain-scope" M4: B plus a narrower abstention clause
ARM_EDITS = {
    "A0": (),
    "A1": (),
    "A2": (),
    "B": _PROMOTE_EDITS,
    "C": _PER_BLOCK_EDITS,
    "D": _PROMOTE_EDITS + (
        ArmEdit(TRAILER_CONFIDENCE_BULLET,
                TRAILER_CONFIDENCE_BULLET + REQUIRED_SENTENCE, 1),
    ),
    "E": _PROMOTE_EDITS + (
        ArmEdit(ABSTAIN_FIELD_CLAUSE, ABSTAIN_SCOPED_CLAUSE, 1),
    ),
}

GATE_ARMS = ("A0", "A1", "A2")
CANDIDATE_ARMS = ("B", "C", "D", "E")
# The tie-break's edit count: the number of ArmEdits per candidate arm.
EDIT_COUNT = {arm: len(ARM_EDITS[arm]) for arm in CANDIDATE_ARMS}

# ---------------------------------------------------------------------------
# The pre-registered protocol's constants. Never changed after plan 03's
# commit. Every cut is compared with ints or Fractions, never a float.
# ---------------------------------------------------------------------------
VALIDITY_MIN_RATE = Fraction(1, 10)
VALIDITY_MIN_REACHED = 30
SERVED_MODEL_MIN_SHARE = Fraction(19, 20)
NOISE_FLOOR_MIN = 3
NOISE_FLOOR_DIVISOR = 4
DECISION_MAX_RATIO = Fraction(1, 2)
ALPHA = Fraction(1, 20)
REACH_TOLERANCE_MIN = 3
REACH_TOLERANCE_DIVISOR = 10
CALIBRATION_MODAL_MAX = Fraction(4, 5)
DEFAULT_POOL_CAP = 300

OUTCOME_CLEARED_PREFIX = "CLEARED \u2014 arm "
OUTCOME_CLEARED_A1 = "CLEARED \u2014 arm A1, already deployed"
OUTCOME_NOT_CLEARED = "NOT CLEARED"
OUTCOME_NOT_EVALUATED = (
    "NOT EVALUATED \u2014 harness did not reproduce the omission")
# Exists so the record's vocabulary has one source. The harness never
# returns it: it is written by the operator path when spend is declined.
OUTCOME_NOT_RUN = "NOT RUN \u2014 spend declined"

# Whitelisted per-call record fields. Nothing else is ever persisted.
PER_CALL_RECORD_KEYS = frozenset({
    "arc", "arm", "stage", "outcome", "tokens", "valued", "has_key",
    "value_kind", "conf_value", "conf_like_key", "conf_in_text", "mechanism",
    "finish_reason", "completion_tokens", "served_model", "call_error", "ts",
})

# Production writers the harness must never reference. Checked by AST.
FORBIDDEN_WRITERS = frozenset({
    "_attach_assessment",
    "run_classification_async",
    "run_classification",
    "_write_job_marker",
    "_write_job_assessment",
    "_write_marker_pair",
    "_persist_job_type_to_taxonomy",
    "_persist_label_to_taxonomy",
})

OUTCOME_CLASSES = (
    "call_error",
    "timeout",
    "invalid",
    "abstain_null",
    "newly_enabled",
    "mechanism_rejected",
    "hours_rate_rejected",
    "confidence_omitted",
    "passed_confidence_gate",
)
_REACHED_CLASSES = ("confidence_omitted", "passed_confidence_gate")

_FINISH_REASONS = frozenset(
    {"stop", "length", "content_filter", "tool_calls", "unknown"})
_SERVED_MODEL_CLAMP = 64


# ---------------------------------------------------------------------------
# Arm surgery
# ---------------------------------------------------------------------------
def apply_arm(prompt, arm):
    """Return `prompt` with the arm's edits applied to its head.

    The head is the text before the first `TASK_ARC_BOUNDARY`; the tail (the
    job name and the transcript) is reattached byte for byte. Each edit
    asserts its declared occurrence count against the head as it stands at
    that edit, in the listed order. Any mismatch raises `ArmSurgeryError`.
    """
    if arm not in ARM_EDITS:
        raise ArmSurgeryError(f"unknown arm {arm!r}")
    head, sep, tail = prompt.partition(TASK_ARC_BOUNDARY)
    if not sep:
        raise ArmSurgeryError(
            "the task-arc boundary is absent from the prompt; the builder "
            "drifted")
    for index, edit in enumerate(ARM_EDITS[arm], start=1):
        found = head.count(edit.old)
        if found != edit.expected_count:
            raise ArmSurgeryError(
                f"arm {arm} edit {index}: expected {edit.expected_count} "
                f"occurrence(s) of the anchor in the instruction text, "
                f"found {found}")
        head = head.replace(edit.old, edit.new)
    return head + sep + tail


def numeric_tokens(text):
    """The set of numeric tokens in `text`."""
    return frozenset(re.findall(r"\d+(?:\.\d+)?", text))


def arc_key(agentic_job_id):
    """Opaque arc key: the first 16 hex characters of the id's sha256."""
    return hashlib.sha256(str(agentic_job_id).encode("utf-8")).hexdigest()[:16]


def _arm_config(cfg, arm):
    """The config an arm runs under. A0 is the prompt the glm-5.2-era arcs
    saw: the same config with `rateCard` removed (PA-1)."""
    base = cfg if isinstance(cfg, dict) else {}
    if arm == "A0":
        return {k: v for k, v in base.items() if k != "rateCard"}
    return base


# ---------------------------------------------------------------------------
# Loading the classifier
# ---------------------------------------------------------------------------
def load_plugin_package(plugin_dir, name="phase67_replay_pkg"):
    """Import the plugin package under a private name; return its classifier.

    The caller sets HERMES_HOME and REVENIUM_STATE_DIR before calling: the
    classifier binds its path constants at import. Cached `name*` modules are
    purged first so a second load never returns a classifier bound to an
    earlier environment.
    """
    plugin_dir = Path(plugin_dir)
    for cached in [m for m in sys.modules
                   if m == name or m.startswith(name + ".")]:
        del sys.modules[cached]
    spec = importlib.util.spec_from_file_location(
        name, str(plugin_dir / "__init__.py"),
        submodule_search_locations=[str(plugin_dir)])
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return sys.modules[name + ".classifier"]


# ---------------------------------------------------------------------------
# The per-call context and the production instrument
# ---------------------------------------------------------------------------
_CALL_CTX = contextvars.ContextVar("phase67_call_ctx")


class _InstrumentCapture(logging.Handler):
    """Maps each classifier log record's UNFORMATTED `record.msg` to a token
    and appends it to the current call's token list. It never calls
    `getMessage()`, so model output carried in `record.args` is never
    rendered. With no call context set it does nothing."""

    def emit(self, record):
        try:
            ctx = _CALL_CTX.get(None)
            if ctx is None:
                return
            msg = record.msg
            token = (VALIDATOR_TOKENS.get(msg, "other")
                     if isinstance(msg, str) else "other")
            ctx["tokens"].append(token)
        except Exception:
            pass


def _response_content(response):
    try:
        try:
            return response.choices[0].message.content
        except AttributeError:
            return response["choices"][0]["message"]["content"]
    except Exception:
        return None


def _response_completion_tokens(response):
    try:
        usage = getattr(response, "usage", None)
        if usage is None and isinstance(response, dict):
            usage = response.get("usage")
        value = getattr(usage, "completion_tokens", None)
        if value is None and isinstance(usage, dict):
            value = usage.get("completion_tokens")
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    except Exception:
        pass
    return None


def install_replay_hooks(c, real_call_llm, provider=REPLAY_PROVIDER,
                         model=REPLAY_MODEL):
    """Install the arm-aware builder and the model-pinning `call_llm` on the
    classifier module `c`. Idempotent; undo with `restore_replay_hooks`.

    `real_call_llm` is called with exactly the kwargs production passes, plus
    `provider` and `model`. A raised exception is recorded and re-raised, so
    production's own `except` path decides what it means.
    """
    log = c.logger
    # The logger is a process-wide singleton shared by every loaded copy of
    # the classifier, so its saved state lives on the logger itself.
    if not hasattr(log, "_phase67_saved_propagate"):
        log._phase67_saved_propagate = log.propagate
    # Validator records must not reach a root file handler: the host's
    # agent.log is Phase 70's grep target.
    log.propagate = False
    if not any(isinstance(h, _InstrumentCapture) for h in log.handlers):
        log.addHandler(_InstrumentCapture())

    if not hasattr(c, "_phase67_original_builder"):
        c._phase67_original_builder = c._build_outcome_evaluation_prompt
    original = c._phase67_original_builder

    def _arm_builder(job, transcript, config):
        prompt = original(job, transcript, config)
        ctx = _CALL_CTX.get(None)
        if ctx is None:
            # Outside a replay call this is production's builder.
            return prompt
        return apply_arm(prompt, ctx["arm"])

    c._build_outcome_evaluation_prompt = _arm_builder

    if not hasattr(c, "_phase67_original_call_llm"):
        c._phase67_original_call_llm = c.call_llm

    def pinned(**kw):
        ctx = _CALL_CTX.get(None)
        diag = ctx["diag"] if ctx is not None else {}
        try:
            response = real_call_llm(provider=provider, model=model, **kw)
        except Exception:
            diag["call_error"] = True
            raise
        diag["finish_reason"] = c._resolve_finish_reason(response)
        diag["served_model"] = str(
            c._resolve_served_model(response))[:_SERVED_MODEL_CLAMP]
        diag["completion_tokens"] = _response_completion_tokens(response)
        content = _response_content(response)
        diag["conf_in_text"] = (
            isinstance(content, str) and "confidence" in content.lower())
        return response

    c.call_llm = pinned


def restore_replay_hooks(c):
    """Undo `install_replay_hooks`: module globals, the handler, and the
    logger's `propagate`. Safe to call when nothing is installed."""
    if hasattr(c, "_phase67_original_builder"):
        c._build_outcome_evaluation_prompt = c._phase67_original_builder
        del c._phase67_original_builder
    if hasattr(c, "_phase67_original_call_llm"):
        c.call_llm = c._phase67_original_call_llm
        del c._phase67_original_call_llm
    log = c.logger
    for handler in list(log.handlers):
        if isinstance(handler, _InstrumentCapture):
            log.removeHandler(handler)
    if hasattr(log, "_phase67_saved_propagate"):
        log.propagate = log._phase67_saved_propagate
        del log._phase67_saved_propagate


# ---------------------------------------------------------------------------
# One replay call
# ---------------------------------------------------------------------------
def _value_kind(raw):
    if not isinstance(raw, dict) or "confidence" not in raw:
        return "absent"
    value = raw["confidence"]
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    return "other"


def _conf_like_key(raw):
    if not isinstance(raw, dict):
        return False
    return any(isinstance(k, str) and k != "confidence" and "conf" in k.lower()
               for k in raw)


def _mechanism_label(c, raw):
    if not isinstance(raw, dict) or "economic_mechanism" not in raw:
        return "none"
    value = raw["economic_mechanism"]
    if isinstance(value, str) and value in c.ECONOMIC_MECHANISMS:
        return value
    return "other"


def _finish_reason_label(value):
    if value is None:
        return "unknown"
    if isinstance(value, str) and value in _FINISH_REASONS:
        return value
    return "other"


def _stage_label(stage):
    if isinstance(stage, int) and not isinstance(stage, bool):
        return stage
    return str(stage)[:16]


def _record(c, job, arm, stage, outcome, ctx, raw, valued, served_model):
    diag = ctx["diag"]
    conf_value = None
    if isinstance(raw, dict):
        conf_value = c._finite_number(raw.get("confidence"))
    return {
        "arc": arc_key((job or {}).get("agentic_job_id", "")),
        "arm": arm,
        "stage": _stage_label(stage),
        "outcome": outcome,
        "tokens": list(ctx["tokens"]),
        "valued": bool(valued),
        "has_key": isinstance(raw, dict) and "confidence" in raw,
        "value_kind": _value_kind(raw),
        "conf_value": conf_value,
        "conf_like_key": _conf_like_key(raw),
        "conf_in_text": bool(diag.get("conf_in_text", False)),
        "mechanism": _mechanism_label(c, raw),
        "finish_reason": _finish_reason_label(diag.get("finish_reason")),
        "completion_tokens": diag.get("completion_tokens"),
        "served_model": served_model,
        "call_error": bool(diag.get("call_error", False)),
        "ts": int(time.time()),
    }


async def replay_call(c, job, transcript, cfg, arm, stage, evaluator_version):
    """Replay one (arc, arm) through production's own call path and return a
    whitelisted record.

    The branch order mirrors `_attach_assessment`: pop the served-model
    carrier, then invalid, timed-out, null, `newly_enabled_work`, and only
    then the validator. An exception from the validator is deliberately not
    caught: a validator that raises is a defect to see, and swallowing it
    would shape the measurement.
    """
    arm_cfg = _arm_config(cfg, arm)
    ctx = {"arm": arm, "tokens": [], "diag": {}}
    token = _CALL_CTX.set(ctx)
    try:
        raw = await c._evaluate_outcome_via_llm(job, transcript, arm_cfg)
        served_model = None
        if isinstance(raw, dict):
            carrier = raw.pop(c._SERVED_MODEL_KEY, None)
            if isinstance(carrier, c._ServedModel):
                served_model = str(carrier.value)[:_SERVED_MODEL_CLAMP]
        if served_model is None:
            served_model = ctx["diag"].get("served_model")
        valued = False
        if raw is c._EVAL_INVALID:
            outcome = "invalid"
        elif raw is c._EVAL_TIMED_OUT:
            outcome = "timeout"
        elif raw is None:
            outcome = ("call_error" if ctx["diag"].get("call_error")
                       else "abstain_null")
        elif (c._resolve_economic_mechanism(raw)
                == c.ECONOMIC_MECHANISM_NEWLY_ENABLED_WORK):
            outcome = "newly_enabled"
        else:
            mark = len(ctx["tokens"])
            result = c._validate_assessment(
                raw, arm_cfg, "llm", evaluator_version)
            first = (ctx["tokens"][mark:mark + 1] or [None])[0]
            if first == "confidence_omitted":
                outcome = "confidence_omitted"
            elif first == "mechanism_rejected":
                outcome = "mechanism_rejected"
            elif first in ("hours_rate_nonnumeric", "bound_exceeded"):
                outcome = "hours_rate_rejected"
            else:
                outcome = "passed_confidence_gate"
                valued = bool(result)
        return _record(c, job, arm, stage, outcome, ctx, raw, valued,
                       served_model)
    finally:
        _CALL_CTX.reset(token)


async def run_calls(c, calls, concurrency, evaluator_version, on_start=None):
    """Run `calls`, a list of `(job, transcript, cfg, arm, stage)`, with at
    most `concurrency` in flight. Returns the records in call order.
    `on_start(index)` runs just before call `index` reaches the model."""
    semaphore = asyncio.Semaphore(max(1, int(concurrency)))

    async def one(index, spec):
        job, transcript, cfg, arm, stage = spec
        async with semaphore:
            if on_start is not None:
                on_start(index)
            return await replay_call(
                c, job, transcript, cfg, arm, stage, evaluator_version)

    return list(await asyncio.gather(
        *(one(index, spec) for index, spec in enumerate(calls))))


# ---------------------------------------------------------------------------
# Records and aggregation
# ---------------------------------------------------------------------------
def append_record(path, record):
    """Append one whitelisted record to a JSONL file. A key outside
    `PER_CALL_RECORD_KEYS` is refused before anything is written."""
    extra = sorted(set(record) - PER_CALL_RECORD_KEYS)
    if extra:
        raise ValueError(f"record keys outside the whitelist: {extra}")
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")


def read_records(path):
    """Read a JSONL records file back, skipping blank lines."""
    out = []
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def aggregate(records):
    """Per-arm counts by outcome class, plus reached, omitted and valued.

    Denominators come only from the outcome classes the production branch
    order produces. No record is ever dropped.
    """
    arms = {}
    for rec in records:
        slot = arms.setdefault(rec["arm"], {
            "counts": {name: 0 for name in OUTCOME_CLASSES},
            "reached": 0, "omitted": 0, "valued": 0, "total": 0,
        })
        slot["counts"][rec["outcome"]] += 1
        slot["total"] += 1
        if rec["outcome"] in _REACHED_CLASSES:
            slot["reached"] += 1
        if rec["outcome"] == "confidence_omitted":
            slot["omitted"] += 1
        if rec["outcome"] == "passed_confidence_gate" and rec["valued"]:
            slot["valued"] += 1
    return arms


# ---------------------------------------------------------------------------
# Exact statistics
# ---------------------------------------------------------------------------
def mcnemar_one_sided_p(b, c):
    """Exact one-sided McNemar p for `b` arcs omitted in the baseline only and
    `c` omitted in the candidate only: the binomial tail P(X <= c) with
    n = b + c and p = 1/2, as an exact Fraction. No discordant pairs gives 1.
    """
    n = b + c
    if n == 0:
        return Fraction(1)
    return Fraction(sum(math.comb(n, i) for i in range(c + 1)), 2 ** n)


def wilson_interval(k, n, z=1.959963984540054):
    """Wilson score interval for k of n. REPORTING ONLY: floats, never an
    input to a decision. (0.0, 0.0) when n is 0."""
    if n == 0:
        return (0.0, 0.0)
    phat = k / n
    denom = 1 + z * z / n
    center = (phat + z * z / (2 * n)) / denom
    half = z * math.sqrt(phat * (1 - phat) / n + z * z / (4 * n * n)) / denom
    low = 0.0 if k == 0 else max(0.0, center - half)
    high = 1.0 if k == n else min(1.0, center + half)
    return (low, high)


def calibration(values):
    """n, distinct values, the modal value's count, and the mean."""
    n = len(values)
    if n == 0:
        return {"n": 0, "distinct": 0, "modal_count": 0, "mean": None}
    counts = Counter(values)
    return {
        "n": n,
        "distinct": len(counts),
        "modal_count": max(counts.values()),
        "mean": sum(values) / n,
    }


def modal_share(values):
    """The modal value's share as an exact Fraction, or None for no values
    (which the calibration guard treats as a pass)."""
    if not values:
        return None
    return Fraction(max(Counter(values).values()), len(values))


# ---------------------------------------------------------------------------
# The pre-registered gates and decision rule
# ---------------------------------------------------------------------------
class IncompleteStageError(Exception):
    """A stage lacks a record for some pool arc. The protocol never judges a
    stage it only partly has."""


class ServedModelError(Exception):
    """A stage-2 arm (A1 or a candidate) has a served-model share below
    SERVED_MODEL_MIN_SHARE. Not a ValueError, so the callers' existing except
    tuples never swallow it. `arm` names the arm that fell short."""

    def __init__(self, arm):
        super().__init__(
            f"arm {arm}: served-model share below the required share")
        self.arm = arm


class DuplicateRecordError(ValueError):
    """More than one record for one (arc, arm). Counting both would shape the
    measurement, so the evaluator refuses."""


def _views(records, arms):
    """arm -> {arc: record} for the requested arms. Other arms are ignored."""
    views = {arm: {} for arm in arms}
    for rec in records:
        view = views.get(rec["arm"])
        if view is None:
            continue
        if rec["arc"] in view:
            raise DuplicateRecordError(
                f"arm {rec['arm']}: more than one record for one arc")
        view[rec["arc"]] = rec
    return views


def _check_complete(views, pool, arms):
    for arm in arms:
        stray = set(views[arm]) - pool
        if stray:
            raise ValueError(
                f"arm {arm}: {len(stray)} record(s) for arcs outside the pool")
        missing = len(pool) - len(views[arm])
        if missing:
            raise IncompleteStageError(
                f"arm {arm}: {missing} of {len(pool)} pool arc(s) have no "
                f"record")


def _arm_sets(view):
    """(reached, omitted) arc sets for one arm's {arc: record} view."""
    reached = frozenset(
        arc for arc, rec in view.items()
        if rec["outcome"] in _REACHED_CLASSES)
    omitted = frozenset(
        arc for arc, rec in view.items()
        if rec["outcome"] == "confidence_omitted")
    return reached, omitted


def _served_model_holds(records, expected_model):
    """Whether the calls that got a response were served by `expected_model`
    at SERVED_MODEL_MIN_SHARE or better. A match is a prefix match, so a
    variant suffix still counts. Calls with no response are not in the
    denominator, and no response at all cannot pass. G0 and the per-arm
    stage-2 check both come through here so they cannot drift apart."""
    responded = [rec for rec in records
                 if rec.get("served_model") is not None]
    matched = sum(
        1 for rec in responded
        if rec["served_model"].startswith(expected_model))
    return (len(responded) > 0
            and Fraction(matched, len(responded)) >= SERVED_MODEL_MIN_SHARE)


def _gate_values(views, expected_model=REPLAY_MODEL):
    r0, o0 = _arm_sets(views["A0"])
    r1, o1 = _arm_sets(views["A1"])
    r2, o2 = _arm_sets(views["A2"])
    g0 = _served_model_holds(
        [rec for arm in GATE_ARMS for rec in views[arm].values()],
        expected_model)
    g1 = (len(r0) >= VALIDITY_MIN_REACHED
          and Fraction(len(o0), len(r0)) >= VALIDITY_MIN_RATE)
    g2 = (abs(len(o1) - len(o2))
          <= max(NOISE_FLOOR_MIN, len(o1) // NOISE_FLOOR_DIVISOR))
    g3 = (len(r1) >= VALIDITY_MIN_REACHED
          and Fraction(len(o1), len(r1)) >= VALIDITY_MIN_RATE)
    return {
        "G0": g0, "G1": g1, "G2": g2, "G3": g3,
        "valid": g0 and g2 and (g1 or g3),
        "stage2_eligible": g0 and g2 and g3,
        "reasons": [name for name, ok in
                    (("G0", g0), ("G1", g1), ("G2", g2), ("G3", g3))
                    if not ok],
    }


def evaluate_gates(records, pool_keys, expected_model=REPLAY_MODEL):
    """The validity gates, from the stage-1 records (A0, A1, A2) alone.
    `expected_model` is the model G0 expects to have served the calls.

    Raises IncompleteStageError when any pool arc lacks a record for any
    stage-1 arm.
    """
    pool = frozenset(pool_keys)
    views = _views(records, GATE_ARMS)
    _check_complete(views, pool, GATE_ARMS)
    return _gate_values(views, expected_model)


def _supplied_confidences(view):
    return [rec["conf_value"] for rec in view.values()
            if rec["outcome"] == "passed_confidence_gate"
            and rec.get("conf_value") is not None]


def clears(records, x_arm, base_arm):
    """Whether arm `x_arm` clears against `base_arm` on all four criteria.

    Returns a dict: `crit_a` (at most half the baseline rate, by
    cross-multiplication), `crit_b` (exact one-sided McNemar p < ALPHA over
    arcs that reached in both arms), `crit_c` (reach guard), `crit_d`
    (calibration guard), `clears` (all four), the discordant counts `b`
    (omitted in the base only) and `c` (omitted in `x_arm` only), and the
    exact Fraction `p`.

    The calibration guard disqualifies a candidate whose modal confidence
    share is above CALIBRATION_MODAL_MAX unless the baseline's is too. A
    baseline that supplied no confidence at all is not above it.
    """
    views = _views(records, (x_arm, base_arm))
    vx, vb = views[x_arm], views[base_arm]
    rx, ox = _arm_sets(vx)
    rb, ob = _arm_sets(vb)

    crit_a = (DECISION_MAX_RATIO.denominator * len(ox) * len(rb)
              <= DECISION_MAX_RATIO.numerator * len(ob) * len(rx))

    both = rx & rb
    b = len((ob & both) - ox)
    c = len((ox & both) - ob)
    p = mcnemar_one_sided_p(b, c)
    crit_b = p < ALPHA

    crit_c = len(rx) >= len(rb) - max(
        REACH_TOLERANCE_MIN, len(rb) // REACH_TOLERANCE_DIVISOR)

    share_x = modal_share(_supplied_confidences(vx))
    share_base = modal_share(_supplied_confidences(vb))
    x_flat = share_x is not None and share_x > CALIBRATION_MODAL_MAX
    base_flat = share_base is not None and share_base > CALIBRATION_MODAL_MAX
    crit_d = (not x_flat) or base_flat

    return {
        "crit_a": crit_a, "crit_b": crit_b, "crit_c": crit_c,
        "crit_d": crit_d,
        "clears": crit_a and crit_b and crit_c and crit_d,
        "b": b, "c": c, "p": p,
    }


def _tie_break_key(view, arm):
    reached, omitted = _arm_sets(view)
    rate = Fraction(len(omitted), len(reached)) if reached else Fraction(1)
    return (rate, EDIT_COUNT[arm], CANDIDATE_ARMS.index(arm))


def evaluate_protocol(records, pool_keys, expected_model=REPLAY_MODEL):
    """Apply the pre-registered protocol to `records` over `pool_keys`.

    The outcome is one of four strings, as a function of the data: a clear
    candidate (`CLEARED \u2014 arm X`), A1 already deployed, NOT CLEARED, or
    NOT EVALUATED when the gates fail. Raises IncompleteStageError rather than
    judging a stage that lacks a record for any pool arc. Candidate arms are
    read only when stage 2 is eligible.

    When stage 2 is eligible, A1 and each candidate arm must also meet the
    served-model share on its own, or ServedModelError names the first arm
    that does not. That check extends G0 past the pre-registered text and can
    only refuse a result, never produce a winner.
    """
    pool = frozenset(pool_keys)
    gates = evaluate_gates(records, pool, expected_model)
    eligible = gates["stage2_eligible"]
    arms = GATE_ARMS + (CANDIDATE_ARMS if eligible else ())
    views = _views(records, arms)
    if eligible:
        _check_complete(views, pool, CANDIDATE_ARMS)
        # A1 is the base of every stage-2 comparison. Pooled G0 lets one arm
        # fall well below the share (all the off-model calls in A1), so a
        # candidate could beat a mixed-model base. The G1-only path (A1
        # against A0) stays on pooled G0 as pre-registered: it is the path
        # the recorded run took, and it never reads a candidate arm.
        for arm in ("A1",) + CANDIDATE_ARMS:
            if not _served_model_holds(views[arm].values(), expected_model):
                raise ServedModelError(arm)

    raw_comparisons = {}
    if eligible:
        for arm in CANDIDATE_ARMS:
            raw_comparisons[arm] = clears(records, arm, "A1")
    raw_diag = clears(records, "A1", "A0")

    winner = None
    if not gates["valid"]:
        outcome = OUTCOME_NOT_EVALUATED
    elif gates["G3"]:
        clearing = [arm for arm in CANDIDATE_ARMS
                    if raw_comparisons[arm]["clears"]]
        if clearing:
            winner = min(clearing,
                         key=lambda arm: _tie_break_key(views[arm], arm))
            outcome = OUTCOME_CLEARED_PREFIX + winner
        else:
            outcome = OUTCOME_NOT_CLEARED
    elif raw_diag["clears"]:
        winner = "A1"
        outcome = OUTCOME_CLEARED_A1
    else:
        outcome = OUTCOME_NOT_CLEARED

    return {
        "arms": {arm: _arm_report(views[arm]) for arm in arms},
        "gates": gates,
        "comparisons": {arm: _comparison_report(res)
                        for arm, res in raw_comparisons.items()},
        "diagnostic_a0_a1": _comparison_report(raw_diag),
        "m0": _m0_report(views, arms),
        "calibration": {arm: _calibration_report(views[arm]) for arm in arms},
        "outcome": outcome,
        "winner": winner,
    }


# ---------------------------------------------------------------------------
# Reporting helpers. Display floats live here, never in a decision function.
# ---------------------------------------------------------------------------
def _fraction_text(value):
    return f"{value.numerator}/{value.denominator}"


def _arm_report(view):
    reached, omitted = _arm_sets(view)
    agg = aggregate(list(view.values()))
    slot = next(iter(agg.values()))
    k, n = len(omitted), len(reached)
    return {
        "counts": slot["counts"],
        "total": slot["total"],
        "reached": n,
        "omitted": k,
        "valued": slot["valued"],
        "rate": f"{k}/{n}",
        "rate_exact": Fraction(k, n) if n else None,
        "wilson": list(wilson_interval(k, n)),
    }


def _comparison_report(res):
    return {
        "criteria": {"a": res["crit_a"], "b": res["crit_b"],
                     "c": res["crit_c"], "d": res["crit_d"]},
        "clears": res["clears"],
        "b": res["b"],
        "c": res["c"],
        "p": _fraction_text(res["p"]),
        "p_exact": res["p"],
        "p_float": float(res["p"]),
    }


def _calibration_report(view):
    values = _supplied_confidences(view)
    out = calibration(values)
    share = modal_share(values)
    out["modal_share"] = _fraction_text(share) if share is not None else None
    out["modal_share_exact"] = share
    return out


def _m0_report(views, arms):
    """Aggregates over the omitted responses, to say what an omission looks
    like (M0): a null, a renamed key, text outside the JSON, a truncation."""
    omitted = [rec for arm in arms for rec in views[arm].values()
               if rec["outcome"] == "confidence_omitted"]
    tokens = [rec["completion_tokens"] for rec in omitted
              if isinstance(rec.get("completion_tokens"), int)]
    return {
        "n": len(omitted),
        "value_kind": dict(Counter(rec["value_kind"] for rec in omitted)),
        "conf_like_key": sum(1 for rec in omitted if rec["conf_like_key"]),
        "conf_in_text": sum(1 for rec in omitted if rec["conf_in_text"]),
        "finish_reason": dict(Counter(rec["finish_reason"] for rec in omitted)),
        "median_completion_tokens": (
            statistics.median(tokens) if tokens else None),
    }


def _jsonable(value):
    if isinstance(value, Fraction):
        return _fraction_text(value)
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


def report_to_json(report):
    """The report as JSON text, with every Fraction rendered as `k/n`."""
    return json.dumps(_jsonable(report), indent=2, sort_keys=True,
                      ensure_ascii=False)


# ---------------------------------------------------------------------------
# Host plumbing (plan 03): the pool, the side-effect fence and the CLI.
#
# Everything below reads the host's state and writes only under `--out-dir`,
# which must resolve outside `--hermes-home`. `state.db` is opened with
# `mode=ro`. Identifier-bearing data (job ids, job names, session ids) lives
# only in `pool.json` (mode 0600) and `fence-snapshot.json` (arc keys only).
# Everything printed, and `census.json`, `calls.jsonl` and `report.json`, hold
# counts and opaque arc keys. `run-model.json` holds only the provider and
# model names the run is bound to.
# ---------------------------------------------------------------------------
HostPaths = namedtuple("HostPaths", [
    "hermes_home", "state_dir", "sidecar_dir", "markers_dir", "state_db",
    "logs_dir", "config_json", "hermes_ledger", "jobs_ledger",
    "tool_events_ledger",
])

# Overrides the classifier honours at import. They are cleared while the host's
# classifier is loaded so every path derives from `--hermes-home`.
_PATH_ENV_OVERRIDES = (
    "REVENIUM_MARKERS_DIR", "REVENIUM_MARKERS_READY_DIR",
    "REVENIUM_TAXONOMY_FILE", "REVENIUM_JOB_TAXONOMY_FILE",
    "REVENIUM_JOB_ASSESSMENTS_DIR", "REVENIUM_CONFIG_FILE",
)

EXCLUSION_STEPS = (
    "not_sequence_0", "duplicate_arc", "not_success", "wrong_model",
    "no_success_marker", "no_transcript", "transcript_drift",
)
POOL_ENTRY_KEYS = ("arc", "agentic_job_id", "sid", "job_name", "job_type",
                   "ts", "transcript_sha256")
RUN_MODEL_FILE = "run-model.json"
ATTEMPTS_FILE = "attempts.jsonl"
FENCE_CHECKS = ("sidecar_marker_lines", "ledger_lines",
                "state_db_model_rows", "agent_log_instrument")
INSTRUMENT_NEEDLE = "rejected assessment, confidence outside [0,1]"
SMOKE_ARM = "A1"
SMOKE_STAGE = "smoke"
STAGE_NUMBER = {"gate": 1, "candidates": 2}
STAGE_ARMS = {"gate": GATE_ARMS, "candidates": CANDIDATE_ARMS}

EXIT_OK = 0
EXIT_FENCE = 1
EXIT_USAGE = 2
EXIT_BUDGET = 3
EXIT_STAGE = 4
EXIT_TIMESTAMP = 5
EXIT_NO_CALLABLE = 6
EXIT_DRIFT = 7

# A plausible range for `messages.timestamp` in epoch seconds (1973 to 5138).
_EPOCH_MIN = 10 ** 8
_EPOCH_MAX = 10 ** 11

_SID_TOKEN_RE = re.compile(r"^\d{4}-\d{2}-\d{2} \S+ [A-Z]+ \[([^\]]+)\] ")
_LOG_TIME_RE = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")


class TimestampUnitError(Exception):
    """`messages.timestamp` is not plain epoch seconds; the drift test would
    be a guess, so the census stops."""


class TimestampReadError(Exception):
    """`state.db` could not be opened or its `messages` query failed. A failed
    read must not pass as "no drift", so the census stops."""


def host_paths(hermes_home):
    home = Path(hermes_home).expanduser()
    state = home / "state" / "revenium"
    return HostPaths(
        hermes_home=home, state_dir=state,
        sidecar_dir=state / "job-assessments", markers_dir=state / "markers",
        state_db=home / "state.db", logs_dir=home / "logs",
        config_json=state / "config.json",
        hermes_ledger=state / "revenium-hermes.ledger",
        jobs_ledger=state / "revenium-jobs.ledger",
        tool_events_ledger=state / "revenium-tool-events.ledger")


def _ro_connect(db_path):
    """Open `state.db` read-only. `mode=ro` means a missing file raises
    rather than being created."""
    uri = "file:" + urllib.parse.quote(str(db_path), safe="/") + "?mode=ro"
    return sqlite3.connect(uri, uri=True, timeout=2.0)


def _iter_jsonl(path):
    """Yield `(dict_or_None)` per non-blank line; None marks a malformed
    line. A missing or unreadable file yields nothing."""
    try:
        handle = open(path, encoding="utf-8", errors="replace")
    except OSError:
        return
    with handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                value = json.loads(line)
            except ValueError:
                yield None
                continue
            yield value if isinstance(value, dict) else None


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _read_sidecar_records(paths):
    records, malformed = [], 0
    for path in sorted(paths.sidecar_dir.glob("*.jsonl")):
        for rec in _iter_jsonl(path):
            if rec is None:
                malformed += 1
            elif (rec.get("kind") == "job_assessment"
                    and isinstance(rec.get("agentic_job_id"), str)):
                records.append(rec)
    return records, malformed


def _read_job_markers(paths):
    """job id -> the latest `kind: job` marker (by `ts`)."""
    latest = {}
    for path in sorted(paths.markers_dir.glob("*.jsonl")):
        for rec in _iter_jsonl(path):
            if (rec is None or rec.get("kind") != "job"
                    or not isinstance(rec.get("agentic_job_id"), str)):
                continue
            ts = rec.get("ts") if _is_number(rec.get("ts")) else 0
            prior = latest.get(rec["agentic_job_id"])
            if prior is None or ts >= prior[0]:
                latest[rec["agentic_job_id"]] = (ts, rec)
    return {job: pair[1] for job, pair in latest.items()}


def _message_stamps(conn, sid):
    """`(max_numeric_timestamp_or_None, any_unusable)` for one session."""
    try:
        rows = conn.execute(
            "SELECT timestamp, typeof(timestamp) FROM messages "
            "WHERE session_id = ?", (sid,)).fetchall()
    except sqlite3.Error:
        raise TimestampReadError("messages query failed") from None
    best, unusable = None, False
    for value, kind in rows:
        if kind == "null":
            continue
        if (kind not in ("integer", "real")
                or not (_EPOCH_MIN < value < _EPOCH_MAX)):
            unusable = True
            continue
        best = value if best is None else max(best, value)
    return best, unusable


def build_pool(paths, c, cap):
    """Select the eligible arcs. Returns `(pool, counts)`.

    An arc is eligible when its sidecar record has sequence 0, execution
    status SUCCESS and model exactly `REPLAY_MODEL`; a `kind: job` marker for
    the same job id has status SUCCESS; `_read_session_transcript` returns a
    non-empty transcript; and no message in the session is later than the
    sidecar record's `ts`. Each exclusion is counted once, at the first rule
    that rejects the arc. With a cap, the most recent arcs by sidecar `ts` are
    kept, then sorted ascending. Each entry carries the sha256 of the
    transcript the non-empty check read, so a later stage can tell whether the
    session changed. Raises TimestampReadError when `state.db` cannot be
    opened or queried.
    """
    records, malformed = _read_sidecar_records(paths)
    markers = _read_job_markers(paths)
    counts = {step: 0 for step in EXCLUSION_STEPS}
    counts["records_read"] = len(records)
    counts["malformed_lines"] = malformed
    seen = set()
    eligible = []
    conn = None
    unit_seen = False
    try:
        try:
            conn = _ro_connect(paths.state_db)
        except sqlite3.Error:
            raise TimestampReadError("state.db cannot be opened") from None
        for rec in records:
            job_id = rec["agentic_job_id"]
            if rec.get("sequence") != 0 or isinstance(
                    rec.get("sequence"), bool):
                counts["not_sequence_0"] += 1
                continue
            if job_id in seen:
                counts["duplicate_arc"] += 1
                continue
            seen.add(job_id)
            if rec.get("execution_status") != "SUCCESS":
                counts["not_success"] += 1
                continue
            if rec.get("model") != REPLAY_MODEL:
                counts["wrong_model"] += 1
                continue
            marker = markers.get(job_id)
            if (marker is None or marker.get("status") != "SUCCESS"
                    or not isinstance(marker.get("sid"), str)
                    or not marker["sid"]):
                counts["no_success_marker"] += 1
                continue
            sid = marker["sid"]
            transcript = c._read_session_transcript(sid)
            if not transcript:
                counts["no_transcript"] += 1
                continue
            newest, unusable = _message_stamps(conn, sid)
            if unusable:
                raise TimestampUnitError("messages.timestamp is not epoch "
                                         "seconds")
            if newest is not None:
                unit_seen = True
            ts = rec.get("ts")
            if (not _is_number(ts)
                    or (newest is not None and newest > ts)):
                counts["transcript_drift"] += 1
                continue
            eligible.append({
                "arc": arc_key(job_id), "agentic_job_id": job_id,
                "sid": sid, "job_name": str(marker.get("job_name", "")),
                "job_type": str(marker.get("job_type", "")), "ts": ts,
                "transcript_sha256": hashlib.sha256(
                    transcript.encode("utf-8")).hexdigest()})
    finally:
        if conn is not None:
            conn.close()
    counts["eligible"] = len(eligible)
    counts["pool_cap"] = cap
    counts["timestamp_unit"] = "epoch_seconds" if unit_seen else "unobserved"
    eligible.sort(key=lambda e: (e["ts"], e["arc"]))
    pool = eligible[-cap:] if cap and cap > 0 else []
    pool.sort(key=lambda e: (e["ts"], e["arc"]))
    return pool, counts


# -- private files ----------------------------------------------------------
def _write_private_json(path, value):
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            fd = None
            json.dump(value, handle, sort_keys=True)
    finally:
        if fd is not None:
            os.close(fd)


def _write_json(path, value):
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write("\n")


def _sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


# -- the side-effect fence --------------------------------------------------
def _sidecar_component(job_id):
    """Mirror of the classifier's sidecar filename rule (duplicated on
    purpose: the fence never loads the classifier)."""
    if not isinstance(job_id, str):
        return "_"
    value = job_id
    for bad in (":", " ", "\t", "\n", "\r"):
        value = value.replace(bad, "_")
    value = re.sub(r"[^A-Za-z0-9._-]", "_", value)
    return "_" if value in ("", ".", "..") else value


def _file_size(path):
    try:
        return os.stat(path).st_size
    except OSError:
        return 0


def _read_from(path, offset):
    try:
        with open(path, "rb") as handle:
            handle.seek(max(0, int(offset)))
            return handle.read().decode("utf-8", errors="replace")
    except OSError:
        return ""


def _model_row_count(paths):
    try:
        conn = _ro_connect(paths.state_db)
    except sqlite3.Error:
        return 0
    try:
        return conn.execute(
            "SELECT COUNT(*) FROM sessions WHERE model = ?",
            (REPLAY_MODEL,)).fetchone()[0]
    except sqlite3.Error:
        return 0
    finally:
        conn.close()


def _agent_log_stat(paths):
    try:
        st = os.stat(paths.logs_dir / "agent.log")
    except OSError:
        return {"inode": None, "size": 0}
    return {"inode": st.st_ino, "size": st.st_size}


def _ledger_files(paths):
    return {"hermes": paths.hermes_ledger, "jobs": paths.jobs_ledger,
            "tool_events": paths.tool_events_ledger}


def _sidecar_path(paths, entry):
    return paths.sidecar_dir / (_sidecar_component(entry["agentic_job_id"])
                                + ".jsonl")


def _marker_path(paths, entry):
    return paths.markers_dir / (entry["sid"] + ".jsonl")


def fence_snapshot(paths, pool):
    """Sizes only, keyed by opaque arc key: no identifier is stored."""
    return {
        "taken_at": int(time.time()),
        "sidecar": {e["arc"]: _file_size(_sidecar_path(paths, e))
                    for e in pool},
        "markers": {e["arc"]: _file_size(_marker_path(paths, e))
                    for e in pool},
        "ledgers": {name: _file_size(path)
                    for name, path in _ledger_files(paths).items()},
        "model_rows": _model_row_count(paths),
        "agent_log": _agent_log_stat(paths),
    }


def _agent_log_new_text(paths, before):
    prior = before.get("agent_log") or {}
    log = paths.logs_dir / "agent.log"
    try:
        st = os.stat(log)
    except OSError:
        st = None
    offset = prior.get("size", 0)
    if (st is not None and st.st_ino == prior.get("inode")
            and st.st_size >= offset):
        return _read_from(log, offset)
    chunks = []
    if st is None or st.st_ino != prior.get("inode"):
        # Rotated: the file we snapshotted is now agent.log.1.
        chunks.append(_read_from(paths.logs_dir / "agent.log.1", offset))
    if st is not None:
        chunks.append(_read_from(log, 0))
    return "".join(chunks)


def _log_line_epoch(line):
    match = _LOG_TIME_RE.match(line)
    if not match:
        return None
    try:
        return time.mktime(time.strptime(match.group(1), "%Y-%m-%d %H:%M:%S"))
    except (ValueError, OverflowError):
        return None


def fence_check(paths, pool, before, since_epoch=None):
    """Four read-only checks against the snapshot. Returns a dict of check
    name to violation count. Counts only, never an identifier."""
    ids = sorted({e["agentic_job_id"] for e in pool}
                 | {e["sid"] for e in pool})
    pattern = (re.compile("|".join(re.escape(i) for i in ids))
               if ids else None)
    pool_sids = {e["sid"] for e in pool}

    first = 0
    for entry in pool:
        for path, key in ((_sidecar_path(paths, entry), "sidecar"),
                          (_marker_path(paths, entry), "markers")):
            appended = _read_from(path, (before.get(key) or {}).get(
                entry["arc"], 0))
            for line in appended.splitlines():
                if entry["agentic_job_id"] in line:
                    first += 1

    second = 0
    for name, path in _ledger_files(paths).items():
        appended = _read_from(path, (before.get("ledgers") or {}).get(name, 0))
        if pattern is None:
            continue
        for line in appended.splitlines():
            if pattern.search(line):
                second += 1

    third = abs(_model_row_count(paths) - before.get("model_rows", 0))

    fourth = 0
    horizon = since_epoch if since_epoch is not None else before.get(
        "taken_at")
    for line in _agent_log_new_text(paths, before).splitlines():
        if INSTRUMENT_NEEDLE not in line:
            continue
        stamp = _log_line_epoch(line)
        if horizon is not None and stamp is not None and stamp < horizon:
            continue
        match = _SID_TOKEN_RE.match(line)
        if match is None or match.group(1) in pool_sids:
            fourth += 1

    return {"sidecar_marker_lines": first, "ledger_lines": second,
            "state_db_model_rows": third, "agent_log_instrument": fourth}


# -- loading the host's classifier and the model callable -------------------
@contextlib.contextmanager
def _host_env(home):
    paths = host_paths(home)
    keys = ("HERMES_HOME", "REVENIUM_STATE_DIR") + _PATH_ENV_OVERRIDES
    saved = {k: os.environ.get(k) for k in keys}
    for key in _PATH_ENV_OVERRIDES:
        os.environ.pop(key, None)
    os.environ["HERMES_HOME"] = str(paths.hermes_home)
    os.environ["REVENIUM_STATE_DIR"] = str(paths.state_dir)
    try:
        yield paths
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def resolve_call_llm(hermes_agent_dir):
    """Import Hermes' `call_llm` from `hermes_agent_dir`, or None. Never
    called here."""
    agent_dir = str(Path(hermes_agent_dir).expanduser())
    if agent_dir not in sys.path:
        sys.path.insert(0, agent_dir)
    try:
        from agent.auxiliary_client import call_llm
    except Exception:
        return None
    return call_llm


def accepts_provider_model(fn):
    """Whether `fn` takes `provider` and `model` keyword arguments, decided
    from its signature alone."""
    try:
        params = inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return False
    if any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values()):
        return True
    return "provider" in params and "model" in params


def _reasoning_effort(home):
    """The value of the single `reasoning_effort` key in config.yaml, or
    `unset`. Nothing else in the file is read into the result."""
    try:
        text = (Path(home) / "config.yaml").read_text(
            encoding="utf-8", errors="replace")
    except OSError:
        return "unset"
    match = re.search(r"^\s*reasoning_effort:\s*([^\s#]+)", text, re.M)
    if not match:
        return "unset"
    value = match.group(1).strip("'\"")
    return value if re.fullmatch(r"[A-Za-z0-9_.-]{1,32}", value) else "other"


# -- census -----------------------------------------------------------------
_SYNTHETIC_JOB = {"agentic_job_id": "synthetic", "job_name": "synthetic",
                  "job_type": "synthetic", "status": "SUCCESS"}
_SYNTHETIC_TRANSCRIPT = "user: synthetic request\nassistant: synthetic reply"


def _job_for(entry):
    return {"agentic_job_id": entry["agentic_job_id"],
            "job_name": entry["job_name"], "job_type": entry["job_type"],
            "status": "SUCCESS"}


def _surgery_survey(c, pool):
    """Apply every arm to the real builder's prompt for every pool arc (or a
    synthetic arc when the pool is empty). Returns `(surgery, mean_chars)`."""
    cfg = c._llm_evaluation_config()
    subjects = ([(_job_for(e), c._read_session_transcript(e["sid"]))
                 for e in pool]
                or [(_SYNTHETIC_JOB, _SYNTHETIC_TRANSCRIPT)])
    surgery, means = {}, {}
    for arm in ARM_EDITS:
        arm_cfg = _arm_config(cfg, arm)
        lengths = []
        try:
            for job, transcript in subjects:
                prompt = c._build_outcome_evaluation_prompt(
                    job, transcript, arm_cfg)
                lengths.append(len(apply_arm(prompt, arm)))
            surgery[arm] = "ok"
        except ArmSurgeryError as exc:
            surgery[arm] = str(exc)
        means[arm] = sum(lengths) // len(lengths) if lengths else 0
    return surgery, means


def _cmd_census(args, paths, out_dir, real_call_llm):
    c = load_plugin_package(args.plugin_dir)
    cfg_cap = args.pool_cap
    unit_error = None
    try:
        pool, counts = build_pool(paths, c, cfg_cap)
    except (TimestampUnitError, TimestampReadError) as exc:
        pool, counts = [], {step: 0 for step in EXCLUSION_STEPS}
        unit_error = ("unreadable" if isinstance(exc, TimestampReadError)
                      else "unknown")
    unit = unit_error or counts.pop("timestamp_unit")
    call_llm = real_call_llm or resolve_call_llm(args.hermes_agent_dir)
    if unit_error:
        surgery, means = {}, {}
    else:
        surgery, means = _surgery_survey(c, pool)
    census = {
        "counts": counts,
        "pool_n": len(pool),
        "timestamp_unit": unit,
        "surgery": surgery,
        "mean_prompt_chars": means,
        "call_llm_resolved": call_llm is not None,
        "call_llm_accepts_provider_model": (
            call_llm is not None and accepts_provider_model(call_llm)),
        "classifier_sha256": _sha256_file(
            Path(args.plugin_dir) / "classifier.py"),
        "evaluator_version": str(getattr(c, "LLM_EVALUATOR_VERSION", "")),
        "reasoning_effort": _reasoning_effort(paths.hermes_home),
        "harness_sha256": _sha256_file(__file__),
    }
    if unit_error:
        _write_json(out_dir / "census.json", census)
        print("census: cannot read message timestamps; stopped"
              if unit_error == "unreadable"
              else "census: timestamp unit is not epoch seconds; stopped")
        return EXIT_TIMESTAMP
    _write_private_json(out_dir / "pool.json", pool)
    _write_json(out_dir / "census.json", census)
    print("census: eligible=%d pool_n=%d" % (counts["eligible"], len(pool)))
    for step in EXCLUSION_STEPS:
        print("census: %s=%d" % (step, counts[step]))
    bad = sorted(a for a, v in surgery.items() if v != "ok")
    print("census: surgery %s" % ("ok" if not bad else "FAILED " + ",".join(bad)))
    return EXIT_OK


# -- calls ------------------------------------------------------------------
def _load_pool(out_dir):
    try:
        with open(out_dir / "pool.json", encoding="utf-8") as handle:
            pool = json.load(handle)
    except (OSError, ValueError):
        return None
    return pool if isinstance(pool, list) else None


def _resolve_run_model(args, out_dir):
    """The `(provider, model)` this out-dir's run is bound to, or None when
    the invocation must be refused.

    A binding file is authoritative: an explicit flag that differs from it, or
    a file that is not a JSON object with string `provider` and `model`, is a
    refusal. With no binding the pair is the explicit flag, else the replay
    defaults. A later stage must be judged against the model that answered
    the earlier ones, so the pair cannot change mid-run.
    """
    explicit_provider = getattr(args, "provider", None)
    explicit_model = getattr(args, "model", None)
    path = out_dir / RUN_MODEL_FILE
    if path.exists():
        try:
            bound = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if (not isinstance(bound, dict)
                or not isinstance(bound.get("provider"), str)
                or not isinstance(bound.get("model"), str)):
            return None
        if (explicit_provider is not None
                and explicit_provider != bound["provider"]):
            return None
        if explicit_model is not None and explicit_model != bound["model"]:
            return None
        return bound["provider"], bound["model"]
    return (explicit_provider or REPLAY_PROVIDER,
            explicit_model or REPLAY_MODEL)


def _bind_run_model(out_dir, provider, model):
    """Write the binding when there is none yet. Called only once every
    refusal has passed, so a refused invocation never binds."""
    path = out_dir / RUN_MODEL_FILE
    if not path.exists():
        _write_json(path, {"model": model, "provider": provider})


def _calls_path(out_dir):
    return out_dir / "calls.jsonl"


def _read_calls(out_dir):
    path = _calls_path(out_dir)
    return read_records(str(path)) if path.exists() else []


def effective_records(records):
    """The last non-smoke record per `(arc, arm)` and the attempt count per
    pair. A retry's record supersedes the `call_error` it retried."""
    effective, attempts = {}, Counter()
    for rec in records:
        if rec["stage"] == SMOKE_STAGE:
            continue
        key = (rec["arc"], rec["arm"])
        attempts[key] += 1
        effective[key] = rec
    return effective, attempts


def _attempts_path(out_dir):
    return out_dir / ATTEMPTS_FILE


def _append_attempt_line(out_dir, line):
    with open(_attempts_path(out_dir), "a", encoding="utf-8") as handle:
        handle.write(json.dumps(line, sort_keys=True) + "\n")


def unfinished_attempts(out_dir):
    """How many reserved calls never got a record. Such a call may have been
    billed, so it counts as spent. A torn line is skipped: a reservation is
    written before its call, so a torn one made no call."""
    path = _attempts_path(out_dir)
    if not path.exists():
        return 0
    reserved, finished = set(), set()
    with open(path, encoding="utf-8") as handle:
        for text in handle:
            try:
                line = json.loads(text)
            except ValueError:
                continue
            if not isinstance(line, dict):
                continue
            if "done" in line:
                finished.add(line["done"])
            elif "id" in line:
                reserved.add(line["id"])
    return len(reserved - finished)


def _real_callable(args, real_call_llm):
    return real_call_llm or resolve_call_llm(args.hermes_agent_dir)


def _verify_transcripts(c, entries):
    """Re-read each distinct arc's transcript and compare its digest with the
    pool's. Returns `({arc: verified_text}, drifted_arc_count)`.

    Arms of one arc are paired, so every call must replay the census-time
    input whichever invocation makes it. An entry with no digest, or a
    non-string one, counts as drifted: a pool written before the digest
    existed cannot be checked. The verified text is what the calls use, so
    what was checked and what is sent are the same bytes.
    """
    texts, seen, drifted = {}, set(), 0
    for entry in entries:
        arc = entry["arc"]
        if arc in seen:
            continue
        seen.add(arc)
        text = c._read_session_transcript(entry["sid"])
        digest = entry.get("transcript_sha256")
        if (isinstance(digest, str) and isinstance(text, str)
                and hashlib.sha256(text.encode("utf-8")).hexdigest()
                == digest):
            texts[arc] = text
        else:
            drifted += 1
    return texts, drifted


def _run_specs(c, specs, out_dir, concurrency, evaluator_version, transcripts):
    """Run `specs` (`(entry, arm, stage)`), appending each record as its
    chunk finishes so a crash loses at most one chunk. Each call is reserved
    in the attempts file before it is made, so a crash that loses a chunk's
    records still leaves those calls counted. `transcripts` is the verified
    `{arc: text}` map; no transcript is read here."""
    cfg = c._llm_evaluation_config()
    chunk = max(1, int(concurrency)) * 4
    done = 0
    for start in range(0, len(specs), chunk):
        chunk_specs = specs[start:start + chunk]
        batch, ids = [], {}
        for entry, arm, stage in chunk_specs:
            batch.append((_job_for(entry), transcripts[entry["arc"]], cfg,
                          arm, stage))

        def reserve(index, chunk_specs=chunk_specs, ids=ids):
            entry, arm, stage = chunk_specs[index]
            ids[index] = uuid.uuid4().hex
            _append_attempt_line(out_dir, {
                "id": ids[index], "arc": entry["arc"], "arm": arm,
                "stage": _stage_label(stage)})

        records = asyncio.run(run_calls(
            c, batch, concurrency, evaluator_version, on_start=reserve))
        for index, rec in enumerate(records):
            append_record(str(_calls_path(out_dir)), rec)
            _append_attempt_line(out_dir, {"done": ids[index]})
        done += len(records)
    return done


def _cmd_smoke(args, paths, out_dir, real_call_llm):
    pool = _load_pool(out_dir)
    if not pool:
        print("smoke: no pool.json; run census first")
        return EXIT_USAGE
    bound = _resolve_run_model(args, out_dir)
    if bound is None:
        print("smoke: refused, --model/--provider differ from this run's "
              "bound model")
        return EXIT_USAGE
    records = _read_calls(out_dir)
    if any(r["stage"] == SMOKE_STAGE for r in records):
        print("smoke: already recorded; no call made")
        return EXIT_OK
    call_llm = _real_callable(args, real_call_llm)
    if call_llm is None:
        print("smoke: call_llm did not resolve")
        return EXIT_NO_CALLABLE
    c = load_plugin_package(args.plugin_dir)
    transcripts, drifted = _verify_transcripts(c, [pool[0]])
    if drifted:
        print("smoke: refused, %d pool arc(s) changed since census; no call "
              "made" % drifted)
        return EXIT_DRIFT
    _bind_run_model(out_dir, *bound)
    install_replay_hooks(c, call_llm, *bound)
    try:
        done = _run_specs(
            c, [(pool[0], SMOKE_ARM, SMOKE_STAGE)], out_dir, 1,
            str(getattr(c, "LLM_EVALUATOR_VERSION", "")), transcripts)
    finally:
        restore_replay_hooks(c)
    [rec] = _read_calls(out_dir)[-1:]
    print("smoke: calls=%d outcome=%s served_model=%s" % (
        done, rec["outcome"], rec["served_model"]))
    return EXIT_OK


def _cmd_run(args, paths, out_dir, real_call_llm):
    pool = _load_pool(out_dir)
    if not pool:
        print("run: no pool.json; run census first")
        return EXIT_USAGE
    if args.max_calls is None or args.max_calls < 0:
        print("run: --max-calls is required")
        return EXIT_USAGE
    bound = _resolve_run_model(args, out_dir)
    if bound is None:
        print("run: refused, --model/--provider differ from this run's "
              "bound model")
        return EXIT_USAGE
    pool_keys = [e["arc"] for e in pool]
    records = _read_calls(out_dir)
    effective, attempts = effective_records(records)
    if args.stage == "candidates":
        try:
            gates = evaluate_gates(
                list(effective.values()), pool_keys, bound[1])
        except (IncompleteStageError, DuplicateRecordError, ValueError):
            print("run: refused, stage 1 is incomplete")
            return EXIT_STAGE
        if not gates["stage2_eligible"]:
            print("run: refused, the validity gates do not allow stage 2 "
                  "(failed: %s)" % ",".join(gates["reasons"]))
            return EXIT_STAGE
    arms = STAGE_ARMS[args.stage]
    stage = STAGE_NUMBER[args.stage]
    first = [(e, arm, stage) for e in pool for arm in arms
             if (e["arc"], arm) not in attempts]
    unfinished = unfinished_attempts(out_dir)
    completed = len(records) + unfinished
    if completed + len(first) > args.max_calls:
        print("run: refused, %d recorded + %d unfinished + %d planned "
              "exceeds --max-calls %d"
              % (len(records), unfinished, len(first), args.max_calls))
        return EXIT_BUDGET
    remaining = args.max_calls - completed - len(first)
    retries = [
        (e, arm, stage) for e in pool for arm in arms
        if attempts.get((e["arc"], arm)) == 1
        and effective[(e["arc"], arm)]["outcome"] == "call_error"
    ][:remaining]
    specs = first + retries
    if not specs:
        print("run: nothing to do; no call made")
        return EXIT_OK
    call_llm = _real_callable(args, real_call_llm)
    if call_llm is None:
        print("run: call_llm did not resolve")
        return EXIT_NO_CALLABLE
    c = load_plugin_package(args.plugin_dir)
    transcripts, drifted = _verify_transcripts(c, [e for e, _a, _s in specs])
    if drifted:
        print("run: refused, %d pool arc(s) changed since census; no call "
              "made" % drifted)
        return EXIT_DRIFT
    _bind_run_model(out_dir, *bound)
    install_replay_hooks(c, call_llm, *bound)
    try:
        done = _run_specs(
            c, specs, out_dir, args.concurrency,
            str(getattr(c, "LLM_EVALUATOR_VERSION", "")), transcripts)
    finally:
        restore_replay_hooks(c)
    print("run: stage=%s calls=%d first=%d retries=%d" % (
        args.stage, done, len(first), len(retries)))
    return EXIT_OK


def _print_stage_two_state(records, pool_keys, expected_model, exc):
    """Tell the operator why `report` cannot judge yet. With stage 1 complete
    and stage 2 eligible, show each gate and the next step, so an operator is
    not left reading "incomplete" with no way to see that stage 2 is open.
    Every other case keeps the plain incomplete line. Nothing is written."""
    try:
        gates = evaluate_gates(records, pool_keys, expected_model)
    except (IncompleteStageError, DuplicateRecordError, ValueError):
        gates = None
    if gates is None or not gates["stage2_eligible"]:
        print("report: incomplete (%s)" % type(exc).__name__)
        return
    for name in ("G0", "G1", "G2", "G3"):
        print("report: %s %s" % (name, "pass" if gates[name] else "fail"))
    if any(rec["arm"] in CANDIDATE_ARMS for rec in records):
        print("report: stage 2 eligible; candidates incomplete")
    else:
        print("report: stage 2 eligible; run --stage candidates")


def _cmd_report(args, paths, out_dir, real_call_llm):
    pool = _load_pool(out_dir)
    if not pool:
        print("report: no pool.json; run census first")
        return EXIT_USAGE
    bound = _resolve_run_model(args, out_dir)
    if bound is None:
        print("report: refused, --model/--provider differ from this run's "
              "bound model")
        return EXIT_USAGE
    effective, _attempts = effective_records(_read_calls(out_dir))
    records = list(effective.values())
    pool_keys = [e["arc"] for e in pool]
    try:
        report = evaluate_protocol(records, pool_keys, bound[1])
    except ServedModelError as exc:
        print("report: refused, served model below the required share in "
              "arm %s" % exc.arm)
        return EXIT_STAGE
    except IncompleteStageError as exc:
        _print_stage_two_state(records, pool_keys, bound[1], exc)
        return EXIT_STAGE
    except (DuplicateRecordError, ValueError) as exc:
        print("report: incomplete (%s)" % type(exc).__name__)
        return EXIT_STAGE
    (out_dir / "report.json").write_text(
        report_to_json(report) + "\n", encoding="utf-8")
    print(report["outcome"])
    return EXIT_OK


def _cmd_fence(args, paths, out_dir, real_call_llm):
    pool = _load_pool(out_dir)
    if not pool:
        print("fence: no pool.json; run census first")
        return EXIT_USAGE
    snap_path = out_dir / "fence-snapshot.json"
    if args.snapshot:
        _write_private_json(snap_path, fence_snapshot(paths, pool))
        print("fence: snapshot written")
        return EXIT_OK
    if not args.check:
        print("fence: pass --snapshot or --check")
        return EXIT_USAGE
    try:
        before = json.loads(snap_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        print("fence: no snapshot; run fence --snapshot first")
        return EXIT_USAGE
    result = fence_check(paths, pool, before, args.since_epoch)
    tripped = [(name, result[name]) for name in FENCE_CHECKS if result[name]]
    for name, count in tripped:
        print("FENCE VIOLATION check=%s count=%d" % (name, count))
    if tripped:
        return EXIT_FENCE
    print("fence: clean")
    return EXIT_OK


def _cmd_verify_deploy(args, paths, out_dir, real_call_llm):
    deployed = load_plugin_package(args.plugin_dir, "phase67_deployed_pkg")
    baseline = load_plugin_package(
        args.baseline_plugin_dir, "phase67_baseline_pkg")
    cfg = deployed._llm_evaluation_config()
    variants = (("full", cfg),
                ("no_rate_card", {k: v for k, v in cfg.items()
                                  if k != "rateCard"}))
    ok = True
    for label, variant in variants:
        got = deployed._build_outcome_evaluation_prompt(
            _SYNTHETIC_JOB, _SYNTHETIC_TRANSCRIPT, variant)
        try:
            want = apply_arm(baseline._build_outcome_evaluation_prompt(
                _SYNTHETIC_JOB, _SYNTHETIC_TRANSCRIPT, variant), args.arm)
        except ArmSurgeryError:
            print("config=%s surgery_failed arm=%s" % (label, args.arm))
            ok = False
            continue
        match = got == want
        ok = ok and match
        print("config=%s deployed_sha256=%s expected_sha256=%s match=%s" % (
            label, hashlib.sha256(got.encode("utf-8")).hexdigest(),
            hashlib.sha256(want.encode("utf-8")).hexdigest(),
            "true" if match else "false"))
    return EXIT_OK if ok else EXIT_FENCE


_COMMANDS = {
    "census": _cmd_census, "smoke": _cmd_smoke, "run": _cmd_run,
    "report": _cmd_report, "fence": _cmd_fence,
    "verify-deploy": _cmd_verify_deploy,
}
_NEEDS_CLASSIFIER = ("census", "smoke", "run", "verify-deploy")


def build_parser():
    parser = argparse.ArgumentParser(
        prog="confidence_replay_harness",
        description="Phase 67 on-host replay harness (TRU-03).")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--hermes-home", default="~/.hermes")
    common.add_argument("--plugin-dir", default=None)
    common.add_argument("--hermes-agent-dir", default=None)
    common.add_argument("--out-dir", required=True)
    # None means "the run's bound model, else the replay default"; see
    # `_resolve_run_model`.
    common.add_argument("--model", default=None)
    common.add_argument("--provider", default=None)
    sub = parser.add_subparsers(dest="command", required=True)
    census = sub.add_parser("census", parents=[common])
    census.add_argument("--pool-cap", type=int, default=DEFAULT_POOL_CAP)
    sub.add_parser("smoke", parents=[common])
    run = sub.add_parser("run", parents=[common])
    run.add_argument("--stage", choices=sorted(STAGE_NUMBER), required=True)
    run.add_argument("--max-calls", type=int, default=None)
    run.add_argument("--concurrency", type=int, default=4)
    sub.add_parser("report", parents=[common])
    fence = sub.add_parser("fence", parents=[common])
    fence.add_argument("--snapshot", action="store_true")
    fence.add_argument("--check", action="store_true")
    fence.add_argument("--since-epoch", type=float, default=None)
    verify = sub.add_parser("verify-deploy", parents=[common])
    verify.add_argument("--baseline-plugin-dir", required=True)
    verify.add_argument("--arm", required=True, choices=sorted(ARM_EDITS))
    return parser


def _inside(child, parent):
    child, parent = Path(child).resolve(), Path(parent).resolve()
    return child == parent or parent in child.parents


def main(argv=None, real_call_llm=None):
    """Run one subcommand and return its exit code. `real_call_llm` injects
    the model callable (tests); the host leaves it None."""
    sys.dont_write_bytecode = True
    try:
        args = build_parser().parse_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else EXIT_USAGE
    home = Path(args.hermes_home).expanduser()
    out_dir = Path(args.out_dir).expanduser()
    if _inside(out_dir, home):
        print("refused: --out-dir resolves inside --hermes-home")
        return EXIT_USAGE
    if args.plugin_dir is None:
        args.plugin_dir = str(home / "plugins" / "revenium-classifier")
    if args.hermes_agent_dir is None:
        args.hermes_agent_dir = str(home / "hermes-agent")
    out_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    handler = _COMMANDS[args.command]
    if args.command in _NEEDS_CLASSIFIER:
        with _host_env(home) as paths:
            return handler(args, paths, out_dir, real_call_llm)
    return handler(args, host_paths(home), out_dir, real_call_llm)


if __name__ == "__main__":
    sys.exit(main())
