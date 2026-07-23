#!/usr/bin/env bash
# Wait for the current chain pass to finish, then run the expanded sample.
# The per-artist cache makes the second pass resume rather than repeat.
set -uo pipefail
cd "$(dirname "$0")/../.."
until [ "$(ls spikes/roster_probe/out/chain/*.json 2>/dev/null | wc -l)" -ge 42 ]; do sleep 8; done
cp spikes/roster_probe/out/chain_sample_big.json spikes/roster_probe/out/chain_sample.json
PYTHONIOENCODING=utf-8 python spikes/roster_probe/chain.py
