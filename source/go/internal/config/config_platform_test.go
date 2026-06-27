package config

import (
	"runtime"
	"testing"
)

// TestCredentialProcessPathWindows verifies that on Windows the credential
// process binary path includes the .exe extension. This prevents issue #407
// where the binary wasn't found because the extension was missing.
func TestCredentialProcessPathHasExeOnWindows(t *testing.T) {
	if runtime.GOOS != "windows" {
		t.Skip("Windows-only test")
	}
	path := CredentialProcessPath()
	if len(path) < 4 || path[len(path)-4:] != ".exe" {
		t.Errorf("CredentialProcessPath() = %q; want .exe suffix on Windows", path)
	}
}

// TestCredentialProcessPathNoExeOnNonWindows verifies that on non-Windows
// platforms the credential process binary path does NOT include .exe.
func TestCredentialProcessPathNoExeOnNonWindows(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("non-Windows-only test")
	}
	path := CredentialProcessPath()
	if len(path) >= 4 && path[len(path)-4:] == ".exe" {
		t.Errorf("CredentialProcessPath() = %q; want no .exe suffix on %s", path, runtime.GOOS)
	}
}

// TestCredentialProcessPathContainsInstallDir verifies the path includes
// the expected install directory name regardless of platform.
func TestCredentialProcessPathContainsInstallDir(t *testing.T) {
	path := CredentialProcessPath()
	if !contains(path, "claude-code-with-bedrock") {
		t.Errorf("CredentialProcessPath() = %q; want 'claude-code-with-bedrock' in path", path)
	}
}

func contains(s, substr string) bool {
	return len(s) >= len(substr) && (s == substr || len(s) > len(substr) && searchSubstring(s, substr))
}

func searchSubstring(s, substr string) bool {
	for i := 0; i <= len(s)-len(substr); i++ {
		if s[i:i+len(substr)] == substr {
			return true
		}
	}
	return false
}
