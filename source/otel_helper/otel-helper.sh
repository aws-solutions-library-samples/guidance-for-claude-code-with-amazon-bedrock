#!/bin/bash
# ABOUTME: Lightweight shell wrapper for otel-helper that ensures the local OTEL collector
# ABOUTME: sidecar is running (when present), then checks file cache for headers (avoids PyInstaller startup)
PROFILE="${AWS_PROFILE:-ClaudeCode}"
INSTALL_DIR="$HOME/claude-code-with-bedrock"
PID_FILE="$INSTALL_DIR/collector.pid"
CACHE_DIR="$HOME/.claude-code-session"
CACHE_FILE="$CACHE_DIR/${PROFILE}-otel-headers.json"
RAW_FILE="$CACHE_DIR/${PROFILE}-otel-headers.raw"

# Ensure collector sidecar is running (only in sidecar mode — binary present)
# Use a dedicated <profile>-collector AWS profile so the Go SDK always resolves
# credentials via credential_process (the main profile has static creds in
# ~/.aws/credentials that shadow credential_process and can't auto-refresh).
if [ -x "$INSTALL_DIR/otelcol" ] && [ -f "$INSTALL_DIR/collector-config.yaml" ]; then
    if ! { [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE" 2>/dev/null)" 2>/dev/null; }; then
        mkdir -p "$CACHE_DIR"
        AWS_PROFILE="${PROFILE}-collector" \
        "$INSTALL_DIR/otelcol" --config "$INSTALL_DIR/collector-config.yaml" \
            >> "$CACHE_DIR/collector.log" 2>&1 &
        echo $! > "$PID_FILE"
    fi
fi

# Check if cache exists and token is still valid
if [ -f "$CACHE_FILE" ] && [ -f "$RAW_FILE" ]; then
    # Extract token_exp from JSON using grep+sed (no jq dependency)
    TOKEN_EXP=$(grep -o '"token_exp":[[:space:]]*[0-9]*' "$CACHE_FILE" | sed 's/.*:[[:space:]]*//')
    NOW=$(date +%s)

    if [ -n "$TOKEN_EXP" ] && [ "$TOKEN_EXP" -gt "$((NOW + 60))" ]; then
        # Token still valid (>60s remaining) - serve cached headers
        cat "$RAW_FILE"
        exit 0
    fi
    # Token expired or missing - fall through to binary
fi

# Cache miss or expired - fall back to full PyInstaller binary (which writes the cache)
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
exec "$SCRIPT_DIR/otel-helper-bin" "$@"
