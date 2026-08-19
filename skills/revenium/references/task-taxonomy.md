# Task Taxonomy

## What this is

The task taxonomy is an agent-owned controlled vocabulary stored at `${TAXONOMY_FILE}` (declared
in `common.sh`; defaults to `~/.hermes/state/revenium/task-taxonomy.json`). The seed file at
`skills/revenium/task-taxonomy.json` is copied into `${TAXONOMY_FILE}` on fresh installs — by the
root `install.sh` on the repo-clone path, and by `scripts/install.sh` on the tap path
(`hermes skills install` → `references/bootstrap.sh`). Both are guarded on file existence: an
existing taxonomy is a vocabulary the host has grown, and is never overwritten. Until
quick task 260817-l6o only the root script seeded it, so tap-installed hosts started with no
runtime taxonomy at all and classified against an empty vocabulary. After installation, the live file at `${TAXONOMY_FILE}` is mutable:
the agent adds new labels to it over time via the atomic write pattern documented below.

Before classifying a substantive turn, the classifier reads `${TAXONOMY_FILE}` as a
recency-ordered reference list. The classifier mints a specific descriptive label by default;
existing labels are reused only when they describe the SAME specific work (per the 2026-05-14
prompt rewrite, quick task 260514-nfb). Newly-minted labels are persisted back via the atomic
write pattern documented below.

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

The classifier reads `${TAXONOMY_FILE}` before every substantive turn and mints a SPECIFIC,
DESCRIPTIVE label that captures what the agent actually did (2-4 words joined by underscores).
The prompt deliberately carries no concrete example labels: they were copied verbatim onto
unrelated work in 20% of classifications, and removing them also improved granularity
(quick task 260815-r39). Existing labels are reused
only when they describe the SAME specific work — "close enough" reuse caused taxonomy
fragmentation in practice (quick task 260514-nfb).

When uncertain whether to mint or reuse, mint a new specific label rather than collapsing to
a bland catch-all. Catch-alls to avoid when a more specific label fits: `generation`, `analysis`,
`review`, `task`.

These four are deliberately **absent from the seed file**. Seeding a catch-all contradicts the
mint-first policy above: the prompt tells the classifier to avoid emitting them while the seed
offers them as reusable vocabulary. The seed shipped 2026-05-12 under the earlier closed-set
design ("pick the best-fitting label"); the 2026-05-14 mint-first rewrite superseded that model
but the seed was never revisited. Do not re-add them.

Minting process: choose a snake_case name matching the regex above; the classifier plugin
persists the new entry to `${TAXONOMY_FILE}` automatically via the atomic write pattern below
before the marker is written.

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
profiling system behavior, mint a specific label for that diagnosis (e.g.
`slow_query_profiling`) rather than reusing `research`.

### code_review

Use `code_review` when the turn evaluates code — a function, a diff, a module, or an
architectural decision — for correctness, style, or architectural fit.

Examples: "review this function", "check this diff for bugs"

Disambiguation: when the subject of review is a design document, runbook, or prose rather than
code, mint a specific label naming the artifact (e.g. `runbook_review`, `adr_review`).
`code_review` is for code specifically — a function, a diff, a module, an architectural decision.

### refactor

Use `refactor` when the turn restructures existing code without changing its observable behavior.
The turn output is modified source code that is functionally equivalent to the original.

Examples: "extract this into a helper", "rename these variables"

Disambiguation: if the turn changes behavior (fixes a bug, adds a feature), it is not a
refactor. If the turn produces a new artifact from scratch, mint a specific label naming what
was produced (e.g. `webhook_handler_impl`), not a generic one.

### planning

Use `planning` when the turn produces a plan, roadmap, design document, or task breakdown. The
output is a structured description of future work, not the work itself.

Examples: "break this into subtasks", "design the schema for X"

Disambiguation: if the turn produces runnable code or configuration, mint a specific label for
what was built. If the turn evaluates an existing plan or design for correctness, mint a
specific label naming the artifact reviewed (e.g. `migration_plan_review`).

### debugging

Use `debugging` when the turn reproduces and fixes a defect or unexpected behavior. The turn
involves identifying the root cause of a failure and producing a correction.

Examples: "this test fails intermittently", "fix this error"

Disambiguation: if the turn identifies the cause without fixing it, mint a specific label for
the diagnosis (e.g. `race_condition_diagnosis`). If the turn produces a new feature rather than
correcting a defect, mint a specific label naming the feature.
