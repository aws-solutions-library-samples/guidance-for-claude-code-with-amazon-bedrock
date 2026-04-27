#!/bin/bash
# ABOUTME: Lightweight shell wrapper for otel-helper that checks file cache first
# ABOUTME: Avoids PyInstaller binary startup (~6s) on cache hit, falls back to full binary on miss
PROFILE="${AWS_PROFILE:-ClaudeCode}"
CACHE_DIR="$HOME/.claude-code-session"
CACHE_FILE="$CACHE_DIR/${PROFILE}-otel-headers.json"
RAW_FILE="$CACHE_DIR/${PROFILE}-otel-headers.raw"

if [ -f "$RAW_FILE" ]; then
    # Serve raw headers directly — no JSON parsing needed
    cat "$RAW_FILE"
    exit 0
fi

# Cache miss - fall back to full PyInstaller binary (which writes the cache)
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
if [ "${CLAUDE_CODE_OTEL_ANONYMOUS:-}" = "1" ]; then
    exec "$SCRIPT_DIR/otel-helper-bin" --anonymous "$@"
fi
exec "$SCRIPT_DIR/otel-helper-bin" "$@"
