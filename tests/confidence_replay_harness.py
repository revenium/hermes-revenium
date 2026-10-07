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

import asyncio
import contextvars
import hashlib
import importlib.util
import json
import logging
import re
import sys
import time
from collections import namedtuple
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

# Arm A0 has no text edits; its config transform removes `rateCard`
# (see `_arm_config`), which reproduces the pre-PR-#140 prompt.
ARM_EDITS = {
    "A0": (),
    "A1": (),
    "A2": (),
    "B": _PROMOTE_EDITS,
}

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


async def run_calls(c, calls, concurrency, evaluator_version):
    """Run `calls`, a list of `(job, transcript, cfg, arm, stage)`, with at
    most `concurrency` in flight. Returns the records in call order."""
    semaphore = asyncio.Semaphore(max(1, int(concurrency)))

    async def one(spec):
        job, transcript, cfg, arm, stage = spec
        async with semaphore:
            return await replay_call(
                c, job, transcript, cfg, arm, stage, evaluator_version)

    return list(await asyncio.gather(*(one(spec) for spec in calls)))


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
