package storage

import (
	"os"
	"path/filepath"
	"testing"
	"time"
)

func TestQuotaState_ReadWriteCycle(t *testing.T) {
	// Use a temp dir as home
	tmpDir := t.TempDir()
	t.Setenv("HOME", tmpDir)
	t.Setenv("USERPROFILE", tmpDir) // Windows compat

	// Ensure the target directory exists
	os.MkdirAll(filepath.Join(tmpDir, "claude-code-with-bedrock"), 0755)

	profile := "test-profile"

	// Initially should return zero time
	ts := ReadQuotaState(profile)
	if !ts.IsZero() {
		t.Errorf("expected zero time for fresh state, got %v", ts)
	}

	// Save state
	err := SaveQuotaState(profile)
	if err != nil {
		t.Fatalf("SaveQuotaState failed: %v", err)
	}

	// Read back — should be within last 2 seconds
	ts = ReadQuotaState(profile)
	if ts.IsZero() {
		t.Fatal("expected non-zero time after save")
	}
	if time.Since(ts) > 2*time.Second {
		t.Errorf("timestamp too old: %v (now: %v)", ts, time.Now())
	}
}

func TestQuotaState_IntervalCheck(t *testing.T) {
	tmpDir := t.TempDir()
	t.Setenv("HOME", tmpDir)
	t.Setenv("USERPROFILE", tmpDir)
	os.MkdirAll(filepath.Join(tmpDir, "claude-code-with-bedrock"), 0755)

	profile := "interval-test"

	// No state = zero time (should trigger re-check)
	ts := ReadQuotaState(profile)
	if !ts.IsZero() {
		t.Fatal("expected zero time initially")
	}

	// Save, then immediately read — should be recent (within interval)
	_ = SaveQuotaState(profile)
	ts = ReadQuotaState(profile)
	interval := 30 * time.Minute
	if time.Since(ts) >= interval {
		t.Errorf("freshly saved state should be within interval")
	}
}

func TestQuotaState_CorruptFile(t *testing.T) {
	tmpDir := t.TempDir()
	t.Setenv("HOME", tmpDir)
	t.Setenv("USERPROFILE", tmpDir)

	dir := filepath.Join(tmpDir, "claude-code-with-bedrock")
	os.MkdirAll(dir, 0755)

	// Write garbage
	os.WriteFile(filepath.Join(dir, ".quota-state-corrupt.json"), []byte("not json"), 0600)

	ts := ReadQuotaState("corrupt")
	if !ts.IsZero() {
		t.Errorf("expected zero time for corrupt file, got %v", ts)
	}
}
