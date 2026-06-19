package main

import (
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
	"time"

	"ccwb-go/internal/config"
	"ccwb-go/internal/storage"
)

func boolPtr(b bool) *bool { return &b }

// writeMonitoringToken seeds a session-mode monitoring token file with the
// given token and expiry so storage.GetMonitoringToken returns it.
func writeMonitoringToken(t *testing.T, home, profile, token string, exp int64) {
	t.Helper()
	dir := filepath.Join(home, ".claude-code-session")
	if err := os.MkdirAll(dir, 0o700); err != nil {
		t.Fatalf("mkdir: %v", err)
	}
	data := map[string]interface{}{
		"token":   token,
		"expires": exp,
		"email":   "test@example.com",
		"profile": profile,
	}
	raw, err := json.Marshal(data)
	if err != nil {
		t.Fatalf("marshal: %v", err)
	}
	path := filepath.Join(dir, profile+"-monitoring.json")
	if err := os.WriteFile(path, raw, 0o600); err != nil {
		t.Fatalf("write: %v", err)
	}
}

// TestGetMCPAuthHeader_OutputShape pins the exact JSON the header mode emits,
// which is the contract Python must match byte-for-byte (credential-helper-parity).
func TestGetMCPAuthHeader_OutputShape(t *testing.T) {
	out, err := json.Marshal(map[string]string{"Authorization": "Bearer tok"})
	if err != nil {
		t.Fatalf("marshal: %v", err)
	}
	const want = `{"Authorization":"Bearer tok"}`
	if string(out) != want {
		t.Fatalf("header JSON shape = %q, want %q", string(out), want)
	}
}

// TestGetMCPAuthHeader_CachedToken verifies a valid cached token is returned as
// a Bearer auth header without any browser/network side effects.
func TestGetMCPAuthHeader_CachedToken(t *testing.T) {
	tmpDir := t.TempDir()
	t.Setenv("HOME", tmpDir)
	t.Setenv("USERPROFILE", tmpDir) // Windows
	// Ensure no env token leaks in from the host.
	t.Setenv("CLAUDE_CODE_MONITORING_TOKEN", "")

	profile := "test-mcp-auth-cached"
	// Expiry well beyond the 600s buffer in storage.GetMonitoringToken.
	writeMonitoringToken(t, tmpDir, profile, "cached-id-token", time.Now().Unix()+3600)

	cfg := &config.ProfileConfig{
		ClientID:          "test-client",
		ProviderDomain:    "test.example.com",
		CredentialStorage: "session",
		SsoEnabled:        boolPtr(true),
	}
	app := &credentialApp{profile: profile, cfg: cfg, providerType: "okta"}

	if code := app.getMCPAuthHeader(); code != 0 {
		t.Fatalf("getMCPAuthHeader exit = %d, want 0", code)
	}
}

// TestGetMCPAuthHeader_NoToken verifies a clean non-zero exit when no valid
// token is cached and no refresh_token is available — never hangs, never opens
// a browser (getMCPAuthHeader has no authenticate() fall-through by design).
func TestGetMCPAuthHeader_NoToken(t *testing.T) {
	tmpDir := t.TempDir()
	t.Setenv("HOME", tmpDir)
	t.Setenv("USERPROFILE", tmpDir)
	t.Setenv("CLAUDE_CODE_MONITORING_TOKEN", "")
	if err := os.MkdirAll(filepath.Join(tmpDir, ".claude-code-session"), 0o700); err != nil {
		t.Fatalf("mkdir: %v", err)
	}

	profile := "test-mcp-auth-empty"
	t.Cleanup(func() { storage.ClearRefreshToken(profile) })

	cfg := &config.ProfileConfig{
		ClientID:          "test-client",
		ProviderDomain:    "test.invalid.example.com", // unreachable if refresh were attempted
		CredentialStorage: "session",
		SsoEnabled:        boolPtr(true),
	}
	app := &credentialApp{profile: profile, cfg: cfg, providerType: "okta"}

	if code := app.getMCPAuthHeader(); code != 1 {
		t.Fatalf("getMCPAuthHeader exit = %d, want 1 (clean failure)", code)
	}
}

// TestGetMCPAuthHeader_EnvToken verifies the env-var token shortcut also works,
// matching getMonitoringToken's CLAUDE_CODE_MONITORING_TOKEN precedence.
func TestGetMCPAuthHeader_EnvToken(t *testing.T) {
	tmpDir := t.TempDir()
	t.Setenv("HOME", tmpDir)
	t.Setenv("USERPROFILE", tmpDir)
	t.Setenv("CLAUDE_CODE_MONITORING_TOKEN", "env-supplied-token")

	cfg := &config.ProfileConfig{
		ClientID:          "test-client",
		ProviderDomain:    "test.example.com",
		CredentialStorage: "session",
		SsoEnabled:        boolPtr(true),
	}
	app := &credentialApp{profile: "test-mcp-auth-env", cfg: cfg, providerType: "okta"}

	if code := app.getMCPAuthHeader(); code != 0 {
		t.Fatalf("getMCPAuthHeader exit = %d, want 0 with env token", code)
	}
}
