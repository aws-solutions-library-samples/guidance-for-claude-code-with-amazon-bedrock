#!/usr/bin/env bash
# =============================================================================
# Audit Logger — Tamper-evident, fail-closed audit log for Claude Code
# =============================================================================
# Hook version: 2.0.0
# Last updated: 2026-05-29
# Compatible with: claude-code 2.1.150+
# Dependencies: bash 4+, jq, openssl (HMAC), aws CLI (optional, for CloudWatch)
# Maintainer: AWS Solutions Library (contributed via #494)
# Change log:
#   2.0.0 (2026-05-29) — HMAC chain, fail-closed, mandatory SIEM, CloudWatch dual-write,
#                        prev_hash stored under /var/lib/claude-code/audit-state
#   1.0.0 (2026-05-28) — initial release
# =============================================================================
# Each event line is a JSON object that includes:
#   - prev_hash: HMAC-SHA256 of the previous event line (or "GENESIS")
#   - hmac:      HMAC-SHA256(key, prev_hash || event_body_canonical)
# Verifying the chain (chain_verify.sh) detects ANY post-hoc edit, deletion,
# reorder, or insertion (the smallest tamper breaks the hash chain forward).
#
# Key sources (in order):
#   1. AUDIT_HMAC_KEY env (must be set in managed-settings, NOT user-readable)
#   2. /etc/claude-code/audit-key (root:audit 0640)
#   3. AWS Secrets Manager (audit-hmac-key) — fetched if neither above present
#
# Fail-closed: if we cannot append to the local log AND cannot ship to
# CloudWatch, exit 2 to block the tool. Audit-evasion is treated as a
# deny-worthy condition by default. Set CLAUDE_AUDIT_FAIL_OPEN=1 to override
# (NOT recommended in production).
#
# Mandatory SIEM check (P0-2):
#   Set CLAUDE_AUDIT_SIEM_REQUIRED=1 to refuse startup unless either:
#     - CLAUDE_AUDIT_CLOUDWATCH_GROUP is set AND aws CLI works, OR
#     - CLAUDE_AUDIT_ALERT_CMD is set
# =============================================================================

set -u
input=$(cat)

# Defaults are user-writable for plugin / opt-in mode. For enterprise
# fail-closed enforcement, override these in managed-settings to root-owned
# paths (/var/log/claude-code, /var/lib/claude-code) — see the full repo.
LOG_FILE="${CLAUDE_AUDIT_LOG:-$HOME/.claude/claude-code-security/audit.jsonl}"
STATE_DIR="${CLAUDE_AUDIT_STATE:-$HOME/.claude/claude-code-security/audit-state}"
CW_GROUP="${CLAUDE_AUDIT_CLOUDWATCH_GROUP:-}"
CW_STREAM="${CLAUDE_AUDIT_CLOUDWATCH_STREAM:-$(hostname 2>/dev/null || echo unknown)}"
ALERT_CMD="${CLAUDE_AUDIT_ALERT_CMD:-}"
SIEM_REQ="${CLAUDE_AUDIT_SIEM_REQUIRED:-0}"
FAIL_OPEN="${CLAUDE_AUDIT_FAIL_OPEN:-0}"

mkdir -p "$(dirname "$LOG_FILE")" "$STATE_DIR" 2>/dev/null || true

# --- Mandatory SIEM check -----------------------------------------------------
if [[ "$SIEM_REQ" == "1" ]]; then
  ok=0
  [[ -n "$CW_GROUP" ]] && command -v aws >/dev/null 2>&1 && ok=1
  [[ -n "$ALERT_CMD" ]] && ok=1
  if [[ "$ok" != "1" ]]; then
    echo "audit-logger: SIEM forwarding required but no working forwarder configured" >&2
    [[ "$FAIL_OPEN" != "1" ]] && exit 2
  fi
fi

# --- Resolve HMAC key ---------------------------------------------------------
get_key() {
  if [[ -n "${AUDIT_HMAC_KEY:-}" ]]; then printf '%s' "$AUDIT_HMAC_KEY"; return; fi
  if [[ -r /etc/claude-code/audit-key ]]; then cat /etc/claude-code/audit-key; return; fi
  if command -v aws >/dev/null 2>&1; then
    aws secretsmanager get-secret-value --secret-id audit-hmac-key \
      --query SecretString --output text 2>/dev/null && return
  fi
  # Final fallback: derive from hostname+install marker (NOT cryptographically
  # secure but lets unit tests and dev environments run). Marker can be created
  # at install time so the same machine produces a stable key.
  if [[ -r "$STATE_DIR/key.dev" ]]; then cat "$STATE_DIR/key.dev"; return; fi
  return 1
}

