#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
selector="${script_dir}/select-gitleaks-range.sh"
fixture="$(mktemp -d)"
unrelated_fixture="$(mktemp -d)"
trap 'rm -rf "$fixture" "$unrelated_fixture"' EXIT

fail() {
  printf 'FAIL: %s\n' "$1" >&2
  exit 1
}

assert_output() {
  local output_file="$1"
  local expected="$2"

  grep -Fqx "$expected" "$output_file" ||
    fail "expected '$expected' in $(cat "$output_file")"
}

assert_warning() {
  local output_file="$1"
  local expected="$2"

  grep -Fqx "$expected" "${output_file}.stderr" ||
    fail "expected warning '$expected' in $(cat "${output_file}.stderr")"
}

run_selector() {
  local output_file="$1"
  shift

  : >"$output_file"
  : >"${output_file}.stderr"
  env GITHUB_OUTPUT="$output_file" "$@" "$selector" 2>"${output_file}.stderr"
}

git -C "$fixture" init -q
git -C "$fixture" checkout -qb main
git -C "$fixture" config user.email ci-test@revenium.io
git -C "$fixture" config user.name 'CI Test'
printf 'initial\n' >"$fixture/conflict.txt"
git -C "$fixture" add conflict.txt
git -C "$fixture" commit -qm 'initial'
root_sha="$(git -C "$fixture" rev-parse HEAD)"

# A regular pull-request commit.
git -C "$fixture" switch -qc feature
printf 'feature\n' >"$fixture/feature.txt"
git -C "$fixture" add feature.txt
git -C "$fixture" commit -qm 'feature change'
feature_sha="$(git -C "$fixture" rev-parse HEAD)"

output="$fixture/output"
(
  cd "$fixture"
  run_selector "$output" \
    EVENT_NAME=pull_request PR_BASE_SHA="$root_sha" PR_HEAD_SHA="$feature_sha"
)
assert_output "$output" 'mode=incremental'
assert_output "$output" "commit_range=${root_sha}..${feature_sha}"

# A normal push scans only newly introduced history.
(
  cd "$fixture"
  run_selector "$output" \
    EVENT_NAME=push PUSH_BEFORE_SHA="$root_sha" PUSH_AFTER_SHA="$feature_sha" PUSH_FORCED=false
)
assert_output "$output" 'mode=incremental'
assert_output "$output" "commit_range=${root_sha}..${feature_sha}"

# Scheduled and manual events retain full-history coverage.
(
  cd "$fixture"
  run_selector "$output" EVENT_NAME=schedule
)
assert_output "$output" 'mode=full'
assert_output "$output" 'reason=scheduled full-history scan'

(
  cd "$fixture"
  run_selector "$output" EVENT_NAME=workflow_dispatch
)
assert_output "$output" 'mode=full'
assert_output "$output" 'reason=manual full-history scan'

# Unknown events use the fail-safe full-history path.
(
  cd "$fixture"
  run_selector "$output" EVENT_NAME=unknown_event
)
assert_output "$output" 'mode=full'
assert_output "$output" "reason=unsupported event 'unknown_event'"
assert_warning "$output" "::warning::Gitleaks range unavailable: unsupported event 'unknown_event'. Falling back to a full-history scan."

# Missing/zero before SHAs and force pushes fail safe to full history.
(
  cd "$fixture"
  run_selector "$output" \
    EVENT_NAME=push PUSH_BEFORE_SHA=0000000000000000000000000000000000000000 \
    PUSH_AFTER_SHA="$feature_sha" PUSH_FORCED=false
)
assert_output "$output" 'mode=full'
assert_output "$output" 'reason=push before SHA is missing or zero'
assert_warning "$output" '::warning::Gitleaks range unavailable: push before SHA is missing or zero. Falling back to a full-history scan.'

(
  cd "$fixture"
  run_selector "$output" \
    EVENT_NAME=push PUSH_BEFORE_SHA="$root_sha" PUSH_AFTER_SHA="$feature_sha" PUSH_FORCED=true
)
assert_output "$output" 'mode=full'
assert_output "$output" 'reason=forced push'
assert_warning "$output" '::warning::Gitleaks range unavailable: forced push. Falling back to a full-history scan.'

# PUSH_BEFORE_SHA has an explicit empty/zero guard above; PUSH_AFTER_SHA has
# no equivalent guard and instead relies on is_commit's regex rejection
# inside emit_incremental_scan. Exercise that path directly.
(
  cd "$fixture"
  run_selector "$output" \
    EVENT_NAME=push PUSH_BEFORE_SHA="$root_sha" PUSH_FORCED=false
  # PUSH_AFTER_SHA intentionally absent
)
assert_output "$output" 'mode=full'
assert_output "$output" 'reason=push head SHA is missing or unavailable'
assert_warning "$output" '::warning::Gitleaks range unavailable: push head SHA is missing or unavailable. Falling back to a full-history scan.'

# An unavailable but well-formed base SHA cannot create a silent bypass.
missing_sha=1111111111111111111111111111111111111111
(
  cd "$fixture"
  run_selector "$output" \
    EVENT_NAME=pull_request PR_BASE_SHA="$missing_sha" PR_HEAD_SHA="$feature_sha"
)
assert_output "$output" 'mode=full'
assert_output "$output" 'reason=pull request base SHA is missing or unavailable'
assert_warning "$output" '::warning::Gitleaks range unavailable: pull request base SHA is missing or unavailable. Falling back to a full-history scan.'

