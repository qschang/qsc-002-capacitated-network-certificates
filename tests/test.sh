#!/bin/sh
set -eu
reward_file=/logs/verifier/reward.txt
mkdir -p "$(dirname "$reward_file")"
printf '0.000\n' > "$reward_file"
chmod 0444 "$reward_file" 2>/dev/null || true
cleanup() { code=$?; chmod 0644 "$reward_file" 2>/dev/null || true; if [ "$code" -eq 0 ]; then printf '1.000\n' > "$reward_file"; else printf '0.000\n' > "$reward_file"; fi; chmod 0444 "$reward_file" 2>/dev/null || true; exit "$code"; }
trap cleanup EXIT INT TERM HUP
timeout 240s python3 -m pytest -q "$(dirname "$0")/test_contract.py" --junitxml=/tmp/network-certificates-junit.xml
