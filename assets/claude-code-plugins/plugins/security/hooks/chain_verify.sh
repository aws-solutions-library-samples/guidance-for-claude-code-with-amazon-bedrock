#!/usr/bin/env bash
# Verify the HMAC chain in an audit log. Exits 0 if intact, 1 if broken.
# Usage: chain_verify.sh <log-file> [--key-file <path>]
set -u
LOG="${1:-}"
KEY_FILE="${2:-}"
[[ -z "$LOG" || ! -r "$LOG" ]] && { echo "usage: $0 <log> [--key-file path]"; exit 2; }

if [[ -n "${AUDIT_HMAC_KEY:-}" ]]; then
  KEY="$AUDIT_HMAC_KEY"
elif [[ -n "$KEY_FILE" && -r "$KEY_FILE" ]]; then
  KEY=$(cat "$KEY_FILE")
elif [[ -r /etc/claude-code/audit-key ]]; then
  KEY=$(cat /etc/claude-code/audit-key)
elif [[ -r "${CLAUDE_AUDIT_STATE:-$HOME/.claude/claude-code-security/audit-state}/key.dev" ]]; then
  KEY=$(cat "${CLAUDE_AUDIT_STATE:-$HOME/.claude/claude-code-security/audit-state}/key.dev")
else
  echo "no key" >&2; exit 2
fi

prev="GENESIS"
n=0; bad=0
while IFS= read -r line; do
  n=$((n+1))
  body=$(printf '%s' "$line" | jq -c 'del(.hmac)')
  expected=$(printf '%s' "$line" | jq -r '.hmac')
  prev_in=$(printf '%s' "$line" | jq -r '.prev_hash')
  if [[ "$prev_in" != "$prev" ]]; then
    echo "line $n: prev_hash mismatch (expected $prev, got $prev_in)" >&2
    bad=1
  fi
  computed=$(printf '%s' "$body" | openssl dgst -sha256 -hmac "$KEY" | awk '{print $NF}')
  if [[ "$computed" != "$expected" ]]; then
    echo "line $n: hmac mismatch" >&2
    bad=1
  fi
  prev="$expected"
done < "$LOG"

if [[ "$bad" == "1" ]]; then
  echo "CHAIN BROKEN ($n lines verified, failures detected)"; exit 1
else
  echo "chain intact ($n lines verified)"; exit 0
fi
