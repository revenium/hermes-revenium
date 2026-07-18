#!/usr/bin/env bash
set -euo pipefail

workspace="${GITHUB_WORKSPACE:-$(pwd)}"
report_path="${workspace}/gitleaks-report.sarif"
docker_bin="${GITLEAKS_DOCKER_BIN:-docker}"
image="${GITLEAKS_DOCKER_IMAGE:-ghcr.io/gitleaks/gitleaks:v8.30.1}"

case "${SCAN_MODE:-}" in
  incremental)
    if [[ ! "${COMMIT_RANGE:-}" =~ ^[0-9a-fA-F]{40,64}\.\.[0-9a-fA-F]{40,64}$ ]]; then
      printf '::error::Incremental Gitleaks mode received an invalid commit range.\n' >&2
      exit 2
    fi
    log_opts="--diff-merges=separate ${COMMIT_RANGE}"
    printf 'Scanning PR/push commit range: %s\n' "$COMMIT_RANGE"
    ;;
  full)
    log_opts="--all --diff-merges=separate"
    printf 'Scanning full repository history.\n'
    ;;
  *)
    printf '::error::Unknown Gitleaks scan mode: %s\n' "${SCAN_MODE:-missing}" >&2
    exit 2
    ;;
esac

# Never leave a report from a prior attempt available to the upload step.
rm -f -- "$report_path"

set +e
"$docker_bin" run --rm \
  -v "${workspace}:/repo" \
  "$image" \
  git \
    --log-opts="$log_opts" \
    --redact \
    --verbose \
    --report-format=sarif \
    --report-path=/repo/gitleaks-report.sarif \
    --exit-code=1 \
    /repo
scan_status=$?
set -e

validate_report() {
  if [[ ! -s "$report_path" ]]; then
    printf '::error::Gitleaks did not produce a non-empty SARIF report.\n' >&2
    return 1
  fi

  # The exact SARIF version is pinned to what gitleaks v8.30.1 (see $image
  # above) emits today. If that image tag is ever bumped, re-check this
  # version string against the new release's SARIF output before assuming
  # a mismatch here still means "invalid report."
  if ! jq -e '
    .version == "2.1.0" and
    (.runs | type == "array") and
    (.runs | length > 0) and
    (all(.runs[]?; .tool.driver.name == "gitleaks"))
  ' "$report_path" >/dev/null; then
    printf '::error::Gitleaks produced an invalid or unexpected SARIF report.\n' >&2
    return 1
  fi
}

if ! validate_report; then
  rm -f -- "$report_path"
  exit 2
fi

if [[ "$scan_status" -eq 0 ]]; then
  exit 0
fi

if [[ "$scan_status" -eq 1 ]]; then
  finding_count="$(jq '[.runs[]?.results[]?] | length' "$report_path")"
  if [[ "$finding_count" -eq 0 ]]; then
    printf '::error::Gitleaks exited with the findings code but reported no findings.\n' >&2
    rm -f -- "$report_path"
    exit 2
  fi

  printf '::warning::Gitleaks found %s potential secret(s); retaining report-only enforcement.\n' "$finding_count" >&2
  exit 0
fi

printf '::error::Gitleaks failed operationally with exit code %s; no SARIF will be uploaded.\n' "$scan_status" >&2
rm -f -- "$report_path"
exit "$scan_status"
