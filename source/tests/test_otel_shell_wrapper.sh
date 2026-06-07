#!/usr/bin/env bash
# ABOUTME: Tests for otel-helper.sh shell wrapper — the sidecar-mode otelHeadersHelper.
# ABOUTME: Covers Bearer splicing on cache hit, expiry gate, env precedence, graceful no-token, cache-miss fallthrough.
#
# This closes the coverage gap that let the wrapper-bypass bug (Finding 1) ship:
# every Go/Python test calls the binary directly, none exercised this wrapper.
#
# Run: bash source/tests/test_otel_shell_wrapper.sh
set -u

# Resolve repo paths relative to this test file.
TEST_DIR="$(cd "$(dirname "$0")" && pwd)"
WRAPPER="$TEST_DIR/../otel_helper/otel-helper.sh"
PROFILE="test-profile"

PASS=0
FAIL=0

fail() { echo "  FAIL: $1"; FAIL=$((FAIL + 1)); }
pass() { echo "  ok:   $1"; PASS=$((PASS + 1)); }

# Validate that a string is legal JSON and (optionally) assert a jq-free field check via python3.
is_json() { printf '%s' "$1" | python3 -c "import json,sys; json.load(sys.stdin)" 2>/dev/null; }
json_get() { printf '%s' "$1" | python3 -c "import json,sys; print(json.load(sys.stdin).get('$2',''))" 2>/dev/null; }

# Each scenario runs in its own temp HOME so the wrapper's CACHE_DIR is isolated and
# the sidecar-collector guard (needs $HOME/claude-code-with-bedrock/otelcol) is inert.
setup_home() {
    TMP_HOME="$(mktemp -d)"
    CACHE_DIR="$TMP_HOME/.claude-code-session"
    mkdir -p "$CACHE_DIR"
    RAW_FILE="$CACHE_DIR/${PROFILE}-otel-headers.json"      # note: wrapper uses CACHE_FILE for token_exp
    CACHE_FILE="$CACHE_DIR/${PROFILE}-otel-headers.json"
    RAWP="$CACHE_DIR/${PROFILE}-otel-headers.raw"
    MON_FILE="$CACHE_DIR/${PROFILE}-monitoring.json"
    # Install a stub binary next to a *copy* of the wrapper so a cache-miss fallthrough
    # (exec "$SCRIPT_DIR/otel-helper-bin") hits our stub, not a real build.
    RUN_DIR="$TMP_HOME/run"
    mkdir -p "$RUN_DIR"
    cp "$WRAPPER" "$RUN_DIR/otel-helper.sh"
    cat > "$RUN_DIR/otel-helper-bin" <<'STUB'
#!/usr/bin/env bash
echo '{"__stub_binary__": "invoked"}'
STUB
    chmod +x "$RUN_DIR/otel-helper-bin"
}
teardown_home() { rm -rf "$TMP_HOME"; }

run_wrapper() { AWS_PROFILE="$PROFILE" HOME="$TMP_HOME" bash "$RUN_DIR/otel-helper.sh"; }

FUTURE=$(($(date +%s) + 3600))
PAST=$(($(date +%s) - 10))
ATTR='{"x-user-email": "cached@example.com", "x-user-id": "u-123"}'

# ---------------------------------------------------------------------------
echo "Scenario 1: cache hit + valid monitoring.json token -> Bearer spliced"
setup_home
printf '{"headers": %s, "token_exp": %s}\n' "$ATTR" "$FUTURE" > "$CACHE_FILE"
printf '%s\n' "$ATTR" > "$RAWP"
printf '{"token": "HEADER.PAYLOAD.SIG", "expires": %s}\n' "$FUTURE" > "$MON_FILE"
OUT="$(run_wrapper)"
if is_json "$OUT"; then
    if [ "$(json_get "$OUT" authorization)" = "Bearer HEADER.PAYLOAD.SIG" ] \
        && [ "$(json_get "$OUT" x-user-email)" = "cached@example.com" ]; then
        pass "Bearer spliced + attribution preserved"
    else
        fail "expected Bearer + attribution, got: $OUT"
    fi
else
    fail "output not valid JSON: $OUT"
fi
teardown_home

