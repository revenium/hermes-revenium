# Task Taxonomy

## What this is

The task taxonomy is an agent-owned controlled vocabulary stored at `${TAXONOMY_FILE}` (declared
in `common.sh`; defaults to `~/.hermes/state/revenium/task-taxonomy.json`). The seed file at
`skills/revenium/task-taxonomy.json` is copied into `${TAXONOMY_FILE}` on fresh installs by
`examples/setup-local.sh`. After installation, the live file at `${TAXONOMY_FILE}` is mutable:
the agent adds new labels to it over time via the atomic write pattern documented below.

Before classifying a substantive turn, the agent reads `${TAXONOMY_FILE}` and attempts to reuse
an existing label. A new label is minted only when no existing label clearly fits the turn's
semantics. Once created, a label is permanent for the lifetime of the installation.

## Schema

The taxonomy file is a JSON object with a single top-level key, `labels`. Its value is an object
mapping label names to per-label descriptors. Each descriptor has exactly two keys:

- `description` — a short string (at most 25 words) describing when to use this label
- `examples` — an array of exactly two short example phrases

No other keys are present in the per-label descriptor.

```json
{
  "labels": {
    "research": {
      "description": "Reading docs, exploring the codebase, or searching the web to learn before acting",
      "examples": [
        "find all usages of X",
        "what does this API return"
      ]
    }
  }
}
```

## Label normalization rules

Labels are lowercase, snake_case strings. The following rules apply to every label key, whether
seeded or minted:

- All characters must be lowercase ASCII letters, digits, or underscores.
- The label must start with a lowercase letter.
- The label must be at least 2 characters and at most 48 characters long.
- The label must match the regular expression:

```text
^[a-z][a-z0-9_]{1,47}$
```

Hyphens, spaces, uppercase letters, and non-ASCII characters are not permitted. When minting a
new label, normalize the candidate name by converting hyphens and spaces to underscores and
lowercasing all characters before applying the regex check.

## Blocklist

The following trivial labels are rejected by the cron pipeline. The agent must never use them
as a `task_type` value, even if the session turn resembles an acknowledgment or greeting:

- `ack`
- `acknowledgment`
- `greeting`
- `confirmation`
- `hello`
- `thanks`

The blocklist is a closed set for v1. Adding entries requires a release.

## Mint policy

The agent reads `${TAXONOMY_FILE}` before every substantive turn classification and reuses an
existing label when any label clearly fits the turn's semantics. A new label is minted only when
no existing label provides a good fit.

Bias toward reuse: fragmentation is permanent, but an oversized label bucket is recoverable by
a later analysis pass. When in doubt between two labels, pick the more specific one if it exists
(for example, prefer `code_review` over `review` when the turn is specifically about reviewing
code). When genuinely uncertain whether to mint or reuse, default to the closest existing label
rather than creating a new one.

Minting process: choose a snake_case name matching the regex above, provide a short description
and two examples, and commit the new entry to `${TAXONOMY_FILE}` using the atomic write pattern
below before the marker is written.

## Atomic write pattern

Taxonomy mutations use the write-to-tmp + `os.rename` + `fcntl.flock` pattern. This prevents
partial reads: `os.rename` on a POSIX filesystem is atomic — the file visible to readers is
always either the pre-mutation state or the post-mutation state, never a partially written
intermediate.

The temp file must be created in the same directory as the target taxonomy file. `os.rename` is
only atomic when source and destination are on the same filesystem. Never write the temp file
to `/tmp` or another directory that may be on a different filesystem.

