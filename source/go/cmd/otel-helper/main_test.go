package main

import (
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
)

// TestRun_NoToken_EmitsEmptyHeadersAndExitsZero is the regression test for the
// Windows symptom "otelHeadersHelper did not return a valid value": when no
// monitoring token is available the helper must still print a valid JSON object
// and exit 0 so Claude Code's telemetry export proceeds instead of failing on
// every cycle.
func TestRun_NoToken_EmitsEmptyHeadersAndExitsZero(t *testing.T) {
	tmpDir := t.TempDir()
	t.Setenv("HOME", tmpDir)
	t.Setenv("USERPROFILE", tmpDir) // Windows home resolution
	t.Setenv("AWS_PROFILE", "ClaudeCode")
	t.Setenv("CLAUDE_CODE_MONITORING_TOKEN", "") // force credential-process path
	// No credential-process binary exists under tmpDir/claude-code-with-bedrock,
	// so getTokenViaCredentialProcess returns an error -> emitEmptyHeaders.

	if code := run(false); code != 0 {
		t.Fatalf("run() exit code = %d, want 0", code)
	}

	// The empty result must be cached with a future TTL so the next turn is a
	// cache hit rather than another credential-process spawn.
	cachePath := filepath.Join(tmpDir, ".claude-code-session", "ClaudeCode-otel-headers.json")
	data, err := os.ReadFile(cachePath)
	if err != nil {
		t.Fatalf("expected empty-headers cache to be written: %v", err)
	}
	var entry struct {
		Headers  map[string]string `json:"headers"`
		TokenExp int64             `json:"token_exp"`
	}
	if err := json.Unmarshal(data, &entry); err != nil {
		t.Fatalf("cache not valid JSON: %v", err)
	}
	if entry.Headers == nil {
		t.Fatal("cached headers should be a non-nil empty map")
	}
	if len(entry.Headers) != 0 {
		t.Errorf("cached headers = %v, want empty", entry.Headers)
	}
	if entry.TokenExp <= 0 {
		t.Errorf("empty-headers cache should carry a positive TTL, got token_exp=%d", entry.TokenExp)
	}
}

// TestRun_TestMode_NoToken_DoesNotWriteCache ensures --test never persists an
// empty-headers cache entry (test mode is for humans inspecting output).
func TestRun_TestMode_NoToken_DoesNotWriteCache(t *testing.T) {
	tmpDir := t.TempDir()
	t.Setenv("HOME", tmpDir)
	t.Setenv("USERPROFILE", tmpDir)
	t.Setenv("AWS_PROFILE", "ClaudeCode")
	t.Setenv("CLAUDE_CODE_MONITORING_TOKEN", "")

	if code := run(true); code != 0 {
		t.Fatalf("run(testMode) exit code = %d, want 0", code)
	}

	cachePath := filepath.Join(tmpDir, ".claude-code-session", "ClaudeCode-otel-headers.json")
	if _, err := os.Stat(cachePath); !os.IsNotExist(err) {
		t.Errorf("test mode must not write cache file, stat err = %v", err)
	}
}

// TestRun_FreshEmptyCache_ServedViaLayer1 locks in the latency guarantee
// end-to-end: a second run with a still-valid empty-headers cache must be
// served from Layer 1 and exit 0 WITHOUT touching credential-process. The
// Layer-1 path returns before any cache write, so we prove the short-circuit
// by asserting the cache file is left byte-for-byte unchanged (a credential-
// process round-trip would have rewritten it with a fresh cached_at/token_exp).
func TestRun_FreshEmptyCache_ServedViaLayer1(t *testing.T) {
	tmpDir := t.TempDir()
	t.Setenv("HOME", tmpDir)
	t.Setenv("USERPROFILE", tmpDir)
	t.Setenv("AWS_PROFILE", "ClaudeCode")
	t.Setenv("CLAUDE_CODE_MONITORING_TOKEN", "")

	cacheDir := filepath.Join(tmpDir, ".claude-code-session")
	if err := os.MkdirAll(cacheDir, 0700); err != nil {
		t.Fatalf("mkdir: %v", err)
	}
	cachePath := filepath.Join(cacheDir, "ClaudeCode-otel-headers.json")
	// Empty headers with a far-future token_exp -> still-valid Layer-1 hit.
	fresh := `{"schema_version":2,"headers":{},"token_exp":9999999999,"cached_at":1000}`
	if err := os.WriteFile(cachePath, []byte(fresh), 0600); err != nil {
		t.Fatalf("seed cache: %v", err)
	}

	if code := run(false); code != 0 {
		t.Fatalf("run() exit code = %d, want 0", code)
	}

	after, err := os.ReadFile(cachePath)
	if err != nil {
		t.Fatalf("read cache after run: %v", err)
	}
	if string(after) != fresh {
		t.Errorf("Layer-1 hit must not rewrite the cache (no credential-process spawn).\n before: %s\n after:  %s", fresh, string(after))
	}
}

// TestRun_PopulatedExpiredEntry_ServedNotRewritten pins the end-to-end guarantee
// that a populated cache entry survives the no-token flow. We seed a populated
// entry with a past token_exp: by design populated attributes are served PAST
// expiry (to avoid browser re-auth), so Layer 1 returns it as a hit and run()
// never reaches emitEmptyHeaders — the entry is both served on stdout AND left
// untouched on disk, never replaced by {}.
//
// Note: because Layer 1 short-circuits here, this test does NOT exercise the
// emitEmptyHeaders clobber-guard itself — that guard (EmptyHeadersWriteSafe,
// which protects against a TRANSIENT Layer-1 read failure over a good entry) is
// covered directly by TestEmptyHeadersWriteSafe in the otel package. This test
// covers the complementary, more common path: a readable populated entry.
func TestRun_PopulatedExpiredEntry_ServedNotRewritten(t *testing.T) {
	tmpDir := t.TempDir()
	t.Setenv("HOME", tmpDir)
	t.Setenv("USERPROFILE", tmpDir)
	t.Setenv("AWS_PROFILE", "ClaudeCode")
	t.Setenv("CLAUDE_CODE_MONITORING_TOKEN", "")

	cacheDir := filepath.Join(tmpDir, ".claude-code-session")
	if err := os.MkdirAll(cacheDir, 0700); err != nil {
		t.Fatalf("mkdir: %v", err)
	}
	cachePath := filepath.Join(cacheDir, "ClaudeCode-otel-headers.json")
	// Populated headers, token_exp in the past.
	populated := `{"schema_version":2,"headers":{"x-user-email":"real@user.com"},"token_exp":1000,"cached_at":500}`
	if err := os.WriteFile(cachePath, []byte(populated), 0600); err != nil {
		t.Fatalf("seed cache: %v", err)
	}

	if code := run(false); code != 0 {
		t.Fatalf("run() exit code = %d, want 0", code)
	}

	data, err := os.ReadFile(cachePath)
	if err != nil {
		t.Fatalf("read cache after run: %v", err)
	}
	var entry struct {
		Headers map[string]string `json:"headers"`
	}
	if err := json.Unmarshal(data, &entry); err != nil {
		t.Fatalf("cache not valid JSON: %v", err)
	}
	if entry.Headers["x-user-email"] != "real@user.com" {
		t.Errorf("populated attribution was clobbered: x-user-email = %q, want real@user.com (cache now: %s)",
			entry.Headers["x-user-email"], string(data))
	}
}
