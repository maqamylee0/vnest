#!/bin/bash
# Records the phone log and force-stops the VNeST app if a generation produces no first token within LIMIT seconds,
# so a stuck GPU can't trigger Android's system watchdog (which restarts the phone; RESEARCH_LOG Entry 6). Runs until killed.
# Usage: tools/phone_hang_guard.sh <log file> [LIMIT seconds, default 90]
# Writes the full log to <log file> and guard events to <log file>.guard.
A=~/Android/Sdk/platform-tools/adb
OUT=${1:?log file}
LIMIT=${2:-90}
start=""
$A logcat -v time 2>&1 | while IFS= read -r line; do
  echo "$line" >> "$OUT"
  case "$line" in
    *"VnestLlm"*"generate start"*) start=$(date +%s); echo "GUARD $(date +%T) armed" >> "$OUT.guard" ;;
    *"VnestLlm"*"first token"*|*"VnestLlm"*"generate done"*) [ -n "$start" ] && echo "GUARD $(date +%T) ok after $(( $(date +%s) - start )) s" >> "$OUT.guard"; start="" ;;
  esac
  if [ -n "$start" ] && [ $(( $(date +%s) - start )) -ge "$LIMIT" ]; then
    $A shell am force-stop rw.ongera.vnest_app
    echo "GUARD $(date +%T) no first token after ${LIMIT}s -> force-stopped app" >> "$OUT.guard"
    start=""
  fi
done
