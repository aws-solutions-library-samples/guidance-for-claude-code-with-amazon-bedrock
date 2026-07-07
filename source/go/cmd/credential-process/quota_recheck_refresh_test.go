package main

import (
	"net/http"
	"net/http/httptest"
	"os"
	"testing"

	"ccwb-go/internal/config"
	"ccwb-go/internal/storage"
)

// TestPerformQuotaRecheck_AttemptsRefreshWhenTokenExpired is the regression
// guard for the bug where an over-quota OIDC user got NO warning on the
// cache-hit fast path.
//
// Background: run() serves cached AWS credentials immediately and the ONLY
// quota logic on that path is performQuotaRecheck(). It read the cached
// monitoring token (id_token) and, when that token had aged past the 10-min
// buffer in storage.GetMonitoringToken, returned true (fail-open) WITHOUT
// attempting a refresh_token exchange. Since cached AWS creds last ~12h but
// the id_token expires in ~1h, the steady state for an active user is
// "valid AWS creds + expired id_token" — so the quota API was never called,
// printQuotaWarning()/printQuotaBlocked() never fired, and the user blew
// past quota silently. PRs #655/#657/#658 fixed the warning *display* but
// all of it sits downstream of a successful quota.Check() that never ran.
//
// The fix mirrors the getMonitoringToken() handler: when the cached id_token
// is empty, attempt tryRefreshToken() to silently mint a fresh id_token
// before giving up.
//
// This test proves the exchange is *attempted*: with a refresh_token stored and
// an IdP that returns a definitive invalid_grant, tryRefreshToken fails and
// clears the (revoked) refresh_token. Before the fix, performQuotaRecheck
// returned on the empty-token check and NEVER touched the refresh_token, so it
// would remain stored. The cleared-token assertion therefore fails without the
// fix and passes with it.
//
// NOTE: the IdP must return invalid_grant (not merely be unreachable) — a
// transient/unreachable failure now correctly RETAINS the token (that retention
// is the OTEL-bearer undercount fix), so only a definitive rejection clears it.
func TestPerformQuotaRecheck_AttemptsRefreshWhenTokenExpired(t *testing.T) {
	// IdP that definitively rejects the refresh_token → tryRefreshToken clears it.
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusBadRequest)
		_, _ = w.Write([]byte(`{"error":"invalid_grant","error_description":"revoked"}`))
	}))
	defer srv.Close()

	tmpDir := t.TempDir()
	t.Setenv("HOME", tmpDir)
	t.Setenv("USERPROFILE", tmpDir) // Windows
	// Ensure no ambient env token short-circuits storage.GetMonitoringToken.
	t.Setenv("CLAUDE_CODE_MONITORING_TOKEN", "")
	if err := os.MkdirAll(tmpDir+"/.claude-code-session", 0o700); err != nil {
		t.Fatalf("mkdir: %v", err)
	}

	profile := "test-quota-recheck-refresh-attempted"
	t.Cleanup(func() {
		storage.ClearRefreshToken(profile)
	})

	if err := storage.SaveRefreshToken(profile, "session", "rt_test_value"); err != nil {
		t.Fatalf("SaveRefreshToken: %v", err)
	}

	cfg := &config.ProfileConfig{
		ClientID:          "test-client",
		OIDCTokenEndpoint: srv.URL, // generic provider reads the endpoint directly
		CredentialStorage: "session",
		QuotaAPIEndpoint:  "https://quota.invalid.example.com",
		QuotaFailMode:     "open",
		QuotaCheckTimeout: 1,
	}
	app := &credentialApp{profile: profile, cfg: cfg, providerType: "generic"}

	// Exchange fails (unreachable IdP); with no usable token the recheck
	// fails open and allows cached credentials through.
	if allowed := app.performQuotaRecheck(); !allowed {
		t.Fatalf("performQuotaRecheck returned false (blocked) when it should fail open on no usable token")
	}

	// The core regression assertion: the refresh_token was consumed by a
	// definitive invalid_grant exchange. If it is still present, performQuotaRecheck
	// never attempted the exchange — the fix is not wired in.
	if got := storage.LoadRefreshToken(profile, "session"); got != "" {
		t.Errorf("refresh_token not cleared after invalid_grant exchange (got %q); "+
			"performQuotaRecheck did NOT attempt tryRefreshToken — quota recheck "+
			"will silently fail open for over-quota users with expired id_tokens", got)
	}

	// And because no usable token was obtained, the quota API was never
	// queried, so the check timestamp must NOT have been persisted — the
	// next invocation should retry once a fresh token is available.
	if ts := storage.ReadQuotaState(profile); !ts.IsZero() {
		t.Errorf("quota-state timestamp was saved (%v) despite no quota check running; "+
			"a frozen timestamp would suppress rechecks for the full interval", ts)
	}
}

// TestPerformQuotaRecheck_NoTokenNoRefreshFailsOpenQuietly preserves the
// genuinely-unrecoverable behavior: no cached id_token AND no stored
// refresh_token. performQuotaRecheck must fail open (return true) without a
// browser flow — the cache-hit path runs on every AWS API call and must
// never block on it — and must not persist a check timestamp, so the next
// invocation retries once credentials are available.
func TestPerformQuotaRecheck_NoTokenNoRefreshFailsOpenQuietly(t *testing.T) {
	tmpDir := t.TempDir()
	t.Setenv("HOME", tmpDir)
	t.Setenv("USERPROFILE", tmpDir)
	t.Setenv("CLAUDE_CODE_MONITORING_TOKEN", "")
	if err := os.MkdirAll(tmpDir+"/.claude-code-session", 0o700); err != nil {
		t.Fatalf("mkdir: %v", err)
	}

	profile := "test-quota-recheck-no-creds"

	cfg := &config.ProfileConfig{
		ClientID:          "test-client",
		ProviderDomain:    "test.invalid.example.com",
		CredentialStorage: "session",
		QuotaAPIEndpoint:  "https://quota.invalid.example.com",
		QuotaFailMode:     "open",
		QuotaCheckTimeout: 1,
	}
	app := &credentialApp{profile: profile, cfg: cfg, providerType: "okta"}

	if allowed := app.performQuotaRecheck(); !allowed {
		t.Fatalf("performQuotaRecheck returned false (blocked) with no token and no refresh_token; must fail open")
	}

	if ts := storage.ReadQuotaState(profile); !ts.IsZero() {
		t.Errorf("quota-state timestamp saved (%v) when no quota check ran", ts)
	}
}