```python
import fcntl, json, os, tempfile

def mint_label(taxonomy_path, name, description, examples):
    """Add a new label to the taxonomy using the atomic write pattern."""
    import re
    name = re.sub(r'[^a-z0-9_]', '', re.sub(r'[-\s]+', '_', name.lower()))
    if not re.match(r'^[a-z][a-z0-9_]{1,47}$', name):
        return None  # reject malformed label
    with open(taxonomy_path, "r+") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        data = json.load(f)
        if name in data.get("labels", {}):
            return name  # idempotent: already exists
        data.setdefault("labels", {})[name] = {
            "description": description,
            "examples": examples,
        }
        d = os.path.dirname(taxonomy_path)
        with tempfile.NamedTemporaryFile("w", dir=d, delete=False, suffix=".tmp") as tmp:
            json.dump(data, tmp, indent=2, ensure_ascii=True)
            tmp.flush()
            os.fsync(tmp.fileno())
            tmpname = tmp.name
        os.rename(tmpname, taxonomy_path)  # atomic replace on POSIX same-filesystem
    return name
```

The `fcntl.flock(LOCK_EX)` call is advisory. It prevents two concurrent agent processes from
both attempting to mint the same label at the same moment. A non-cooperating reader (such as
the cron pipeline) is not blocked by this lock; the reader sees a consistent file state
regardless because `os.rename` is the actual atomicity mechanism.

## Label catalog

### research

Use `research` when the turn's primary activity is information gathering: reading documentation,
exploring the codebase to understand how something works, or searching the web to learn before
taking action. The turn output is primarily knowledge, not a produced artifact.

Examples: "find all usages of X", "what does this API return"

Disambiguation: if the turn moves beyond gathering into diagnosing a specific problem or
profiling system behavior, prefer `analysis`.

### analysis

Use `analysis` when the turn diagnoses a problem, profiles system behavior, or characterizes
how a system works based on evidence. The turn output is a finding or characterization, not
a fix or new artifact.

Examples: "why is this test failing", "trace the data flow for X"

Disambiguation: if the turn is primarily reading docs or searching for background information,
prefer `research`. If the turn results in a concrete fix, prefer `debugging`.

### generation

Use `generation` when the turn produces new code, tests, configuration, or documentation from
scratch. The turn output is a new artifact that did not previously exist.

Examples: "write a function that does X", "add tests for module Y"

Disambiguation: if the turn modifies existing code without changing behavior, prefer `refactor`.
If the turn produces a plan or design doc rather than runnable code, prefer `planning`.

### review

Use `review` when the turn evaluates existing work — documents, designs, plans, pull requests,
or diffs — for correctness or fit. The subject of review is not exclusively code.

Examples: "review this PR", "does this doc make sense"

Disambiguation: when the review is specifically of code (functions, diffs, architecture), prefer
`code_review`. When the subject is a design document, specification, or prose document, use
`review`.

### code_review

Use `code_review` when the turn evaluates code — a function, a diff, a module, or an
architectural decision — for correctness, style, or architectural fit.

Examples: "review this function", "check this diff for bugs"

Disambiguation: when the subject of review is a design document, runbook, or prose rather than
code, prefer `review`. Both `review` and `code_review` involve reading existing work; the
distinction is whether the subject is code.

### refactor

Use `refactor` when the turn restructures existing code without changing its observable behavior.
The turn output is modified source code that is functionally equivalent to the original.

Examples: "extract this into a helper", "rename these variables"

Disambiguation: if the turn changes behavior (fixes a bug, adds a feature), it is not a
refactor. If the turn produces a new module from scratch, prefer `generation`.

### planning

Use `planning` when the turn produces a plan, roadmap, design document, or task breakdown. The
output is a structured description of future work, not the work itself.

Examples: "break this into subtasks", "design the schema for X"

Disambiguation: if the turn produces runnable code or configuration, prefer `generation`. If the
turn evaluates an existing plan or design for correctness, prefer `review`.

### debugging

Use `debugging` when the turn reproduces and fixes a defect or unexpected behavior. The turn
involves identifying the root cause of a failure and producing a correction.

Examples: "this test fails intermittently", "fix this error"

Disambiguation: if the turn identifies the cause without fixing it, prefer `analysis`. If the
turn produces a new feature rather than correcting a defect, prefer `generation`.
