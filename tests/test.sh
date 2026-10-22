#!/bin/sh
set -eu
REWARD_FILE=/logs/verifier/reward.txt
REPORT=/logs/verifier/network-certificates-junit.xml
REPORT_TMP="${REPORT}.tmp.$$"
STATUS=/logs/verifier/verification-status.txt
mkdir -p /logs/verifier
printf '0.000\n' > "$REWARD_FILE"
write_zero() { printf '0.000\n' > "$REWARD_FILE"; rm -f "$REPORT_TMP"; }
write_status() { printf '%s\n' "$1" > "$STATUS"; }
trap 'write_zero; exit 1' INT TERM HUP
write_zero
write_status "INCOMPLETE: pytest has not completed"
cd "$(dirname "$0")"
set +e
timeout 240s python3 -B -I -m pytest -q -p no:cacheprovider -c /dev/null ./test_contract.py --junitxml="$REPORT_TMP" >/logs/verifier/pytest.log 2>&1
pytest_rc=$?
set -e
if [ "$pytest_rc" -ne 0 ] || [ ! -s "$REPORT_TMP" ]; then write_status "INCOMPLETE: pytest did not complete"; write_zero; exit "$pytest_rc"; fi
if ! python3 -B -I ./verify_junit.py "$REPORT_TMP"; then write_status "INCOMPLETE: junit rejected"; write_zero; exit 1; fi
mv -f "$REPORT_TMP" "$REPORT"
if ! python3 -B -I ./score.py --config ./scoring.json --junit "$REPORT" --report-out /logs/verifier/scoring-report.json --reward-out "$REWARD_FILE"; then write_status "INCOMPLETE: weighted scoring rejected report"; write_zero; exit 1; fi
write_status "COMPLETED: weighted scoring finished"
trap - INT TERM HUP
