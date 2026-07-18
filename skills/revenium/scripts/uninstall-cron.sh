#!/usr/bin/env bash
set -euo pipefail

# Remove EVERY Revenium metering crontab line — the legacy single-home marker
# (# hermes-revenium-metering) AND all per-profile fleet markers
# (# hermes-revenium-metering-<profile>). All of them contain the substring
# "hermes-revenium-metering", so one substring filter removes the whole fleet.
# This also clears BUG-7 orphans (lines pointing at a now-missing cron.sh).

CURRENT="$(crontab -l 2>/dev/null || true)"

COUNT=0
if [[ -n "${CURRENT}" ]]; then
  COUNT="$(printf '%s\n' "${CURRENT}" | grep -c "hermes-revenium-metering" || true)"
fi

if [[ "${COUNT}" -eq 0 ]]; then
  echo "No Revenium cron job found."
  exit 0
fi

# Materialize the survivors first (|| true — grep exits 1 when nothing survives,
# which is legitimate when the crontab held ONLY metering lines).
FILTERED="$(printf '%s\n' "${CURRENT}" | grep -v "hermes-revenium-metering" || true)"
if [[ -n "${FILTERED}" ]]; then
  printf '%s\n' "${FILTERED}" | crontab -
else
  # Nothing else in the crontab — remove it entirely.
  crontab -r 2>/dev/null || true
fi
echo "✅ Removed ${COUNT} Revenium metering cron line(s) (all profiles)."
