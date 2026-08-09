package config

import (
	"runtime"
	"strings"
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
	if !strings.Contains(path, "claude-code-with-bedrock") {
		t.Errorf("CredentialProcessPath() = %q; want 'claude-code-with-bedrock' in path", path)
	}
}
