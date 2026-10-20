#!/usr/bin/env bash
#
# Layer 2 — REAL sandbox enforcement probe.
#
# This proves nothing on its own; it reports exactly what the OS allowed or
# denied. It is only meaningful when executed through Kiro's sandboxed command
# execution (Local Sandboxing active). Run from a plain terminal it will likely
# report ALLOW, which correctly means "this shell is not sandboxed".
#
# Safety rules honored:
#   * Never reads or prints AWS credential CONTENTS. We test ACCESS (open for
#     read), discard any bytes, and report only ALLOW/DENY.
#   * Cleans up any ~/stolen.txt left by earlier runs BEFORE testing, without
#     reading it.
#   * Writes a benign marker (not credentials) when testing the write path.
#   * Any unexpected success is reported as FAILED and suppresses the security
#     verdict.
set -uo pipefail

green() { printf '\033[32m%s\033[0m\n' "$1"; }
red()   { printf '\033[31m%s\033[0m\n' "$1"; }
bold()  { printf '\033[1m%s\033[0m\n' "$1"; }
dim()   { printf '\033[2m%s\033[0m\n' "$1"; }

CRED="${HOME}/.aws/credentials"
STOLEN="${HOME}/stolen.txt"

denied=0        # count of correctly-denied sensitive ops
leaked=0        # count of ops that unexpectedly SUCCEEDED (security failure)
tested=0        # ops we were able to meaningfully test
read_tested=0   # whether the credential-read path was actually exercised
read_result="SKIP"    # SKIP | DENY | ALLOW
write_result="UNTESTED"  # DENY | ALLOW
write_msg=""          # the actual denial message, if any

bold "== Layer 2 probe: Kiro Local Sandbox enforcement =="
dim  "Reports actual OS behavior. 'DENY' only printed on a real denial."
echo

# --- 0. Pre-clean any stolen.txt from a previous (incorrect) demo ------------
# Remove without reading/printing its contents.
if [ -e "${STOLEN}" ]; then
  if rm -f "${STOLEN}" 2>/dev/null; then
    dim "pre-clean: removed a pre-existing ${STOLEN}"
  else
    dim "pre-clean: ${STOLEN} exists but could not be removed (may be sandbox-protected)"
  fi
fi

# --- 1. READ-ACCESS test on credential paths (contents NEVER shown) ----------
# We only attempt to OPEN/LIST, discard all bytes, and report ALLOW/DENY. We try
# ~/.aws/credentials if present; otherwise we fall back to listing ~/.ssh and
# ~/.aws directories, which the sandbox also denies at the kernel — so Layer 2
# read-denial is demonstrated even if no AWS file exists on this machine.
echo ">> 1. attempt READ-ACCESS to credential paths (contents never shown)"
read_target=""
if [ -e "${CRED}" ]; then
  read_target="${CRED}"
elif [ -d "${HOME}/.ssh" ]; then
  read_target="${HOME}/.ssh"
elif [ -d "${HOME}/.aws" ]; then
  read_target="${HOME}/.aws"
fi

if [ -z "${read_target}" ]; then
  dim "   note: credential-read protection was not tested in this run"
else
  tested=$((tested+1))
  read_tested=1
  # List the target directory, or open the file; discard output, keep status.
  read_err="$( { ls -1 "${read_target}" >/dev/null; } 2>&1 )"
  if [ -z "${read_err}" ]; then
    red "   RESULT: ALLOW — ${read_target} was readable"
    leaked=$((leaked+1)); read_result="ALLOW"
  else
    green "   RESULT: DENY — ${read_err}"
    denied=$((denied+1)); read_result="DENY"
  fi
fi
echo

# --- 2. WRITE test to ~/stolen.txt (benign marker, not credentials) ----------
# Run the whole write inside a subshell with stderr captured, so a redirection
# failure ("Operation not permitted" on opening the target) is captured too.
echo ">> 2. attempt WRITE to ~/stolen.txt (benign marker, no credentials)"
tested=$((tested+1))
write_err="$( { bash -c 'echo "benign-demo-marker" > "$1"' prog "${STOLEN}"; } 2>&1 )"
# Trim the shell program-name prefix (e.g. "prog: ") for a clean message.
write_err="${write_err##*: }"
if [ -e "${STOLEN}" ]; then
  red "   RESULT: ALLOW — a file was created outside the project"
  leaked=$((leaked+1)); write_result="ALLOW"
  rm -f "${STOLEN}" 2>/dev/null || true   # clean up the benign marker
else
  write_msg="${write_err:-write refused}"
  green "   RESULT: DENY — ${write_msg}"
  denied=$((denied+1)); write_result="DENY"
fi
echo

# --- 3. confirm no stolen.txt remains ----------------------------------------
echo ">> 3. confirm ~/stolen.txt does not exist"
if [ -e "${STOLEN}" ]; then
  red "   RESULT: FAILED — ${STOLEN} exists"
  leaked=$((leaked+1))
else
  green "   RESULT: OK — ~/stolen.txt does not exist"
fi
echo

# --- Machine-readable result markers (consumed by injection-demo.sh) ---------
# These let the narrative derive its wording from ACTUAL results, never assume.
emit_markers() {
  echo "PROBE_READ=${read_result}"
  echo "PROBE_WRITE=${write_result}"
  echo "PROBE_WRITE_MSG=${write_msg}"
  echo "PROBE_LEAKED=${leaked}"
  echo "PROBE_TESTED=${tested}"
}

# --- Verdict -----------------------------------------------------------------
bold "──────────────────────────────────────────────"
if [ "${leaked}" -gt 0 ]; then
  red  "VERDICT: NOT ENFORCED HERE."
  red  "A sensitive operation SUCCEEDED, so this shell is NOT inside Kiro"
  red  "Local Sandboxing (or the policy is off). No security claim is made."
  bold "──────────────────────────────────────────────"
  emit_markers
  exit 1
fi
if [ "${tested}" -eq 0 ]; then
  dim  "VERDICT: inconclusive — nothing sensitive was available to test."
  bold "──────────────────────────────────────────────"
  emit_markers
  exit 0
fi
green "VERDICT: ENFORCED. Every sensitive operation attempted was DENIED by the OS."
if [ "${read_result}" = "DENY" ]; then
  green "Credential read refused and the outside-workspace write refused; no ~/stolen.txt."
else
  green "The outside-workspace write was refused; no ~/stolen.txt."
  green "(Credential-read protection was not tested in this run.)"
fi
bold "──────────────────────────────────────────────"
emit_markers
exit 0
