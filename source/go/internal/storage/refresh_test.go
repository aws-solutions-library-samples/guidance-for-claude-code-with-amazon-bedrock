package storage

import (
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
)

func TestSaveAndLoadRefreshToken(t *testing.T) {
	// Use a temp dir as session dir
	tmpDir := t.TempDir()
	origHome := os.Getenv("HOME")
	origUserProfile := os.Getenv("USERPROFILE")
	os.Setenv("HOME", tmpDir)
	os.Setenv("USERPROFILE", tmpDir) // Windows: os.UserHomeDir() uses USERPROFILE
	defer os.Setenv("HOME", origHome)
	defer os.Setenv("USERPROFILE", origUserProfile)

	// Ensure session dir exists
	os.MkdirAll(filepath.Join(tmpDir, ".claude-code-session"), 0700)

	// Save
	err := SaveRefreshToken("TestProfile", "session", "rt_test_token_abc123")
	if err != nil {
		t.Fatalf("SaveRefreshToken failed: %v", err)
	}

	// Load
	token := LoadRefreshToken("TestProfile", "session")
	if token != "rt_test_token_abc123" {
		t.Errorf("LoadRefreshToken got %q, want %q", token, "rt_test_token_abc123")
	}

	// Verify file permissions
	path := filepath.Join(tmpDir, ".claude-code-session", "TestProfile-refresh.json")
	info, err := os.Stat(path)
	if err != nil {
		t.Fatalf("Stat failed: %v", err)
	}
	if info.Mode().Perm() != 0600 {
		t.Errorf("File permissions = %o, want 0600", info.Mode().Perm())
	}

	// Verify JSON structure
	raw, _ := os.ReadFile(path)
	var data map[string]interface{}
	json.Unmarshal(raw, &data)
	if data["refresh_token"] != "rt_test_token_abc123" {
		t.Errorf("JSON refresh_token = %v, want rt_test_token_abc123", data["refresh_token"])
	}
	if data["profile"] != "TestProfile" {
		t.Errorf("JSON profile = %v, want TestProfile", data["profile"])
	}
}

func TestLoadRefreshToken_Missing(t *testing.T) {
	tmpDir := t.TempDir()
	origHome := os.Getenv("HOME")
	os.Setenv("HOME", tmpDir)
	defer os.Setenv("HOME", origHome)

	token := LoadRefreshToken("NonExistent", "session")
	if token != "" {
		t.Errorf("LoadRefreshToken for missing profile got %q, want empty", token)
	}
}

func TestSaveRefreshToken_EmptyToken(t *testing.T) {
	tmpDir := t.TempDir()
	origHome := os.Getenv("HOME")
	os.Setenv("HOME", tmpDir)
	defer os.Setenv("HOME", origHome)

	// Saving empty token should be a no-op
	err := SaveRefreshToken("TestProfile", "session", "")
	if err != nil {
		t.Fatalf("SaveRefreshToken with empty token should not error: %v", err)
	}

	// File should not exist
	path := filepath.Join(tmpDir, ".claude-code-session", "TestProfile-refresh.json")
	if _, err := os.Stat(path); !os.IsNotExist(err) {
		t.Error("Empty refresh token should not create a file")
	}
}

func TestClearRefreshToken(t *testing.T) {
	tmpDir := t.TempDir()
	origHome := os.Getenv("HOME")
	os.Setenv("HOME", tmpDir)
	defer os.Setenv("HOME", origHome)

	os.MkdirAll(filepath.Join(tmpDir, ".claude-code-session"), 0700)

	// Save then clear
	SaveRefreshToken("TestProfile", "session", "rt_to_be_cleared")
	ClearRefreshToken("TestProfile")

	token := LoadRefreshToken("TestProfile", "session")
	if token != "" {
		t.Errorf("After ClearRefreshToken, got %q, want empty", token)
	}
}
