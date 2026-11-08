#!/bin/bash
set -u
cd "$(dirname "$0")/.."
mode=${1:-run}
case "$mode" in download|run|diagnose|summarize) ;; *) printf 'usage: %s [download|run|diagnose|summarize]\n' "$0" >&2; exit 2;; esac
mkdir -p data/pilot
start=$(date -u +%FT%TZ)
deadline=$(date -u -d '+30 minutes' +%FT%TZ)
log=data/pilot/job.log
printf 'owner=%s purpose=%s pid=%s start=%s deadline=%s checkpoint=%s\n' "${USER:-unknown}" "$mode" "$$" "$start" "$deadline" 'data/pilot/pairs/*.json and counters.json' >> "$log"
timeout -k 20s 1800s uv run --locked python scripts/pilot.py "$mode" >> "$log" 2>&1
status=$?
printf 'finished=%s status=%s\n' "$(date -u +%FT%TZ)" "$status" >> "$log"
exit "$status"