KEY=$(get_key 2>/dev/null || true)
if [[ -z "$KEY" ]]; then
  # Generate a dev key on first run so the chain is stable per machine
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -hex 32 > "$STATE_DIR/key.dev" 2>/dev/null || true
    chmod 0600 "$STATE_DIR/key.dev" 2>/dev/null || true
    KEY=$(cat "$STATE_DIR/key.dev" 2>/dev/null || true)
  fi
fi
if [[ -z "$KEY" ]]; then
  echo "audit-logger: no HMAC key available" >&2
  [[ "$FAIL_OPEN" != "1" ]] && exit 2
fi

# --- Parse fields -------------------------------------------------------------
event=""; session_id=""; cwd=""; tool_name=""; command_str=""
if command -v jq >/dev/null 2>&1; then
  event=$(printf '%s' "$input" | jq -r '.hook_event_name // empty')
  session_id=$(printf '%s' "$input" | jq -r '.session_id // empty')
  cwd=$(printf '%s' "$input" | jq -r '.cwd // empty')
  tool_name=$(printf '%s' "$input" | jq -r '.tool_name // empty')
  case "$event" in
    PostToolUse) command_str=$(printf '%s' "$input" | jq -r '.tool_input.command // .tool_input.file_path // empty') ;;
    UserPromptSubmit) command_str=$(printf '%s' "$input" | jq -r '.prompt // empty' | head -c 500) ;;
  esac
fi

ts=$(date -u +"%Y-%m-%dT%H:%M:%S.%3NZ" 2>/dev/null || date -u +"%Y-%m-%dT%H:%M:%SZ")
user=$(whoami 2>/dev/null || echo unknown)
host=$(hostname 2>/dev/null || echo unknown)

# --- Read previous hash -------------------------------------------------------
PREV_FILE="$STATE_DIR/last-hmac"
[[ ! -e "$PREV_FILE" ]] && echo "GENESIS" > "$PREV_FILE" 2>/dev/null
prev_hash=$(cat "$PREV_FILE" 2>/dev/null || echo "GENESIS")

# --- Build canonical body, compute HMAC ---------------------------------------
body=$(jq -nc \
  --arg ts "$ts" --arg user "$user" --arg host "$host" \
  --arg event "$event" --arg session "$session_id" --arg cwd "$cwd" \
  --arg tool "$tool_name" --arg cmd "$command_str" --arg prev "$prev_hash" \
  '{ts:$ts,user:$user,host:$host,event:$event,session_id:$session,cwd:$cwd,tool:$tool,action:$cmd,prev_hash:$prev}')

hmac=$(printf '%s' "$body" | openssl dgst -sha256 -hmac "$KEY" 2>/dev/null \
       | awk '{print $NF}')
if [[ -z "$hmac" ]]; then
  echo "audit-logger: HMAC computation failed" >&2
  [[ "$FAIL_OPEN" != "1" ]] && exit 2
fi

entry=$(printf '%s' "$body" | jq -c --arg h "$hmac" '. + {hmac:$h}')

# --- Write locally (best-effort) ---------------------------------------------
local_ok=0
if echo "$entry" >> "$LOG_FILE" 2>/dev/null; then
  echo "$hmac" > "$PREV_FILE" 2>/dev/null
  local_ok=1
fi
# Try fallback path if root path failed
if [[ "$local_ok" != "1" ]]; then
  fb="$HOME/.claude/audit-fallback.jsonl"
  mkdir -p "$(dirname "$fb")" 2>/dev/null || true
  if echo "$entry" >> "$fb" 2>/dev/null; then
    echo "$hmac" > "$PREV_FILE" 2>/dev/null
    local_ok=1
  fi
fi

# --- Ship to CloudWatch (best-effort) ----------------------------------------
cw_ok=0
if [[ -n "$CW_GROUP" ]] && command -v aws >/dev/null 2>&1; then
  ts_ms=$(python3 -c 'import time;print(int(time.time()*1000))' 2>/dev/null || echo 0)
  aws logs put-log-events \
    --log-group-name "$CW_GROUP" --log-stream-name "$CW_STREAM" \
    --log-events "timestamp=$ts_ms,message=$(printf '%s' "$entry" | sed 's/"/\\"/g')" \
    >/dev/null 2>&1 && cw_ok=1
fi

# --- Optional alert webhook --------------------------------------------------
if [[ -n "$ALERT_CMD" ]]; then
  printf '%s\n' "$entry" | bash -c "$ALERT_CMD" >/dev/null 2>&1 || true
fi

# --- Fail-closed if both local AND remote failed ------------------------------
if [[ "$local_ok" != "1" && "$cw_ok" != "1" ]]; then
  echo "audit-logger: cannot persist event locally or remotely; blocking tool" >&2
  [[ "$FAIL_OPEN" != "1" ]] && exit 2
fi

exit 0
