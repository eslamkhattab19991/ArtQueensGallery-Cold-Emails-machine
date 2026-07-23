#!/usr/bin/env bash
# Map every site in a batch.
#
# Sequential, not parallel. The first version of this script ran two at a time
# against the account's stated concurrency limit of 2 and every request after
# the sixth failed; the same URLs succeed one at a time. The limit evidently
# applies more tightly than the status line suggests, and a spike is not the
# place to fight it — correctness beats speed here.
#
# Results are cached per row, so a re-run resumes rather than re-paying.
# Failures are recorded, never fatal: an unreachable site is a finding.

set -uo pipefail

BATCH_FILE="${1:?usage: run_maps.sh <batch.json>}"
OUT_DIR="$(dirname "$0")/out/maps"
mkdir -p "$OUT_DIR"

mapfile -t ENTRIES < <(python -c "
import json, sys
for org in json.load(open(sys.argv[1], encoding='utf-8')):
    print(f\"{org['row']}\t{org['website']}\"
)" "$BATCH_FILE")

for entry in "${ENTRIES[@]}"; do
    row="${entry%%$'\t'*}"
    url="${entry##*$'\t'}"
    target="$OUT_DIR/row_${row}.json"

    if [[ -s "$target" ]] && grep -q '"success":true' "$target" 2>/dev/null; then
        echo "  row ${row}: cached"
        continue
    fi

    if timeout 120 firecrawl map "$url" --search "artist" --json > "$target" 2>/dev/null \
       && grep -q '"success":true' "$target" 2>/dev/null; then
        count=$(python -c "
import json,sys
try:
    d=json.load(open(sys.argv[1],encoding='utf-8'))
    print(len(d.get('data',{}).get('links',[])))
except Exception:
    print(0)
" "$target")
        echo "  row ${row}: ok (${count} links)"
    else
        echo '{"success": false, "error": "map failed or timed out"}' > "$target"
        echo "  row ${row}: FAILED"
    fi
    sleep 8
done

echo "maps complete -> $OUT_DIR"
