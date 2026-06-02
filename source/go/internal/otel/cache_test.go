package otel

import (
	"fmt"
	"os"
	"path/filepath"
	"testing"
	"time"
)

func TestWriteAndReadCachedHeaders(t *testing.T) {
	// Use a temp dir for testing
	tmpDir := t.TempDir()
	origHome := os.Getenv("HOME")
	os.Setenv("HOME", tmpDir)
	defer os.Setenv("HOME", origHome)

	profile := "test-profile"
	headers := map[string]string{
		"x-user-email": "test@example.com",
		"x-user-id":    "12345",
	}
	tokenExp := time.Now().Unix() + 3600 // 1 hour from now

	// Write
	err := WriteCachedHeaders(profile, headers, tokenExp)
	if err != nil {
		t.Fatalf("WriteCachedHeaders failed: %v", err)
	}

	// Verify files exist
	cacheDir := filepath.Join(tmpDir, ".claude-code-session")
	if _, err := os.Stat(filepath.Join(cacheDir, profile+"-otel-headers.json")); err != nil {
		t.Errorf("json cache file missing: %v", err)
	}
	if _, err := os.Stat(filepath.Join(cacheDir, profile+"-otel-headers.raw")); err != nil {
		t.Errorf("raw cache file missing: %v", err)
	}

	// Read back
	cached, err := ReadCachedHeaders(profile)
	if err != nil {
		t.Fatalf("ReadCachedHeaders failed: %v", err)
	}
	if cached["x-user-email"] != "test@example.com" {
		t.Errorf("x-user-email = %q, want test@example.com", cached["x-user-email"])
	}
}

func TestReadCachedHeaders_ExpiredTokenStillReturnsHeaders(t *testing.T) {
	tmpDir := t.TempDir()
	origHome := os.Getenv("HOME")
	os.Setenv("HOME", tmpDir)
	defer os.Setenv("HOME", origHome)

	profile := "expired-profile"
	headers := map[string]string{"x-user-email": "test@example.com"}
	tokenExp := time.Now().Unix() - 3600 // Expired 1 hour ago

	_ = WriteCachedHeaders(profile, headers, tokenExp)

	// Should still return headers — they're static user attributes
	cached, err := ReadCachedHeaders(profile)
	if err != nil {
		t.Fatalf("expected headers even with expired token, got error: %v", err)
	}
	if cached["x-user-email"] != "test@example.com" {
		t.Errorf("x-user-email = %q, want test@example.com", cached["x-user-email"])
	}
}

func TestReadCachedHeaders_Missing(t *testing.T) {
	tmpDir := t.TempDir()
	origHome := os.Getenv("HOME")
	os.Setenv("HOME", tmpDir)
	defer os.Setenv("HOME", origHome)

	_, err := ReadCachedHeaders("nonexistent")
	if err == nil {
		t.Error("expected error for missing cache")
	}
}

func TestReadCachedHeaders_OldSchemaIsMiss(t *testing.T) {
	// A cache file written by an older binary (no schema_version field, or
	// value < current) must be treated as a miss so the upgraded binary
	// re-extracts headers including any newly-added keys (x-project in v2).
	tmpDir := t.TempDir()
	origHome := os.Getenv("HOME")
	os.Setenv("HOME", tmpDir)
	defer os.Setenv("HOME", origHome)

	profile := "legacy"
	cacheDir := filepath.Join(tmpDir, ".claude-code-session")
	if err := os.MkdirAll(cacheDir, 0700); err != nil {
		t.Fatalf("mkdir: %v", err)
	}
	// Simulate a v1 cache file: no schema_version, has headers.
	legacyJSON := `{"headers":{"x-user-email":"legacy@example.com"},"token_exp":` +
		timeFutureStr() + `,"cached_at":1000}`
	path := filepath.Join(cacheDir, profile+"-otel-headers.json")
	if err := os.WriteFile(path, []byte(legacyJSON), 0600); err != nil {
		t.Fatalf("write legacy: %v", err)
	}

	_, err := ReadCachedHeaders(profile)
	if err == nil {
		t.Fatal("expected cache miss for legacy-schema file, got hit")
	}
}

func TestWriteCachedHeaders_StampsSchemaVersion(t *testing.T) {
	tmpDir := t.TempDir()
	origHome := os.Getenv("HOME")
	os.Setenv("HOME", tmpDir)
	defer os.Setenv("HOME", origHome)

	profile := "versioned"
	headers := map[string]string{"x-project": "Alpha"}
	if err := WriteCachedHeaders(profile, headers, time.Now().Unix()+3600); err != nil {
		t.Fatalf("write: %v", err)
	}
	// Read back successfully -- write path must stamp the current schema version.
	if _, err := ReadCachedHeaders(profile); err != nil {
		t.Fatalf("freshly-written cache should read clean, got: %v", err)
	}
}

func TestReadCachedHeaders_EmptyHeadersMapIsHit(t *testing.T) {
	// Regression: len(entry.Headers)==0 was treated as a cache miss, forcing a
	// full credential-process round-trip on every turn when the server legitimately
	// returns {} (anonymous / no-attribute mode). Must be a hit.
	tmpDir := t.TempDir()
	origHome := os.Getenv("HOME")
	os.Setenv("HOME", tmpDir)
	defer os.Setenv("HOME", origHome)

	profile := "empty-headers"
	cacheDir := filepath.Join(tmpDir, ".claude-code-session")
	if err := os.MkdirAll(cacheDir, 0700); err != nil {
		t.Fatalf("mkdir: %v", err)
	}
	emptyJSON := `{"schema_version":` + fmt.Sprintf("%d", currentCacheSchemaVersion) +
		`,"headers":{},"token_exp":` + timeFutureStr() + `,"cached_at":1000}`
	path := filepath.Join(cacheDir, profile+"-otel-headers.json")
	if err := os.WriteFile(path, []byte(emptyJSON), 0600); err != nil {
		t.Fatalf("write: %v", err)
	}

	headers, err := ReadCachedHeaders(profile)
	if err != nil {
		t.Fatalf("empty headers map should be a cache hit, got error: %v", err)
	}
	if headers == nil {
		t.Fatal("expected non-nil map for empty headers hit")
	}
}

func TestWriteTwiceOverwritesCacheFile(t *testing.T) {
	// Regression: on Windows os.Rename raises FileExistsError when the
	// destination already exists; the Go atomicWrite uses os.Rename too and
	// would have silently failed, leaving the cache permanently stale.
	// os.Rename on Windows now calls MoveFileExW with MOVEFILE_REPLACE_EXISTING
	// so this is safe, but keep the test to catch any future regression.
	tmpDir := t.TempDir()
	origHome := os.Getenv("HOME")
	os.Setenv("HOME", tmpDir)
	defer os.Setenv("HOME", origHome)

	profile := "overwrite-test"
	first := map[string]string{"x-user-email": "first@example.com"}
	second := map[string]string{"x-user-email": "second@example.com"}
	exp := time.Now().Unix() + 3600

	if err := WriteCachedHeaders(profile, first, exp); err != nil {
		t.Fatalf("first write: %v", err)
	}
	if err := WriteCachedHeaders(profile, second, exp); err != nil {
		t.Fatalf("second write: %v", err)
	}

	cached, err := ReadCachedHeaders(profile)
	if err != nil {
		t.Fatalf("read after second write: %v", err)
	}
	if cached["x-user-email"] != "second@example.com" {
		t.Errorf("x-user-email = %q, want second@example.com", cached["x-user-email"])
	}
}

func timeFutureStr() string {
	// Helper to keep legacyJSON literal readable.
	return "9999999999"
}
