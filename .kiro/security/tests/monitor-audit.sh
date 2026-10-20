#!/usr/bin/env bash
#
# Layer 4 — simple monitor/alert on new outside-access audit entries.
#
# Prints new lines appended to the audit log since the last run (tracked via a
# small cursor file). Intended to be run on a cadence (cron, a Stop hook, or
# manually) so outside-boundary attempts don't go unnoticed. Exits non-zero when
# new entries are found, so it can drive an alert.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"

AUDIT_DIR="${KIRO_AUDIT_DIR:-$(dirname "${PROJECT_ROOT}")/.kiro-agent-audit}"
AUDIT_LOG="${AUDIT_DIR}/outside-access.log"
CURSOR="${AUDIT_DIR}/.monitor-cursor"

[ -f "${AUDIT_LOG}" ] || { echo "No audit log yet at ${AUDIT_LOG} — nothing to monitor."; exit 0; }

TOTAL="$(wc -l < "${AUDIT_LOG}" | tr -d ' ')"
SEEN=0
[ -f "${CURSOR}" ] && SEEN="$(cat "${CURSOR}" 2>/dev/null || echo 0)"

if [ "${TOTAL}" -gt "${SEEN}" ]; then
  NEW=$((TOTAL - SEEN))
  echo "ALERT: ${NEW} new outside-access attempt(s) recorded:"
  tail -n "${NEW}" "${AUDIT_LOG}" | sed 's/^/  /'
  echo "${TOTAL}" > "${CURSOR}" 2>/dev/null || true
  exit 1
fi

echo "No new outside-access attempts since last check (${TOTAL} total)."
exit 0
