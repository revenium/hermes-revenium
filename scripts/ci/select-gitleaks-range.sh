#!/usr/bin/env bash
set -euo pipefail

# Select the smallest trustworthy history range for Gitleaks. This script only
# emits ranges made from validated commit object IDs; event values are never
# evaluated as shell source.

output_file="${GITHUB_OUTPUT:-/dev/stdout}"
zero_sha="0000000000000000000000000000000000000000"

emit_result() {
  local mode="$1"
  local commit_range="$2"
  local reason="$3"

  {
    printf 'mode=%s\n' "$mode"
    printf 'commit_range=%s\n' "$commit_range"
    printf 'reason=%s\n' "$reason"
  } >>"$output_file"
}

emit_full_scan() {
  local reason="$1"

  emit_result "full" "" "$reason"
}

warn_and_scan_full() {
  local reason="$1"

  printf '::warning::Gitleaks range unavailable: %s. Falling back to a full-history scan.\n' "$reason" >&2
  emit_full_scan "$reason"
}

is_commit() {
  local sha="$1"

  # The hex-only anchor below is a security control, not just format
  # validation: run-gitleaks.sh forwards commit_range into gitleaks'
  # --log-opts, which it passes straight to `git log`. Loosening this
  # pattern re-opens a shell/git-argument injection path via event-derived
  # SHAs (e.g. a crafted PR base/head SHA or push before/after SHA).
  [[ "$sha" =~ ^[0-9a-fA-F]{40,64}$ ]] &&
    git cat-file -e "${sha}^{commit}" 2>/dev/null
}

emit_incremental_scan() {
  local base_sha="$1"
  local head_sha="$2"
  local reason="$3"
  local allow_merge_base="$4"
  local commit_range

  if ! is_commit "$base_sha"; then
    warn_and_scan_full "${reason} base SHA is missing or unavailable"
    return
  fi

  if ! is_commit "$head_sha"; then
    warn_and_scan_full "${reason} head SHA is missing or unavailable"
    return
  fi

  # `git rev-list --quiet base..head` is NOT an ancestry check: it exits 0
  # for any two valid commits, including unrelated histories, and silently
  # yields an empty range when base is ahead of head. Use --is-ancestor,
  # which actually fails when base is not an ancestor of head, so those
  # cases fall back to a full scan instead of silently scanning nothing.
  if ! git merge-base --is-ancestor "$base_sha" "$head_sha" 2>/dev/null; then
    if [[ "$allow_merge_base" == "true" ]]; then
      emit_merge_base_scan "$base_sha" "$head_sha" "$reason" && return
    fi
    warn_and_scan_full "${reason} commit range cannot be traversed"
    return
  fi

  commit_range="${base_sha}..${head_sha}"
  emit_result "incremental" "$commit_range" "$reason"
}

# For a stacked PR, the base branch can advance past the point the head
# branch was cut from, which fails the --is-ancestor check above even
# though the PR's own commits are well-defined: merge_base(base,head)..head.
# Falling all the way back to a full-history scan on every such PR is
# what BACK-2713 fixes (a ~49k-commit full scan vs. a few PR commits).
# This is only ever invoked from the pull_request call site
# (allow_merge_base="true"); the push path never reaches here.
emit_merge_base_scan() {
  local base_sha="$1"
  local head_sha="$2"
  local reason="$3"
  local mb
  local canonical_head

  mb="$(git merge-base "$base_sha" "$head_sha" 2>/dev/null | head -n 1 || true)"

  if [[ -z "$mb" ]]; then
    # No common ancestor at all (unrelated histories) — nothing to salvage.
    return 1
  fi

  # git merge-base always prints lowercase hex, but an event-supplied
  # head_sha isn't guaranteed to match case, so compare against git's own
  # canonical (lowercase) resolution of head_sha rather than the raw input.
  canonical_head="$(git rev-parse --verify "${head_sha}^{commit}" 2>/dev/null || true)"

  if [[ -z "$canonical_head" || "$mb" == "$canonical_head" ]]; then
    # mb == head means head is an ancestor of base (base is AHEAD of head):
    # merge_base..head would be an EMPTY range, and gitleaks would silently
    # scan nothing and report clean. Must fall back to full history instead.
    return 1
  fi

  # Re-validate mb through is_commit before it can reach gitleaks'
  # --log-opts (see the security comment on is_commit above) — merge-base's
  # own output is trusted, but every SHA that reaches the range still has
  # to pass the same hex-only anchor as event-derived SHAs.
  if ! is_commit "$mb"; then
    return 1
  fi

  printf '::notice::Gitleaks scanning from the merge base: the base branch has advanced past this branch. Range: %s..%s\n' \
    "$mb" "$head_sha" >&2
  emit_result "incremental" "${mb}..${head_sha}" "${reason} (base branch advanced; scanned from merge base)"
}

case "${EVENT_NAME:-}" in
  pull_request)
    emit_incremental_scan "${PR_BASE_SHA:-}" "${PR_HEAD_SHA:-}" "pull request" "true"
    ;;
  push)
    if [[ "${PUSH_FORCED:-false}" == "true" ]]; then
      warn_and_scan_full "forced push"
    elif [[ -z "${PUSH_BEFORE_SHA:-}" || "${PUSH_BEFORE_SHA}" == "$zero_sha" ]]; then
      warn_and_scan_full "push before SHA is missing or zero"
    else
      # Scoped out of BACK-2713: for a non-forced push to develop, `before`
      # failing to be an ancestor of `after` is an anomaly (not the normal
      # stacked-PR shape), so keep the full-history fail-safe here.
      emit_incremental_scan "${PUSH_BEFORE_SHA}" "${PUSH_AFTER_SHA:-}" "push" "false"
    fi
    ;;
  schedule)
    emit_full_scan "scheduled full-history scan"
    ;;
  workflow_dispatch)
    emit_full_scan "manual full-history scan"
    ;;
  *)
    warn_and_scan_full "unsupported event '${EVENT_NAME:-missing}'"
    ;;
esac
