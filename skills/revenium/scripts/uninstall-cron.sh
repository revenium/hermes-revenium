#!/usr/bin/env bash
set -euo pipefail

if ! crontab -l 2>/dev/null | grep -q "hermes-revenium-metering"; then
  echo "No Revenium cron job found."
  exit 0
fi

crontab -l 2>/dev/null | grep -v "hermes-revenium-metering" | crontab -
echo "✅ Revenium metering cron removed."
