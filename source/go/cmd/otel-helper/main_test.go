package main

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// TestAttachBearer is the behavioral half of the Go↔Python Bearer parity check
// (the static half lives in tests/test_otel_bearer_parity.py). It pins the
// contract the single attachBearer choke point must hold: a non-empty token
// yields exactly "Bearer <token>" under the "authorization" key, and an empty
// token attaches nothing (sending "Bearer " with no JWT is worse than omitting
// the header — the ALB would 401 on it).
func TestAttachBearer(t *testing.T) {
	t.Run("non-empty token sets Bearer header", func(t *testing.T) {
		headers := map[string]string{}
		attachBearer(headers, "abc.def.ghi")
		if got := headers["authorization"]; got != "Bearer abc.def.ghi" {
			t.Errorf("authorization = %q, want %q", got, "Bearer abc.def.ghi")
		}
	})

	t.Run("empty token omits the key", func(t *testing.T) {
		headers := map[string]string{}
		attachBearer(headers, "")
		if _, ok := headers["authorization"]; ok {
			t.Errorf("empty token must not set 'authorization', got %q", headers["authorization"])
		}
	})

	t.Run("existing attribution is preserved", func(t *testing.T) {
		headers := map[string]string{"x-user-email": "a@b.com"}
		attachBearer(headers, "tok")
		if headers["x-user-email"] != "a@b.com" {
			t.Errorf("attachBearer clobbered attribution: x-user-email = %q", headers["x-user-email"])
		}
		if headers["authorization"] != "Bearer tok" {
			t.Errorf("authorization = %q, want 'Bearer tok'", headers["authorization"])
		}
	})
}

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

	if code := run(false, "ClaudeCode"); code != 0 {
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

	if code := run(true, "ClaudeCode"); code != 0 {
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

	if code := run(false, "ClaudeCode"); code != 0 {
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

	if code := run(false, "ClaudeCode"); code != 0 {
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

// TestRun_WithToken_IncludesBearerHeader verifies that when a valid JWT is
// available, the output includes an "authorization" header with a Bearer prefix
// for ALB JWT validation.
func TestRun_WithToken_IncludesBearerHeader(t *testing.T) {
	tmpDir := t.TempDir()
	t.Setenv("HOME", tmpDir)
	t.Setenv("USERPROFILE", tmpDir)
	t.Setenv("AWS_PROFILE", "ClaudeCode")

	// Minimal valid JWT: header.payload.sig (alg:none, email+future exp)
	// Header:  {"alg":"none","typ":"JWT"}
	// Payload: {"email":"test@example.com","exp":9999999999,"sub":"user123"}
	token := "eyJhbGciOiJub25lIiwidHlwIjoiSldUIn0" +
		".eyJlbWFpbCI6InRlc3RAZXhhbXBsZS5jb20iLCJleHAiOjk5OTk5OTk5OTksInN1YiI6InVzZXIxMjMifQ" +
		"."
	t.Setenv("CLAUDE_CODE_MONITORING_TOKEN", token)

	r, w, _ := os.Pipe()
	old := os.Stdout
	os.Stdout = w
	code := run(false, "ClaudeCode")
	w.Close()
	os.Stdout = old

	if code != 0 {
		t.Fatalf("run() = %d, want 0", code)
	}

	var buf [4096]byte
	n, _ := r.Read(buf[:])
	var headers map[string]string
	if err := json.Unmarshal(buf[:n], &headers); err != nil {
		t.Fatalf("output not valid JSON: %v\nraw: %s", err, buf[:n])
	}

	auth, ok := headers["authorization"]
	if !ok {
		t.Fatal("output must include 'authorization' header for ALB JWT validation")
	}
	if auth != "Bearer "+token {
		t.Errorf("authorization = %q, want %q", auth, "Bearer "+token)
	}
	if headers["x-user-email"] != "test@example.com" {
		t.Errorf("x-user-email = %q, want test@example.com", headers["x-user-email"])
	}
}

// TestRun_NoToken_NoBearerInOutput verifies that when no token is available,
// the empty-headers output does NOT contain an "authorization" key — sending
// "Bearer " (empty) would be worse than sending nothing.
func TestRun_NoToken_NoBearerInOutput(t *testing.T) {
	tmpDir := t.TempDir()
	t.Setenv("HOME", tmpDir)
	t.Setenv("USERPROFILE", tmpDir)
	t.Setenv("AWS_PROFILE", "ClaudeCode")
	t.Setenv("CLAUDE_CODE_MONITORING_TOKEN", "")

	r, w, _ := os.Pipe()
	old := os.Stdout
	os.Stdout = w
	run(false, "ClaudeCode")
	w.Close()
	os.Stdout = old

	var buf [4096]byte
	n, _ := r.Read(buf[:])
	var headers map[string]string
	if err := json.Unmarshal(buf[:n], &headers); err != nil {
		t.Fatalf("output not valid JSON: %v", err)
	}
	if _, ok := headers["authorization"]; ok {
		t.Error("empty-headers output must NOT contain 'authorization' key")
	}
}

// TestRun_BearerTokenNotInCacheFile verifies that the Bearer token is never
// persisted to the otel-headers cache file — only attribution headers should
// be cached.
func TestRun_BearerTokenNotInCacheFile(t *testing.T) {
	tmpDir := t.TempDir()
	t.Setenv("HOME", tmpDir)
	t.Setenv("USERPROFILE", tmpDir)
	t.Setenv("AWS_PROFILE", "ClaudeCode")

	token := "eyJhbGciOiJub25lIiwidHlwIjoiSldUIn0" +
		".eyJlbWFpbCI6InRlc3RAZXhhbXBsZS5jb20iLCJleHAiOjk5OTk5OTk5OTksInN1YiI6InVzZXIxMjMifQ" +
		"."
	t.Setenv("CLAUDE_CODE_MONITORING_TOKEN", token)

	// Suppress stdout
	_, w, _ := os.Pipe()
	old := os.Stdout
	os.Stdout = w
	run(false, "ClaudeCode")
	w.Close()
	os.Stdout = old

	cachePath := filepath.Join(tmpDir, ".claude-code-session", "ClaudeCode-otel-headers.json")
	data, err := os.ReadFile(cachePath)
	if err != nil {
		t.Fatalf("cache file should exist: %v", err)
	}

	var entry struct {
		Headers map[string]string `json:"headers"`
	}
	if err := json.Unmarshal(data, &entry); err != nil {
		t.Fatalf("cache not valid JSON: %v", err)
	}
	if _, ok := entry.Headers["authorization"]; ok {
		t.Error("Bearer token must NOT be in cache file — sensitive token must only be in stdout")
	}
	if entry.Headers["x-user-email"] != "test@example.com" {
		t.Errorf("attribution should be cached: x-user-email = %q", entry.Headers["x-user-email"])
	}
}

// TestRun_CacheHit_ResolvesTokenFromEnv verifies that when Layer 1 serves
// cached attribution headers, the output still includes a Bearer token resolved
// from the environment variable.
func TestRun_CacheHit_ResolvesTokenFromEnv(t *testing.T) {
	tmpDir := t.TempDir()
	t.Setenv("HOME", tmpDir)
	t.Setenv("USERPROFILE", tmpDir)
	t.Setenv("AWS_PROFILE", "ClaudeCode")

	// Seed cache with valid attribution (far-future exp), no authorization header
	cacheDir := filepath.Join(tmpDir, ".claude-code-session")
	if err := os.MkdirAll(cacheDir, 0700); err != nil {
		t.Fatal(err)
	}
	cachePath := filepath.Join(cacheDir, "ClaudeCode-otel-headers.json")
	cache := `{"schema_version":2,"headers":{"x-user-email":"cached@user.com"},"token_exp":9999999999,"cached_at":1000}`
	if err := os.WriteFile(cachePath, []byte(cache), 0600); err != nil {
		t.Fatal(err)
	}

	envToken := "eyJhbGciOiJub25lIn0.eyJlbWFpbCI6InRlc3RAZXhhbXBsZS5jb20iLCJleHAiOjk5OTk5OTk5OTl9." // pragma: allowlist secret
	t.Setenv("CLAUDE_CODE_MONITORING_TOKEN", envToken)

	r, w, _ := os.Pipe()
	old := os.Stdout
	os.Stdout = w
	code := run(false, "ClaudeCode")
	w.Close()
	os.Stdout = old

	if code != 0 {
		t.Fatalf("run() = %d, want 0", code)
	}

	var buf [8192]byte
	n, _ := r.Read(buf[:])
	var headers map[string]string
	if err := json.Unmarshal(buf[:n], &headers); err != nil {
		t.Fatalf("output not valid JSON: %v\nraw: %s", err, buf[:n])
	}

	if headers["x-user-email"] != "cached@user.com" {
		t.Errorf("x-user-email = %q, want cached@user.com", headers["x-user-email"])
	}
	if !strings.HasPrefix(headers["authorization"], "Bearer ") {
		t.Errorf("authorization = %q, want 'Bearer <token>'", headers["authorization"])
	}
	if headers["authorization"] != "Bearer "+envToken {
		t.Errorf("authorization = %q, want 'Bearer %s'", headers["authorization"], envToken)
	}
}

// TestRun_Layer1_CacheHit_NoToken_OmitsBearerGracefully verifies that when a
// Layer 1 cache hit occurs but NO Bearer can be resolved (env var empty AND
// credential-process unavailable), the helper still emits valid cached attribution
// JSON, exits 0, and does NOT include an "authorization" key. This is the
// graceful-degradation half of Finding 2 — the (logged) path that previously
// returned silently.
func TestRun_Layer1_CacheHit_NoToken_OmitsBearerGracefully(t *testing.T) {
	tmpDir := t.TempDir()
	t.Setenv("HOME", tmpDir)
	t.Setenv("USERPROFILE", tmpDir)
	t.Setenv("AWS_PROFILE", "ClaudeCode")
	t.Setenv("CLAUDE_CODE_MONITORING_TOKEN", "") // no env token

	// Seed a warm cache with valid attribution (far-future exp), no authorization.
	cacheDir := filepath.Join(tmpDir, ".claude-code-session")
	if err := os.MkdirAll(cacheDir, 0700); err != nil {
		t.Fatal(err)
	}
	cachePath := filepath.Join(cacheDir, "ClaudeCode-otel-headers.json")
	cache := `{"schema_version":2,"headers":{"x-user-email":"cached@user.com"},"token_exp":9999999999,"cached_at":1000}`
	if err := os.WriteFile(cachePath, []byte(cache), 0600); err != nil {
		t.Fatal(err)
	}
	// No credential-process binary exists under tmpDir, so getTokenViaCredentialProcess fails.

	r, w, _ := os.Pipe()
	old := os.Stdout
	os.Stdout = w
	code := run(false, "ClaudeCode")
	w.Close()
	os.Stdout = old

	if code != 0 {
		t.Fatalf("run() = %d, want 0", code)
	}

	var buf [8192]byte
	n, _ := r.Read(buf[:])
	var headers map[string]string
	if err := json.Unmarshal(buf[:n], &headers); err != nil {
		t.Fatalf("output not valid JSON: %v\nraw: %s", err, buf[:n])
	}

	if headers["x-user-email"] != "cached@user.com" {
		t.Errorf("x-user-email = %q, want cached@user.com", headers["x-user-email"])
	}
	if _, ok := headers["authorization"]; ok {
		t.Errorf("authorization must be absent when no token resolves, got %q", headers["authorization"])
	}

	// The cache file must be untouched (no Bearer leaked to disk).
	after, err := os.ReadFile(cachePath)
	if err != nil {
		t.Fatalf("cache file should still exist: %v", err)
	}
	if strings.Contains(string(after), "authorization") {
		t.Error("cache file must not contain 'authorization' after a no-token cache hit")
	}
}

// TestUserInfoFromHeaders verifies the inverse of otel.FormatHeaders used by
// test-mode rendering: cached x-* headers map back to the right UserInfo fields.
func TestUserInfoFromHeaders(t *testing.T) {
	info := userInfoFromHeaders(map[string]string{
		"x-user-email":   "alice@example.com",
		"x-user-id":      "u-123",
		"x-user-name":    "alice",
		"x-department":   "eng",
		"x-team-id":      "team-a",
		"x-cost-center":  "cc-9",
		"x-organization": "org-1",
		"x-location":     "us",
		"x-role":         "dev",
		"x-manager":      "bob",
		"x-project":      "proj-x",
	})
	if info.Email != "alice@example.com" {
		t.Errorf("Email = %q, want alice@example.com", info.Email)
	}
	if info.Department != "eng" || info.Team != "team-a" || info.Project != "proj-x" {
		t.Errorf("field mapping mismatch: %+v", info)
	}
}

// TestRun_TestMode_ServesCachedHeaders is the regression test for IDC --test.
// IDC has no JWT, so attribution lives ONLY in the cache (written by
// credential-process from the IAM ARN). Test mode previously skipped the Layer-1
// cache read entirely and went straight to the (nonexistent) JWT path, so
// `otel-helper --test` always printed empty headers even when attribution was
// working. This asserts test mode now surfaces the cached x-user-email.
func TestRun_TestMode_ServesCachedHeaders(t *testing.T) {
	tmpDir := t.TempDir()
	t.Setenv("HOME", tmpDir)
	t.Setenv("USERPROFILE", tmpDir)
	t.Setenv("AWS_PROFILE", "idc-test")
	t.Setenv("CLAUDE_CODE_MONITORING_TOKEN", "")

	cacheDir := filepath.Join(tmpDir, ".claude-code-session")
	if err := os.MkdirAll(cacheDir, 0o700); err != nil {
		t.Fatal(err)
	}
	// schema_version 2 + future exp so Layer 1 treats it as a valid hit.
	entry := `{"schema_version":2,"headers":{"x-user-email":"qnamzn+developer@amazon.com"},"token_exp":9999999999,"cached_at":1782315885}`
	if err := os.WriteFile(filepath.Join(cacheDir, "idc-test-otel-headers.json"), []byte(entry), 0o600); err != nil {
		t.Fatal(err)
	}

	r, w, _ := os.Pipe()
	old := os.Stdout
	os.Stdout = w
	code := run(true, "idc-test")
	w.Close()
	os.Stdout = old

	if code != 0 {
		t.Fatalf("run(testMode) = %d, want 0", code)
	}

	var buf [8192]byte
	n, _ := r.Read(buf[:])
	out := string(buf[:n])
	if !strings.Contains(out, "qnamzn+developer@amazon.com") {
		t.Errorf("test-mode output must surface the cached email; got:\n%s", out)
	}
}

// TestResolveProfile_Precedence locks in the resolution order:
// --profile flag > CCWB_PROFILE env > AWS_PROFILE env > "ClaudeCode" default.
func TestResolveProfile_Precedence(t *testing.T) {
	t.Setenv("CCWB_PROFILE", "CcwbProfile")
	t.Setenv("AWS_PROFILE", "EnvProfile")

	// CCWB_PROFILE (ccwb-specific override, same convention as
	// credential-process) beats the ambient AWS_PROFILE.
	if got := resolveProfile(""); got != "CcwbProfile" {
		t.Errorf("resolveProfile(\"\") = %q, want CCWB_PROFILE value \"CcwbProfile\"", got)
	}

	if got := resolveProfile("FlagProfile"); got != "FlagProfile" {
		t.Errorf("resolveProfile(flag) = %q, want \"FlagProfile\"", got)
	}
	// The flag must be exported so child processes (credential-process) and
	// the AWS SDK in proxy mode resolve the same profile.
	if got := os.Getenv("AWS_PROFILE"); got != "FlagProfile" {
		t.Errorf("AWS_PROFILE after flag resolution = %q, want \"FlagProfile\"", got)
	}

	t.Setenv("CCWB_PROFILE", "")
	t.Setenv("AWS_PROFILE", "EnvProfile")
	if got := resolveProfile(""); got != "EnvProfile" {
		t.Errorf("resolveProfile(\"\") = %q, want AWS_PROFILE value \"EnvProfile\"", got)
	}

	t.Setenv("AWS_PROFILE", "")
	if got := resolveProfile(""); got != "ClaudeCode" {
		t.Errorf("resolveProfile with no flag/env = %q, want \"ClaudeCode\"", got)
	}
}
