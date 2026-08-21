#!/usr/bin/env bash
set -euo pipefail
# bootstrap.sh — BUG-5 fix: fetch the parts of the skill that
# `hermes skills install` does NOT ship.
#
# `hermes skills install revenium/hermes-revenium/skills/revenium` fetches only
# SKILL.md + references/ — it does NOT include scripts/ or plugins/. So the
# documented setup step (`bash ~/.hermes/skills/revenium/scripts/install.sh`)
# fails on a clean skills-install because scripts/ and plugins/ are absent.
#
# This script lives in references/ (which IS fetched), self-locates the installed
# skill dir, clones the repo, populates scripts/ + plugins/ (+ the taxonomy
# seeds) into it, and then hands off to scripts/install.sh. All flags pass
# through. Idempotent: if scripts/ and plugins/ are already present it skips
# straight to install.sh.
#
# Standalone alternative (no skill installed yet):
#   git clone --depth 1 https://github.com/revenium/hermes-revenium.git /tmp/hr \
#     && bash /tmp/hr/install.sh
#
# This is intentionally NOT sourcing scripts/common.sh — it runs BEFORE scripts/
# exists on the host.

REPO="${REVENIUM_SKILL_REPO:-https://github.com/revenium/hermes-revenium.git}"
REF="${REVENIUM_SKILL_REF:-main}"

# Resolve the installed skill dir: parent of this references/ dir, or the default.
if [[ -n "${BASH_SOURCE[0]:-}" && -f "${BASH_SOURCE[0]}" ]]; then
  DEST="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
else
  DEST="${HERMES_SKILL_DIR:-${HERMES_HOME:-${HOME}/.hermes}/skills/revenium}"
fi
mkdir -p "${DEST}"

echo "▸ Revenium skill bootstrap → ${DEST}"

# --update / --refresh re-fetches even when the tree is already populated.
# Without it, the presence check below is a permanent latch: a host installed
# once keeps running whatever scripts/ it got that day, and every later
# `hermes skills install` + bootstrap silently hands off to the OLD installer.
# Nothing errors, so a stale host is indistinguishable from a current one.
FORCE_FETCH=false
PASSTHRU=()
for arg in "$@"; do
  case "${arg}" in
    --update|--refresh) FORCE_FETCH=true ;;
    *) PASSTHRU+=("${arg}") ;;
  esac
done
set -- ${PASSTHRU+"${PASSTHRU[@]}"}

need_fetch="${FORCE_FETCH}"
[[ -f "${DEST}/scripts/install.sh" ]] || need_fetch=true
[[ -d "${DEST}/plugins/revenium-classifier" ]] || need_fetch=true

if ${need_fetch}; then
  if ! command -v git >/dev/null 2>&1; then
    echo "ERROR: git is required to fetch scripts/ and plugins/." >&2
    echo "  Install git, or clone the repo manually and run install.sh:" >&2
    echo "    git clone --depth 1 ${REPO} /tmp/hermes-revenium && bash /tmp/hermes-revenium/install.sh" >&2
    exit 1
  fi
  tmp="$(mktemp -d)"
  trap 'rm -rf "${tmp}"' EXIT
  echo "  Cloning ${REPO} (${REF}) …"
  # First attempt is silenced: failing because ${REF} is not a branch/tag is the
  # routine fallback path, not an error worth showing. The fallback clone's stderr
  # IS surfaced — if that one fails too, its message (auth, 404, network, TLS) is
  # the only diagnostic the user gets.
  git clone --depth 1 --branch "${REF}" "${REPO}" "${tmp}" >/dev/null 2>&1 \
    || git clone --depth 1 "${REPO}" "${tmp}" \
    || { echo "ERROR: git clone failed for ${REPO}" >&2; exit 1; }

  src="${tmp}/skills/revenium"
  [[ -d "${src}/scripts" && -d "${src}/plugins" ]] \
    || { echo "ERROR: cloned repo missing scripts/ or plugins/ at ${src}" >&2; exit 1; }

  # Copy in. references/ + SKILL.md are already present from
  # `hermes skills install`; only scripts/ and plugins/ are added here.
  #
  # cp -R over the existing dirs rather than rm -rf + copy: operators keep
  # host-only scripts alongside the shipped ones (a fleet cron wrapper, for
  # instance) that exist in no clone, and blowing the directory away to
  # "refresh" it silently deletes them — taking the fleet's metering with it.
  # Overlaying updates every shipped file and leaves anything else untouched.
  mkdir -p "${DEST}/scripts" "${DEST}/plugins"
  cp -R "${src}/scripts/." "${DEST}/scripts/"
  cp -R "${src}/plugins/." "${DEST}/plugins/"
  for seed in task-taxonomy.json job-taxonomy.json; do
    [[ -f "${src}/${seed}" ]] && cp -f "${src}/${seed}" "${DEST}/${seed}"
  done
  # Drop any __pycache__ carried by cp -R so a stale .pyc can't shadow source.
  find "${DEST}" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
  chmod +x "${DEST}/scripts/"*.sh 2>/dev/null || true
  echo "  ✓ Populated scripts/ and plugins/ (host-only files preserved)"
else
  echo "  ✓ scripts/ and plugins/ already present — skipping fetch."
  echo "    (re-run with --update to pull the latest from ${REPO})"
fi

echo "▸ Handing off to scripts/install.sh"
exec bash "${DEST}/scripts/install.sh" "$@"
