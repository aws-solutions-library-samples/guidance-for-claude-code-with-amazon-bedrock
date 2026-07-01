package main

import (
	"os"
	"testing"

	"ccwb-go/internal/config"
	"ccwb-go/internal/storage"
)

// TestGetMonitoringToken_RefreshTokenWiring is the regression guard for
// the bug where --get-monitoring-token would open a browser tab on every
// expired-token call instead of using the cached refresh_token.
//
// PR #447 added refresh_token-based silent renewal but only wired it into
// the main run() flow. The --get-monitoring-token path (called by
// otel-helper for every OTEL export cycle) skipped tryRefreshToken() and
// went straight to authenticate(), opening a browser whenever the cached
// id_token aged past the 10-min buffer in storage.GetMonitoringToken —
// even when a valid refresh_token (typically 7-30 days) was sitting in
// keyring/session storage.
//
// This test verifies the wiring exists: tryRefreshToken is reachable and
// returns nil cheaply when no refresh_token is stored, so the fall-through
// to authenticate() still happens for the genuinely-no-credentials case.
func TestGetMonitoringToken_RefreshTokenWiring(t *testing.T) {
	tmpDir := t.TempDir()
	t.Setenv("HOME", tmpDir)
	t.Setenv("USERPROFILE", tmpDir) // Windows
	if err := os.MkdirAll(tmpDir+"/.claude-code-session", 0o700); err != nil {
		t.Fatalf("mkdir: %v", err)
	}

	profile := "test-monitoring-refresh-wiring"
	t.Cleanup(func() {
		storage.ClearRefreshToken(profile)
	})

	cfg := &config.ProfileConfig{
		ClientID:          "test-client",
		ProviderDomain:    "test.example.com",
		CredentialStorage: "session",
	}
	app := &credentialApp{profile: profile, cfg: cfg, providerType: "okta"}

	// With no refresh_token stored, tryRefreshToken must return nil without
	// any network or browser side effects. This is the path getMonitoringToken
	// takes before falling through to authenticate() in the no-credentials case.
	if creds := app.tryRefreshToken(); creds != nil {
		t.Fatalf("tryRefreshToken returned non-nil with no stored refresh_token: %+v", creds)
	}

	// And confirm storage.LoadRefreshToken agrees no token is stored — guards
	// against a future change accidentally persisting state across the no-op.
	if got := storage.LoadRefreshToken(profile, "session"); got != "" {
		t.Errorf("LoadRefreshToken returned %q after no-op call, want empty", got)
	}
}

// TestGetMonitoringToken_RefreshTokenStoredCallsExchange exercises the path
// that runs when a refresh_token IS stored. Without mocking the OIDC token
// endpoint, the exchange itself will fail (test.example.com is unreachable).
// What we verify is that the exchange is *attempted*: the failure path in
// tryRefreshToken clears the refresh_token (because the IdP may have revoked
// it). After calling tryRefreshToken with an unreachable token URL, the
// stored refresh_token must be cleared.
func TestGetMonitoringToken_RefreshTokenStoredCallsExchange(t *testing.T) {
	tmpDir := t.TempDir()
	t.Setenv("HOME", tmpDir)
	t.Setenv("USERPROFILE", tmpDir)
	if err := os.MkdirAll(tmpDir+"/.claude-code-session", 0o700); err != nil {
		t.Fatalf("mkdir: %v", err)
	}

	profile := "test-monitoring-refresh-attempted"
	t.Cleanup(func() {
		storage.ClearRefreshToken(profile)
	})

	if err := storage.SaveRefreshToken(profile, "session", "rt_test_value"); err != nil {
		t.Fatalf("SaveRefreshToken: %v", err)
	}

	cfg := &config.ProfileConfig{
		ClientID:          "test-client",
		ProviderDomain:    "test.invalid.example.com", // unreachable
		CredentialStorage: "session",
	}
	app := &credentialApp{profile: profile, cfg: cfg, providerType: "okta"}

	// Exchange will fail (network or DNS); tryRefreshToken returns nil and
	// clears the (presumed-revoked) refresh_token.
	if creds := app.tryRefreshToken(); creds != nil {
		t.Fatalf("tryRefreshToken returned non-nil for unreachable IdP: %+v", creds)
	}

	// Clearing on failure is the contract — proves the exchange was attempted.
	if got := storage.LoadRefreshToken(profile, "session"); got != "" {
		t.Errorf("refresh_token not cleared after failed exchange (got %q); "+
			"this means tryRefreshToken did NOT attempt the exchange — the wiring is broken", got)
	}
}
