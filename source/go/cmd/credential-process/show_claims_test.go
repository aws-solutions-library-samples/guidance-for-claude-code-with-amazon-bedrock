// ABOUTME: Tests for --show-claims — full ID-token claim dump for IdP diagnostics
// ABOUTME: (what groups/department/custom claims is Okta actually sending?).
package main

import (
	"encoding/json"
	"os"
	"strings"
	"testing"
	"time"

	"ccwb-go/internal/config"
)

// TestShowClaims_CachedToken verifies the full claim set of a cached token is
// printed as JSON without any browser/network side effects.
func TestShowClaims_CachedToken(t *testing.T) {
	tmpDir := t.TempDir()
	t.Setenv("HOME", tmpDir)
	t.Setenv("USERPROFILE", tmpDir) // Windows
	t.Setenv("CLAUDE_CODE_MONITORING_TOKEN", "")

	profile := "test-show-claims"
	token := fakeJWT(t, map[string]interface{}{
		"email":             "user@example.com",
		"sub":               "00u1abcd",
		"groups":            []string{"engineering", "platform-team"},
		"custom:department": "R&D",
		"exp":               time.Now().Unix() + 3600,
	})
	writeMonitoringToken(t, tmpDir, profile, token, time.Now().Unix()+3600)

	cfg := &config.ProfileConfig{
		ClientID:          "test-client",
		ProviderDomain:    "test.example.com",
		CredentialStorage: "session",
		SsoEnabled:        boolPtr(true),
	}
	app := &credentialApp{profile: profile, cfg: cfg, providerType: "okta"}

	r, w, _ := os.Pipe()
	old := os.Stdout
	os.Stdout = w
	code := app.showClaims()
	w.Close()
	os.Stdout = old

	if code != 0 {
		t.Fatalf("showClaims exit = %d, want 0", code)
	}

	var buf [16384]byte
	n, _ := r.Read(buf[:])
	out := string(buf[:n])

	var claims map[string]interface{}
	if err := json.Unmarshal([]byte(out), &claims); err != nil {
		t.Fatalf("output is not valid JSON: %v\n%s", err, out)
	}
	if claims["email"] != "user@example.com" {
		t.Errorf("email claim = %v", claims["email"])
	}
	if claims["custom:department"] != "R&D" {
		t.Errorf("custom claim missing: %v", claims["custom:department"])
	}
	groups, _ := claims["groups"].([]interface{})
	if len(groups) != 2 {
		t.Errorf("groups claim = %v, want 2 entries", claims["groups"])
	}
}

// TestShowClaims_HelpTextAdvertisesDiagnostic pins the flag registration so
// the diagnostic stays discoverable via --help.
func TestShowClaims_HelpTextAdvertisesDiagnostic(t *testing.T) {
	src, err := os.ReadFile("main.go")
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(string(src), `flag.Bool("show-claims"`) {
		t.Fatal("--show-claims flag registration missing from main.go")
	}
}