# An unavailable PR head SHA has the same fail-safe behavior.
(
  cd "$fixture"
  run_selector "$output" \
    EVENT_NAME=pull_request PR_BASE_SHA="$root_sha" PR_HEAD_SHA="$missing_sha"
)
assert_output "$output" 'mode=full'
assert_output "$output" 'reason=pull request head SHA is missing or unavailable'
assert_warning "$output" '::warning::Gitleaks range unavailable: pull request head SHA is missing or unavailable. Falling back to a full-history scan.'

# Build a real branch-update merge with a conflict resolution. The selected PR
# range includes the merge commit, and the merge-aware log mode exposes content
# introduced only by its resolution.
git -C "$fixture" switch -q main
printf 'main update\n' >"$fixture/conflict.txt"
git -C "$fixture" add conflict.txt
git -C "$fixture" commit -qm 'main update'
main_sha="$(git -C "$fixture" rev-parse HEAD)"

git -C "$fixture" switch -q feature
printf 'feature update\n' >"$fixture/conflict.txt"
git -C "$fixture" add conflict.txt
git -C "$fixture" commit -qm 'feature conflict'
if git -C "$fixture" merge --no-edit main >/dev/null 2>&1; then
  fail 'fixture merge unexpectedly had no conflict'
fi
printf 'RESOLUTION_SECRET_MARKER\n' >"$fixture/conflict.txt"
git -C "$fixture" add conflict.txt
git -C "$fixture" commit -qm 'merge main with resolution'
merge_sha="$(git -C "$fixture" rev-parse HEAD)"

(
  cd "$fixture"
  run_selector "$output" \
    EVENT_NAME=pull_request PR_BASE_SHA="$main_sha" PR_HEAD_SHA="$merge_sha"
)
assert_output "$output" 'mode=incremental'
assert_output "$output" "commit_range=${main_sha}..${merge_sha}"
merge_log="$(git -C "$fixture" log -p --diff-merges=separate "${main_sha}..${merge_sha}")"
grep -Fq '+RESOLUTION_SECRET_MARKER' <<<"$merge_log" ||
  fail 'merge-conflict resolution was absent from the merge-aware PR log'

# Base ahead of head must not silently resolve to an empty range. A plain
# `git rev-list --quiet base..head` exits 0 here (empty range = "success"),
# which is the exact bug this test guards against.
(
  cd "$fixture"
  run_selector "$output" \
    EVENT_NAME=pull_request PR_BASE_SHA="$feature_sha" PR_HEAD_SHA="$root_sha"
)
assert_output "$output" 'mode=full'
assert_output "$output" 'reason=pull request commit range cannot be traversed'
assert_warning "$output" '::warning::Gitleaks range unavailable: pull request commit range cannot be traversed. Falling back to a full-history scan.'

# Unrelated histories (no common ancestor) must not silently resolve either.
# `git rev-list --quiet base..head` exits 0 for these too, since it lists a
# set difference, not an ancestry check.
git -C "$unrelated_fixture" init -q
git -C "$unrelated_fixture" checkout -qb other
git -C "$unrelated_fixture" config user.email ci-test@revenium.io
git -C "$unrelated_fixture" config user.name 'CI Test'
printf 'unrelated\n' >"$unrelated_fixture/other.txt"
git -C "$unrelated_fixture" add other.txt
git -C "$unrelated_fixture" commit -qm 'unrelated commit'
unrelated_sha="$(git -C "$unrelated_fixture" rev-parse HEAD)"
git -C "$fixture" fetch -q "$unrelated_fixture" other
(
  cd "$fixture"
  run_selector "$output" \
    EVENT_NAME=pull_request PR_BASE_SHA="$unrelated_sha" PR_HEAD_SHA="$feature_sha"
)
assert_output "$output" 'mode=full'
assert_output "$output" 'reason=pull request commit range cannot be traversed'
assert_warning "$output" '::warning::Gitleaks range unavailable: pull request commit range cannot be traversed. Falling back to a full-history scan.'

# The push event path shares emit_incremental_scan with pull_request, so the
# same two bug scenarios need equivalent push-event coverage.
(
  cd "$fixture"
  run_selector "$output" \
    EVENT_NAME=push PUSH_BEFORE_SHA="$feature_sha" PUSH_AFTER_SHA="$root_sha" PUSH_FORCED=false
)
assert_output "$output" 'mode=full'
assert_output "$output" 'reason=push commit range cannot be traversed'
assert_warning "$output" '::warning::Gitleaks range unavailable: push commit range cannot be traversed. Falling back to a full-history scan.'

(
  cd "$fixture"
  run_selector "$output" \
    EVENT_NAME=push PUSH_BEFORE_SHA="$unrelated_sha" PUSH_AFTER_SHA="$feature_sha" PUSH_FORCED=false
)
assert_output "$output" 'mode=full'
assert_output "$output" 'reason=push commit range cannot be traversed'
assert_warning "$output" '::warning::Gitleaks range unavailable: push commit range cannot be traversed. Falling back to a full-history scan.'

printf 'All Gitleaks range-selection tests passed.\n'
