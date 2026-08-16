"""Model clients a host can inject into revenium_classify.Classifier.

FINDING (see README): the library's client contract is OpenAI-shaped — it calls
    llm(messages=[...], temperature=, max_tokens=, timeout=)
and reads `.choices[0].message.content`. That shape came from Hermes'
auxiliary_client. Any host whose client differs must write a shim like the ones
below. That is a real (small) portability tax, and it is inherited, not designed.
"""
from __future__ import annotations

import subprocess


class _Msg:
    def __init__(self, content):
        self.content = content


class _Choice:
    def __init__(self, content):
        self.message = _Msg(content)


class OpenAIShaped:
    """Minimal stand-in for the response object the library expects."""

    def __init__(self, content):
        self.choices = [_Choice(content)]


def claude_cli_client(model: str = "claude-sonnet-5"):
    """A real model client backed by the local `claude` CLI.

    This is deliberately a REAL call, not a stub: the spike's question is whether
    a non-Hermes host can drive the library with its own client, and a fake would
    beg that question. `claude -p` carries CLI startup overhead that a direct API
    call would not — do not read latency numbers off this (see spike 004).
    """

    def _call(messages, temperature=0.0, max_tokens=64, timeout=30.0, **_):
        system = "\n".join(m["content"] for m in messages if m.get("role") == "system")
        user = "\n".join(m["content"] for m in messages if m.get("role") == "user")
        prompt = (system + "\n\n" + user).strip()
        proc = subprocess.run(
            ["claude", "-p", prompt, "--model", model],
            capture_output=True, text=True, timeout=timeout,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"claude CLI failed: {proc.stderr.strip()[:200]}")
        return OpenAIShaped(proc.stdout.strip())

    return _call


def scripted_client(responses):
    """Deterministic client for the UI demo and for repeatable runs."""
    seq = list(responses)

    def _call(messages, **_):
        return OpenAIShaped(seq.pop(0) if seq else "unclassified")

    return _call
