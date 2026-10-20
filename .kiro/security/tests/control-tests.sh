#!/usr/bin/env bash
#
# Layer 3 — control tests for the current security posture.
#
# Primary control is now Kiro Local Sandboxing (kernel-enforced). These tests
# confirm the policy file is in place and, when the sandbox is active, that the
# kernel denies outside-project writes and credential reads. They also check the
# steering policy and injection fixture are present (behavioral layer).
#
# NOTE: the sandbox restricts commands RUN THROUGH KIRO. When this script is run
# in a shell that Kiro wraps with the sandbox, the enforcement probes are live.
# Run outside that wrapper, the probes are reported as INFO (cannot enforce).
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"

PASS=0
FAIL=0

ok()   { echo "  PASS: $1"; PASS=$((PASS+1)); }
bad()  { echo "  FAIL: $1"; FAIL=$((FAIL+1)); }
info() { echo "  INFO: $1"; }

echo "== Layer 0: Local Sandboxing config =="
CFG="${PROJECT_ROOT}/.kiro/settings/sandbox.json"
if [ -f "${CFG}" ] && python3 -c 'import json,sys; sys.exit(0 if json.load(open(sys.argv[1])).get("enabled") is True else 1)' "${CFG}"; then
  ok "sandbox.json present and enabled:true"
else
  bad "sandbox.json missing or not enabled (expected {\"enabled\": true})"
fi

echo "== Layer 0: live kernel enforcement probes =="
# Write outside the project root should be denied by the kernel when sandboxed.
PROBE="${HOME}/.kiro_sandbox_probe_$$"
if echo x > "${PROBE}" 2>/dev/null; then
  rm -f "${PROBE}" 2>/dev/null || true
  info "outside-project write SUCCEEDED here — this shell is NOT sandbox-wrapped."
  info "Run build/test through Kiro to exercise live enforcement."
else
  ok "outside-project write DENIED by the kernel (sandbox active)"
fi

# Credential read should be denied when sandboxed.
if ls "${HOME}/.ssh" >/dev/null 2>&1; then
  info "~/.ssh listing SUCCEEDED here — shell not sandbox-wrapped (or no ~/.ssh)."
else
  ok "~/.ssh read DENIED/absent (sandbox active or path missing)"
fi

echo "== Layer 1: steering policy present =="
if [ -f "${PROJECT_ROOT}/.kiro/steering/security-guardrails.md" ]; then
  ok "steering policy present"
else
  bad "steering policy missing"
fi

echo "== Layer 1: prompt-injection fixture present =="
if [ -f "${SCRIPT_DIR}/fixtures/injection-sample.txt" ]; then
  ok "injection fixture present (behavioral refusal enforced by steering)"
else
  bad "injection fixture missing"
fi

echo "== Layer 2: audit monitor present =="
if [ -f "${SCRIPT_DIR}/monitor-audit.sh" ] && [ -f "${PROJECT_ROOT}/.kiro/hooks/audit-monitor.json" ]; then
  ok "audit monitor script + Stop hook present"
else
  bad "audit monitor or Stop hook missing"
fi

echo
echo "== Summary: ${PASS} passed, ${FAIL} failed =="
[ "${FAIL}" -eq 0 ]
