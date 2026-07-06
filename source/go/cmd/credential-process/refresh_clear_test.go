package main

// ABOUTME: Regression tests for the OTEL-bearer undercount bug —
// ABOUTME: refresh_token must survive transient failures and only clear on invalid_grant.

import (
	"net/http"
	"net/http/httptest"
	"os"
	"testing"

	"ccwb-go/internal/config"
	"ccwb-go/internal/storage"
)

// newRefreshApp builds a credentialApp whose refresh_token exchange targets a
// test server. It uses providerType "generic" so tryRefreshToken reads the
// endpoint straight from cfg.OIDCTokenEndpoint (no domain concatenation), and a
// session-storage temp HOME so the refresh_token round-trips through a real file.
func newRefreshApp(t *testing.T, profile, tokenURL string) *credentialApp {
	t.Helper()
	tmp := t.TempDir()
	t.Setenv("HOME", tmp)
	t.Setenv("USERPROFILE", tmp)
	if err := os.MkdirAll(tmp+"/.claude-code-session", 0o700); err != nil {
		t.Fatalf("mkdir: %v", err)
	}
	t.Cleanup(func() { storage.ClearRefreshToken(profile) })

	if err := storage.SaveRefreshToken(profile, "session", "rt_original"); err != nil {
		t.Fatalf("SaveRefreshToken: %v", err)
	}
	cfg := &config.ProfileConfig{
		ClientID:          "test-client",
		OIDCTokenEndpoint: tokenURL,
		CredentialStorage: "session",
	}
	return &credentialApp{profile: profile, cfg: cfg, providerType: "generic"}
}

// TestTryRefreshToken_InvalidGrantClearsToken: a definitive invalid_grant
// rejection means the refresh_token is dead — it must be cleared.
func TestTryRefreshToken_InvalidGrantClearsToken(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusBadRequest)
		_, _ = w.Write([]byte(`{"error":"invalid_grant","error_description":"revoked"}`))
	}))
	defer srv.Close()

	profile := "test-refresh-invalid-grant"
	app := newRefreshApp(t, profile, srv.URL)

	if creds := app.tryRefreshToken(); creds != nil {
		t.Fatalf("tryRefreshToken returned non-nil on invalid_grant: %+v", creds)
	}
	if got := storage.LoadRefreshToken(profile, "session"); got != "" {
		t.Errorf("refresh_token = %q after invalid_grant, want cleared", got)
	}
}

// TestTryRefreshToken_ServerErrorRetainsToken: a 5xx is transient — the
// refresh_token must survive so a later cycle can retry. This is the core of the
// undercount fix: a single server blip must NOT permanently disable silent
// renewal (which previously forced a full browser login to recover).
func TestTryRefreshToken_ServerErrorRetainsToken(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusInternalServerError)
		_, _ = w.Write([]byte(`{"error":"server_error"}`))
	}))
	defer srv.Close()

	profile := "test-refresh-server-error"
	app := newRefreshApp(t, profile, srv.URL)

	if creds := app.tryRefreshToken(); creds != nil {
		t.Fatalf("tryRefreshToken returned non-nil on 500: %+v", creds)
	}
	if got := storage.LoadRefreshToken(profile, "session"); got != "rt_original" {
		t.Errorf("refresh_token = %q after transient 500, want retained (%q)", got, "rt_original")
	}
}

// TestRefreshIDTokenOnly_ServerErrorRetainsToken guards the twin clear site on
// the MCP-auth-header path (refreshIDTokenOnly), which had the identical
// clear-on-any-failure bug.
func TestRefreshIDTokenOnly_ServerErrorRetainsToken(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusBadGateway)
		_, _ = w.Write([]byte(`bad gateway`))
	}))
	defer srv.Close()

	profile := "test-idtoken-only-server-error"
	app := newRefreshApp(t, profile, srv.URL)

	if tok := app.refreshIDTokenOnly(); tok != "" {
		t.Fatalf("refreshIDTokenOnly returned non-empty on 502: %q", tok)
	}
	if got := storage.LoadRefreshToken(profile, "session"); got != "rt_original" {
		t.Errorf("refresh_token = %q after transient 502, want retained (%q)", got, "rt_original")
	}
}

// TestRefreshIDTokenOnly_InvalidGrantClearsToken confirms the MCP path still
// clears on a definitive rejection.
func TestRefreshIDTokenOnly_InvalidGrantClearsToken(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusBadRequest)
		_, _ = w.Write([]byte(`{"error":"invalid_grant"}`))
	}))
	defer srv.Close()

	profile := "test-idtoken-only-invalid-grant"
	app := newRefreshApp(t, profile, srv.URL)

	if tok := app.refreshIDTokenOnly(); tok != "" {
		t.Fatalf("refreshIDTokenOnly returned non-empty on invalid_grant: %q", tok)
	}
	if got := storage.LoadRefreshToken(profile, "session"); got != "" {
		t.Errorf("refresh_token = %q after invalid_grant, want cleared", got)
	}
}
