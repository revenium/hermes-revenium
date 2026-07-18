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
    warn_and_scan_full "${reason} commit range cannot be traversed"
    return
  fi

  commit_range="${base_sha}..${head_sha}"
  emit_result "incremental" "$commit_range" "$reason"
}

case "${EVENT_NAME:-}" in
  pull_request)
    emit_incremental_scan "${PR_BASE_SHA:-}" "${PR_HEAD_SHA:-}" "pull request"
    ;;
  push)
    if [[ "${PUSH_FORCED:-false}" == "true" ]]; then
      warn_and_scan_full "forced push"
    elif [[ -z "${PUSH_BEFORE_SHA:-}" || "${PUSH_BEFORE_SHA}" == "$zero_sha" ]]; then
      warn_and_scan_full "push before SHA is missing or zero"
    else
      emit_incremental_scan "${PUSH_BEFORE_SHA}" "${PUSH_AFTER_SHA:-}" "push"
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
