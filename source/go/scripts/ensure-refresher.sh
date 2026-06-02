#!/bin/bash
# ABOUTME: Shell hook that ensures the credential-refresher daemon is running.
# ABOUTME: Designed to be called from a Claude Code hook or shell profile.
# Usage: source this file, or call ccwb-ensure-refresher from .bashrc/.zshrc

PROFILE="${CCWB_PROFILE:-ClaudeCode}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"

ccwb_ensure_refresher() {
    local profile="${1:-$PROFILE}"
    local refresher_bin="${SCRIPT_DIR}/credential-refresher"
    local pid_file="${HOME}/.claude-code-session/refresher-${profile}.pid"

    # Check if refresher binary exists
    if [ ! -x "$refresher_bin" ]; then
        # Fall back to credential-process for auth (no refresher available)
        return 0
    fi

    # Check if already running
    if [ -f "$pid_file" ]; then
        local pid
        pid=$(cat "$pid_file" 2>/dev/null)
        if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
            # Refresher is running
            return 0
        fi
        # Stale PID file — clean up
        rm -f "$pid_file"
    fi

    # Ensure initial credentials exist before starting daemon
    local cred_file="${HOME}/.aws/credentials"
    if [ ! -f "$cred_file" ] || ! grep -q "aws_access_key_id" "$cred_file" 2>/dev/null; then
        # Bootstrap credentials
        "${SCRIPT_DIR}/credential-process" --profile "$profile" > /dev/null 2>&1
    fi

    # Start refresher in background
    "$refresher_bin" --profile "$profile" >> "${HOME}/.claude-code-session/refresher-${profile}.log" 2>&1 &
    disown
}

# Auto-run if sourced from a shell profile
if [ "${BASH_SOURCE[0]:-}" != "$0" ] || [ "${ZSH_EVAL_CONTEXT:-}" = "toplevel" ]; then
    ccwb_ensure_refresher
fi
