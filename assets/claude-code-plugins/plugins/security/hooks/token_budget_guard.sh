#!/usr/bin/env bash
# =============================================================================
# Token Budget Guard — circuit breaker for runaway agent loops
# =============================================================================
# Hook version: 1.0.0
# Hook events: PreToolUse (decides whether to allow next tool call)
#              PostToolUse (records actual token usage if available)
#
# Maintains per-session running token totals at:
#   $CLAUDE_TOKEN_STATE/<session_id>.tokens     (cumulative input+output)
#   $CLAUDE_TOKEN_STATE/<session_id>.calls      (tool call count)
#
# When either threshold is exceeded the next PreToolUse blocks with exit 2,
# requiring a fresh session.
#
# Configuration (env, set in managed-settings):
#   CLAUDE_TOKEN_STATE     — state directory (default /var/lib/claude-code/sessions)
#   CLAUDE_TOKEN_BUDGET    — max cumulative tokens per session (default 1000000)
#   CLAUDE_CALL_BUDGET     — max tool calls per session (default 500)
#
# This is the circuit breaker for ungoverned agent loops the architect review
# flagged. Agents that legitimately need more should request budget increase.
# =============================================================================

set -u
input=$(cat)

# Default is user-writable for plugin / opt-in mode; override in managed-settings
# to a root-owned path (/var/lib/claude-code/sessions) for enterprise enforcement.
STATE_DIR="${CLAUDE_TOKEN_STATE:-$HOME/.claude/claude-code-security/sessions}"
TOKEN_BUDGET="${CLAUDE_TOKEN_BUDGET:-1000000}"
CALL_BUDGET="${CLAUDE_CALL_BUDGET:-500}"
mkdir -p "$STATE_DIR" 2>/dev/null || true

if ! command -v jq >/dev/null 2>&1; then
  exit 0  # jq missing → cannot enforce; pass through
fi

session=$(printf '%s' "$input" | jq -r '.session_id // empty')
event=$(printf '%s' "$input"   | jq -r '.hook_event_name // empty')
[[ -z "$session" ]] && exit 0

token_file="$STATE_DIR/${session}.tokens"
call_file="$STATE_DIR/${session}.calls"
[[ ! -e "$token_file" ]] && echo 0 > "$token_file" 2>/dev/null
[[ ! -e "$call_file"  ]] && echo 0 > "$call_file"  2>/dev/null

cur_tokens=$(cat "$token_file" 2>/dev/null || echo 0)
cur_calls=$(cat "$call_file"  2>/dev/null || echo 0)

case "$event" in
  PreToolUse)
    # Block if either budget exhausted
    if [[ "$cur_tokens" -ge "$TOKEN_BUDGET" ]]; then
      cat >&2 <<EOF
🛑 TOKEN BUDGET GUARD: session $session has consumed $cur_tokens tokens
   (budget: $TOKEN_BUDGET). Tool execution blocked.

This protects against runaway agent loops. Start a new session, or contact
your team lead to request a temporary budget increase.
EOF
      exit 2
    fi
    if [[ "$cur_calls" -ge "$CALL_BUDGET" ]]; then
      cat >&2 <<EOF
🛑 TOKEN BUDGET GUARD: session $session has executed $cur_calls tool calls
   (budget: $CALL_BUDGET). Tool execution blocked.
EOF
      exit 2
    fi
    # Increment call counter; we do not have token usage at PreToolUse time
    echo $((cur_calls + 1)) > "$call_file" 2>/dev/null
    ;;

  PostToolUse)
    # Token totals — Claude Code reports usage in tool_response.usage if available
    in_tokens=$(printf '%s' "$input" | jq -r '.tool_response.usage.input_tokens // 0' 2>/dev/null)
    out_tokens=$(printf '%s' "$input" | jq -r '.tool_response.usage.output_tokens // 0' 2>/dev/null)
    delta=$((in_tokens + out_tokens))
    if [[ "$delta" -gt 0 ]]; then
      echo $((cur_tokens + delta)) > "$token_file" 2>/dev/null
    fi
    ;;
esac

exit 0
