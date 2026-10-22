#!/bin/sh
set -eu
REWARD_FILE=/logs/verifier/reward.txt
REPORT=/logs/verifier/network-certificates-junit.xml
REPORT_TMP="${REPORT}.tmp.$$"
mkdir -p /logs/verifier
printf '0.000\n' > "$REWARD_FILE"
write_zero() { printf '0.000\n' > "$REWARD_FILE"; rm -f "$REPORT_TMP"; }
trap 'write_zero; exit 1' INT TERM HUP
write_zero
cd "$(dirname "$0")"
set +e
timeout 240s python3 -B -I -m pytest -q -p no:cacheprovider -c /dev/null ./test_contract.py --junitxml="$REPORT_TMP" >/logs/verifier/pytest.log 2>&1
pytest_rc=$?
set -e
if [ "$pytest_rc" -ne 0 ] || [ ! -s "$REPORT_TMP" ]; then write_zero; exit "$pytest_rc"; fi
if ! python3 -B -I ./verify_junit.py "$REPORT_TMP"; then write_zero; exit 1; fi
mv -f "$REPORT_TMP" "$REPORT"
if ! python3 -B -I ./score.py --config ./scoring.json --junit "$REPORT" --report-out /logs/verifier/scoring-report.json --reward-out "$REWARD_FILE"; then write_zero; exit 1; fi
trap - INT TERM HUP
