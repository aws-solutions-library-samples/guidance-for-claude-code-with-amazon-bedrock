#!/usr/bin/env bash
# =============================================================================
# Hook Telemetry Shim — wraps any hook to emit start/end JSON to a telemetry log.
# =============================================================================
# Hook version: 1.0.0
# Last updated: 2026-05-29
# Purpose: Make hook execution observable so SREs can detect crashes, latency
#          regressions, and silent failures (the original audit-logger had
#          `exit 0` even on failure which masked real issues).
#
# Usage in managed-settings.json hooks block:
#   "command": "/usr/local/etc/claude-code/hooks/hook_wrapper.sh /usr/local/etc/claude-code/hooks/pii_prompt_guard.sh"
#
# Output: appends to $CLAUDE_HOOK_TELEMETRY (default /var/log/claude-code/hooks.jsonl)
#         each line: {ts, host, user, hook, event, session, duration_ms, exit_code, status}
#
# Status:
#   ok        — exit 0
#   blocked   — exit 2 (policy block, expected)
#   crashed   — exit other / non-zero with stderr captured (fail-closed)
#   timeout   — exceeded $CLAUDE_HOOK_TIMEOUT_MS
#
# Fail-closed contract: if the wrapped hook crashes (exit != 0/2), we exit 2 to
# block the tool. This converts silent hook failures into explicit denials, so
# operators get an alert instead of a silent miss.
# =============================================================================

set -u
HOOK="${1:-}"
[[ -z "$HOOK" || ! -x "$HOOK" ]] && {
  echo "hook-wrapper: missing or non-executable hook: $HOOK" >&2
  exit 2
}
shift

# Default is user-writable for plugin / opt-in mode; override in managed-settings
# to a root-owned path (/var/log/claude-code/hooks.jsonl) for enterprise SRE observability.
TELEMETRY="${CLAUDE_HOOK_TELEMETRY:-$HOME/.claude/claude-code-security/hooks.jsonl}"
TIMEOUT_MS="${CLAUDE_HOOK_TIMEOUT_MS:-5000}"
mkdir -p "$(dirname "$TELEMETRY")" 2>/dev/null || true
[[ ! -e "$TELEMETRY" ]] && touch "$TELEMETRY" 2>/dev/null

# Buffer stdin so we can both read it (extract event/session) and pass to hook
input=$(cat)
event=""
session=""
if command -v jq >/dev/null 2>&1; then
  event=$(printf '%s' "$input" | jq -r '.hook_event_name // empty' 2>/dev/null || true)
  session=$(printf '%s' "$input" | jq -r '.session_id // empty' 2>/dev/null || true)
fi

now_ms() { python3 -c 'import time;print(int(time.time()*1000))'; }
start_ms=$(now_ms)

# Invoke hook with timeout. macOS has no `timeout` by default; use Python.
tmpout=$(mktemp); tmperr=$(mktemp)
hook_name=$(basename "$HOOK")

run_with_timeout() {
  python3 - "$TIMEOUT_MS" "$HOOK" "$tmpout" "$tmperr" <<'PY' "$@"
import os, sys, subprocess
timeout_ms, hook = int(sys.argv[1]), sys.argv[2]
out_path, err_path = sys.argv[3], sys.argv[4]
extra = sys.argv[5:]
data = sys.stdin.read()
try:
    p = subprocess.run([hook]+extra, input=data, timeout=timeout_ms/1000.0,
                       capture_output=True, text=True)
    open(out_path,'w').write(p.stdout)
    open(err_path,'w').write(p.stderr)
    sys.exit(p.returncode)
except subprocess.TimeoutExpired:
    open(err_path,'w').write(f'hook timeout after {timeout_ms}ms')
    sys.exit(124)
PY
}

printf '%s' "$input" | run_with_timeout "$@"
rc=$?
end_ms=$(now_ms)
duration_ms=$((end_ms - start_ms))

case "$rc" in
  0)   status="ok" ;;
  2)   status="blocked" ;;
  124) status="timeout" ;;
  *)   status="crashed" ;;
esac

# Emit telemetry (best-effort; never block on this)
ts=$(date -u +"%Y-%m-%dT%H:%M:%S.%3NZ" 2>/dev/null || date -u +"%Y-%m-%dT%H:%M:%SZ")
host=$(hostname 2>/dev/null || echo unknown)
user=$(whoami 2>/dev/null || echo unknown)
err_excerpt=$(head -c 300 "$tmperr" 2>/dev/null || true)

if command -v jq >/dev/null 2>&1; then
  jq -nc \
    --arg ts "$ts" --arg host "$host" --arg user "$user" \
    --arg hook "$hook_name" --arg event "$event" --arg session "$session" \
    --argjson duration "$duration_ms" --argjson exit "$rc" \
    --arg status "$status" --arg err "$err_excerpt" \
    '{ts:$ts,host:$host,user:$user,hook:$hook,event:$event,session_id:$session,duration_ms:$duration,exit_code:$exit,status:$status,stderr:$err}' \
    >> "$TELEMETRY" 2>/dev/null || true
fi

# Pass stdout/stderr through to caller
cat "$tmpout"
cat "$tmperr" >&2
rm -f "$tmpout" "$tmperr"

# Fail-closed: convert crash/timeout into block (exit 2)
case "$rc" in
  0|2) exit "$rc" ;;
  *)   exit 2 ;;
esac
