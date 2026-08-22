## What this changes

<!-- And why. If it fixes an issue, link it. -->

## How it was verified

<!-- What you ran, and what it said. -->

- [ ] `python3 -m unittest discover -s tests -p 'test_*.py'`
- [ ] Tried on a live host (say which: single profile / fleet / multiplexed)
- [ ] Manual halt-survivability runbook — only if `SKILL.md`'s halt block changed

## Invariants

<!-- Delete any line that doesn't apply. -->

- [ ] New state paths are declared in `scripts/common.sh`, not inline
- [ ] Metering stays idempotent — re-running the cron does not double-report
- [ ] Golden argv fixtures updated deliberately, or unchanged
- [ ] New CLI flags are capability-probed and fail open
- [ ] New scripts are in `test_expected_files_exist`, executable, and parse under `bash -n`
