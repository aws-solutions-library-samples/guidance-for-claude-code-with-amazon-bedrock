#!/bin/bash
# ABOUTME: Lightweight shell wrapper for otel-helper that ensures the local OTEL collector
# ABOUTME: sidecar is running (when present), then checks file cache for headers (avoids PyInstaller startup)
PROFILE="${AWS_PROFILE:-ClaudeCode}"
INSTALL_DIR="$HOME/claude-code-with-bedrock"
PID_FILE="$INSTALL_DIR/collector.pid"
CACHE_DIR="$HOME/.claude-code-session"
CACHE_FILE="$CACHE_DIR/${PROFILE}-otel-headers.json"
RAW_FILE="$CACHE_DIR/${PROFILE}-otel-headers.raw"
# Must match currentCacheSchemaVersion in source/go/internal/otel/cache.go. The
# shim serves the unversioned .raw companion on the fast path, so it MUST also
# honor the schema gate the Go binary enforces — otherwise a cache written by an
# older binary (e.g. one that predates the x-persona header) would be served
# stale until the JWT expires, defeating the schema bump. On a version mismatch
# we fall through to the binary, which re-extracts headers under the new schema.
CACHE_SCHEMA_VERSION=3

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
MONITORING_FILE="$CACHE_DIR/${PROFILE}-monitoring.json"
if [ -f "$CACHE_FILE" ] && [ -f "$RAW_FILE" ]; then
    # Extract token_exp from JSON using grep+sed (no jq dependency)
    TOKEN_EXP=$(grep -o '"token_exp":[[:space:]]*[0-9]*' "$CACHE_FILE" | sed 's/.*:[[:space:]]*//')
    NOW=$(date +%s)

    # Honor the cache schema gate (see CACHE_SCHEMA_VERSION above). A missing or
    # older schema_version means the cache shape predates this binary's headers
    # (e.g. no x-persona) — fall through to the binary to re-extract rather than
    # serve stale attribution. Default to 0 when absent so legacy caches refresh.
    CACHE_SCHEMA=$(grep -o '"schema_version":[[:space:]]*[0-9]*' "$CACHE_FILE" | sed 's/.*:[[:space:]]*//')
    CACHE_SCHEMA="${CACHE_SCHEMA:-0}"

    if [ -n "$TOKEN_EXP" ] && [ "$TOKEN_EXP" -gt "$((NOW + 60))" ] \
        && [ "$CACHE_SCHEMA" -ge "$CACHE_SCHEMA_VERSION" ]; then
        # Token still valid (>60s remaining) - serve cached attribution headers.
        # The .raw file deliberately omits the Bearer token (never persisted to
        # disk), so splice it onto stdout here: the OTEL collector's ALB jwt-validation
        # action rejects requests without "Authorization: Bearer <jwt>".
        # Resolve the token cheaply (no binary cold-start): env var first, else the
        # monitoring-token cache the credential-provider already wrote and expiry-validated.
        TOKEN="${CLAUDE_CODE_MONITORING_TOKEN:-}"
        if [ -z "$TOKEN" ] && [ -f "$MONITORING_FILE" ]; then
            TOKEN=$(grep -o '"token"[[:space:]]*:[[:space:]]*"[^"]*"' "$MONITORING_FILE" \
                | sed 's/.*"token"[[:space:]]*:[[:space:]]*"//; s/"$//')
        fi

        if [ -n "$TOKEN" ]; then
            # Splice the Bearer into the flat single-line JSON. Strip the trailing '}',
            # then append. Guard the empty-object case ({} -> no leading comma) so the
            # result stays valid JSON whether or not attribution headers are present.
            HEAD=$(sed 's/}[[:space:]]*$//' "$RAW_FILE")
            case "$HEAD" in
                *[!\ {]*) SEP=", " ;;   # has content after '{' -> need a comma
                *)        SEP="" ;;     # bare '{' (empty headers) -> no comma
            esac
            printf '%s%s"authorization": "Bearer %s"}\n' "$HEAD" "$SEP" "$TOKEN"
        else
            # No token resolvable - serve attribution as-is. The ALB will 401 if it
            # enforces JWT, but emitting valid JSON keeps the otelHeadersHelper contract.
            cat "$RAW_FILE"
        fi
        exit 0
    fi
    # Token expired or missing - fall through to binary
fi

# Cache miss or expired - fall back to full PyInstaller binary (which writes the cache)
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
exec "$SCRIPT_DIR/otel-helper-bin" "$@"
