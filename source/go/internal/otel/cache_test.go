package otel

import (
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

func TestReadCachedHeaders_Expired(t *testing.T) {
	tmpDir := t.TempDir()
	origHome := os.Getenv("HOME")
	os.Setenv("HOME", tmpDir)
	defer os.Setenv("HOME", origHome)

	profile := "expired-profile"
	headers := map[string]string{"x-user-email": "test@example.com"}
	tokenExp := time.Now().Unix() + 300 // Only 5 min left (< 10 min buffer)

	_ = WriteCachedHeaders(profile, headers, tokenExp)

	_, err := ReadCachedHeaders(profile)
	if err == nil {
		t.Error("expected error for expired cache")
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
