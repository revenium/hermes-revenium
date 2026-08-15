#!/usr/bin/env python3
"""Interactive demo: one input, classified through N host framings.

Why a UI for a "fact" spike: the fact worth feeling is not "it returns a label",
it is that the SAME work classified through different host prompts can come back
with different labels. Reading that in a table is easy to wave away. Watching
three columns disagree on your own text is not.

Run: python3 serve_demo.py        # real claude CLI calls, ~8s per column
     python3 serve_demo.py --fake # instant, canned responses
Then open http://localhost:8722
"""
from __future__ import annotations

import json
import sys
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

SPIKE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SPIKE_DIR))
sys.path.insert(0, str(SPIKE_DIR.parent / "001-extraction-seam"))

import revenium_classify as lib  # noqa: E402
from clients import claude_cli_client, scripted_client  # noqa: E402

FAKE = "--fake" in sys.argv
PORT = 8722
HOSTS = ["Hermes", "LiteLLM proxy", "Claude Code"]

# Forensic event log — every classification, exportable via GET /log.
EVENTS = []


def log(category, **fields):
    EVENTS.append({
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "category": category,
        **fields,
    })


SEEDS = ["research", "analysis", "code_review", "generation"]

PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>Cross-host classification</title>
<style>
 :root { color-scheme: light dark; }
 body { font: 15px/1.5 ui-sans-serif, system-ui, sans-serif; max-width: 960px;
        margin: 2rem auto; padding: 0 1rem; }
 h1 { font-size: 1.3rem; margin-bottom: .2rem; }
 p.sub { color: #777; margin-top: 0; }
 textarea { width: 100%; font: 13px ui-monospace, monospace; padding: .6rem;
            border: 1px solid #8884; border-radius: 6px; background: transparent;
            color: inherit; }
 button { padding: .55rem 1.1rem; border-radius: 6px; border: 1px solid #8886;
          background: #8881; color: inherit; font-size: .95rem; cursor: pointer; }
 button:disabled { opacity: .5; cursor: progress; }
 .cols { display: grid; grid-template-columns: repeat(3, 1fr); gap: .8rem; margin-top: 1.2rem; }
 .col { border: 1px solid #8884; border-radius: 8px; padding: .8rem; }
 .host { font-size: .75rem; text-transform: uppercase; letter-spacing: .06em; color: #888; }
 .label { font: 600 1.05rem ui-monospace, monospace; margin: .45rem 0; word-break: break-all; }
 .meta { font-size: .75rem; color: #888; }
 .agree { margin-top: 1rem; padding: .7rem .9rem; border-radius: 8px; border: 1px solid #8884; }
 .same { border-color: #2a8a4a88; } .diff { border-color: #b4443288; }
 pre { background: #8881; padding: .7rem; border-radius: 6px; overflow-x: auto; font-size: .75rem; }
</style></head><body>
<h1>One input, three host framings</h1>
<p class="sub">The extracted library is identical in all three columns. Only the
<code>host</code> parameter differs — which is the only thing that differs between
the Hermes plugin's prompt and a LiteLLM guardrail's.</p>

<label class="meta">User message</label>
<textarea id="u" rows="4">Our reconciliation job is dropping about 0.3% of settlement rows overnight. Here's the job config and last night's log tail — figure out where the rows are going.</textarea>
<label class="meta">Assistant response</label>
<textarea id="a" rows="4">The drop is in the dedupe stage: settlement_id is compared after a lossy cast to int64, so ids above 2^53 collide and the second row is discarded as a duplicate.</textarea>
<p><button id="go">Classify through all three hosts</button>
   <span class="meta" id="status"></span></p>
<div class="cols" id="cols"></div>
<div id="verdict"></div>
<p class="meta"><a href="/log">export forensic log (JSON)</a></p>

<script>
const HOSTS = %HOSTS%;
document.getElementById('go').onclick = async () => {
  const btn = document.getElementById('go');
  btn.disabled = true;
  document.getElementById('status').textContent = 'calling the model once per host…';
  document.getElementById('cols').innerHTML = HOSTS.map(h =>
    `<div class="col"><div class="host">${h}</div><div class="label">…</div></div>`).join('');
  document.getElementById('verdict').innerHTML = '';
  const body = JSON.stringify({user: u.value, assistant: a.value});
  const res = await fetch('/classify', {method:'POST', body});
  const data = await res.json();
  document.getElementById('cols').innerHTML = data.results.map(r =>
    `<div class="col"><div class="host">${r.host}</div>
     <div class="label">${r.label}</div>
     <div class="meta">${r.elapsed_s}s · prompt ${r.prompt_bytes} B</div></div>`).join('');
  const uniq = [...new Set(data.results.map(r => r.label))];
  document.getElementById('verdict').innerHTML =
    `<div class="agree ${uniq.length === 1 ? 'same' : 'diff'}">` +
    (uniq.length === 1
      ? `<b>All three hosts agree:</b> <code>${uniq[0]}</code>. One input agreeing is not
         a guarantee — run it again with different text.`
      : `<b>${uniq.length} different labels for the same work:</b> <code>${uniq.join('</code>, <code>')}</code>.
         Same library, same model, same input — only the host framing differed. In Revenium
         these become separate rows in a spend breakdown.`) + `</div>`;
  document.getElementById('status').textContent = '';
  btn.disabled = false;
};
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json"):
        raw = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path == "/":
            self._send(200, PAGE.replace("%HOSTS%", json.dumps(HOSTS)), "text/html; charset=utf-8")
        elif self.path == "/log":
            self._send(200, json.dumps({"events": EVENTS, "count": len(EVENTS)}, indent=2))
        else:
            self._send(404, json.dumps({"error": "not found"}))

    def do_POST(self):
        if self.path != "/classify":
            return self._send(404, json.dumps({"error": "not found"}))
        n = int(self.headers.get("Content-Length", 0))
        payload = json.loads(self.rfile.read(n) or b"{}")
        user, assistant = payload.get("user", ""), payload.get("assistant", "")
        results = []
        for host in HOSTS:
            llm = scripted_client([f"demo_label_{host.split()[0].lower()}"]) if FAKE else claude_cli_client()
            clf = lib.Classifier(llm=llm, taxonomy=lib.InMemoryTaxonomy(seed=SEEDS), host=host)
            prompt = lib.build_classification_prompt(user, assistant, SEEDS, host=host)
            t0 = time.time()
            try:
                label = clf.classify_turn(user, assistant)
            except Exception as exc:
                label = f"error: {exc}"
            row = {
                "host": host,
                "label": label,
                "elapsed_s": round(time.time() - t0, 2),
                "prompt_bytes": len(prompt.encode("utf-8")),
            }
            log("classify", **row)
            results.append(row)
        labels = {r["label"] for r in results}
        log("compare", distinct_labels=len(labels), labels=sorted(labels))
        self._send(200, json.dumps({"results": results}))


if __name__ == "__main__":
    print(f"demo on http://localhost:{PORT}  ({'canned responses' if FAKE else 'real claude CLI calls'})")
    HTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
