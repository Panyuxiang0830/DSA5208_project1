#!/usr/bin/env bash
# Archive the raw per-operation JSONL logs (results/raw/) and the
# machine-readable summaries (results/summary/) into one timestamped tar.gz.
#
# results/raw/*.jsonl is intentionally excluded from Git (see .gitignore) --
# it is the only place the ~40 MB of individual operation records live, and
# it currently exists only on this VM / this machine. If the VM is stopped
# or deleted before the raw logs are backed up, that evidence is gone even
# though the committed results/summary/*.json (computed from it) survives.
#
# Run this before stopping/deleting the experiment VM, and copy the
# resulting archive off the VM (e.g. `gcloud compute scp`, or upload it to
# the same cloud storage / drive the team already uses for the report).
#
# Usage:
#   ./scripts/archive_raw_results.sh [output-directory]
#
# Defaults to writing into ./archives/ at the repository root.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="${1:-${ROOT}/archives}"
mkdir -p "${OUT_DIR}"

TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
ARCHIVE="${OUT_DIR}/dsa5208-raw-results-${TIMESTAMP}.tar.gz"

if [[ ! -d "${ROOT}/results/raw" ]] || [[ -z "$(ls -A "${ROOT}/results/raw" 2>/dev/null | grep -v '^\.gitkeep$')" ]]; then
  echo "Warning: results/raw/ has no JSONL files to archive (only .gitkeep or missing)." >&2
  echo "Nothing to back up yet -- run the experiments first." >&2
fi

tar -czf "${ARCHIVE}" \
  -C "${ROOT}" \
  results/raw \
  results/summary

echo "Wrote ${ARCHIVE}"
echo "Copy this file off the VM before stopping or deleting it -- it is the"
echo "only complete copy of the raw per-operation evidence behind the"
echo "committed summary JSON and the PDF report."