# ---------------------------------------------------------------------------
echo "Scenario 2: cache hit + expired token_exp -> falls through to binary stub"
setup_home
printf '{"headers": %s, "token_exp": %s}\n' "$ATTR" "$PAST" > "$CACHE_FILE"
printf '%s\n' "$ATTR" > "$RAWP"
printf '{"token": "HEADER.PAYLOAD.SIG", "expires": %s}\n' "$PAST" > "$MON_FILE"
OUT="$(run_wrapper)"
# Expired token_exp means the cache block is skipped entirely -> exec stub binary.
if [ "$(json_get "$OUT" __stub_binary__)" = "invoked" ]; then
    pass "expired cache falls through to binary (no stale serve)"
else
    fail "expected binary fallthrough, got: $OUT"
fi
teardown_home

# ---------------------------------------------------------------------------
echo "Scenario 3: cache hit + env var set, no monitoring.json -> Bearer from env"
setup_home
printf '{"headers": %s, "token_exp": %s}\n' "$ATTR" "$FUTURE" > "$CACHE_FILE"
printf '%s\n' "$ATTR" > "$RAWP"
# No monitoring.json on disk; env var supplies the token.
OUT="$(AWS_PROFILE="$PROFILE" HOME="$TMP_HOME" CLAUDE_CODE_MONITORING_TOKEN="ENV.TOKEN.X" bash "$RUN_DIR/otel-helper.sh")"
if is_json "$OUT" && [ "$(json_get "$OUT" authorization)" = "Bearer ENV.TOKEN.X" ]; then
    pass "env var takes precedence and is spliced"
else
    fail "expected Bearer from env, got: $OUT"
fi
teardown_home

# ---------------------------------------------------------------------------
echo "Scenario 4: cache hit + no token anywhere -> attribution only, valid JSON"
setup_home
printf '{"headers": %s, "token_exp": %s}\n' "$ATTR" "$FUTURE" > "$CACHE_FILE"
printf '%s\n' "$ATTR" > "$RAWP"
# No monitoring.json, no env var.
OUT="$(run_wrapper)"
if is_json "$OUT" \
    && [ "$(json_get "$OUT" x-user-email)" = "cached@example.com" ] \
    && [ -z "$(json_get "$OUT" authorization)" ]; then
    pass "graceful: attribution emitted, no authorization, no crash"
else
    fail "expected attribution-only JSON, got: $OUT"
fi
teardown_home

# ---------------------------------------------------------------------------
echo "Scenario 5: cache miss (no cache files) -> falls through to binary stub"
setup_home
# No cache files written at all.
OUT="$(run_wrapper)"
if [ "$(json_get "$OUT" __stub_binary__)" = "invoked" ]; then
    pass "cache miss execs the binary"
else
    fail "expected binary fallthrough on cache miss, got: $OUT"
fi
teardown_home

# ---------------------------------------------------------------------------
echo "Scenario 6: security — Bearer is never written back to the .raw file on disk"
setup_home
printf '{"headers": %s, "token_exp": %s}\n' "$ATTR" "$FUTURE" > "$CACHE_FILE"
printf '%s\n' "$ATTR" > "$RAWP"
printf '{"token": "SECRET.JWT.SIG", "expires": %s}\n' "$FUTURE" > "$MON_FILE"
run_wrapper > /dev/null
if grep -q "authorization" "$RAWP" || grep -q "SECRET.JWT.SIG" "$RAWP"; then
    fail "Bearer/token leaked into .raw file on disk"
else
    pass "Bearer stays on stdout; .raw file unchanged"
fi
teardown_home

# ---------------------------------------------------------------------------
echo "Scenario 7: cache hit + empty-headers {} .raw + token -> valid JSON, no leading comma"
setup_home
printf '{"headers": {}, "token_exp": %s}\n' "$FUTURE" > "$CACHE_FILE"
printf '{}\n' > "$RAWP"
printf '{"token": "TOK.EN.X", "expires": %s}\n' "$FUTURE" > "$MON_FILE"
OUT="$(run_wrapper)"
if is_json "$OUT" && [ "$(json_get "$OUT" authorization)" = "Bearer TOK.EN.X" ]; then
    pass "empty-headers object splices to valid JSON"
else
    fail "expected valid JSON with Bearer, got: $OUT"
fi
teardown_home

# ---------------------------------------------------------------------------
echo
echo "RESULT: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
