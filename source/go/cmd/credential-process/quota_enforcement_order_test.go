package main

// ABOUTME: Regression tests for #761 — quota must be enforced BEFORE the STS
// ABOUTME: exchange on the silent-refresh and refresh-token paths, and the
// ABOUTME: check must never be silently skipped when a quota endpoint is set.

import (
	"fmt"
	"net"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"ccwb-go/internal/config"
	"ccwb-go/internal/federation"
	"ccwb-go/internal/storage"
)

// stsRecorder is an httptest server that counts AssumeRoleWithWebIdentity
// calls and returns a syntactically valid credentials response. run() reaches
// it via AWS_ENDPOINT_URL_STS, which the SDK's config loader honors.
func stsRecorder(t *testing.T) (*httptest.Server, *int32) {
	t.Helper()
	var hits int32
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		atomic.AddInt32(&hits, 1)
		w.Header().Set("Content-Type", "text/xml")
		fmt.Fprint(w, `<AssumeRoleWithWebIdentityResponse xmlns="https://sts.amazonaws.com/doc/2011-06-15/">
  <AssumeRoleWithWebIdentityResult>
    <Credentials>
      <AccessKeyId>ASIAMOCKSTS12345</AccessKeyId>
      <SecretAccessKey>mock-secret</SecretAccessKey>
      <SessionToken>mock-session-token</SessionToken>
      <Expiration>2099-01-01T00:00:00Z</Expiration>
    </Credentials>
    <SubjectFromWebIdentityToken>user-123</SubjectFromWebIdentityToken>
  </AssumeRoleWithWebIdentityResult>
  <ResponseMetadata><RequestId>mock-request</RequestId></ResponseMetadata>
</AssumeRoleWithWebIdentityResponse>`)
	}))
	t.Cleanup(srv.Close)
	return srv, &hits
}

// quotaRecorder returns a quota API stub that counts /check calls and answers
// with the given allowed value.
func quotaRecorder(t *testing.T, allowed bool) (*httptest.Server, *int32) {
	t.Helper()
	var hits int32
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		atomic.AddInt32(&hits, 1)
		w.Header().Set("Content-Type", "application/json")
		if allowed {
			fmt.Fprint(w, `{"allowed": true, "reason": "within_limits", "message": "ok"}`)
			return
		}
		fmt.Fprint(w, `{"allowed": false, "reason": "quota_exceeded", "message": "Usage quota exceeded."}`)
	}))
	t.Cleanup(srv.Close)
	return srv, &hits
}

// freeLocalPort grabs an ephemeral port for run()'s port-lock acquisition so
// parallel test runs never collide on the default 8400.
func freeLocalPort(t *testing.T) int {
	t.Helper()
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatalf("reserve port: %v", err)
	}
	port := ln.Addr().(*net.TCPAddr).Port
	_ = ln.Close()
	return port
}

// newQuotaOrderEnv isolates HOME/session storage and points the AWS SDK at the
// mock STS server. Returns the temp home dir.
func newQuotaOrderEnv(t *testing.T, stsURL string) string {
	t.Helper()
	tmpDir := t.TempDir()
	t.Setenv("HOME", tmpDir)
	t.Setenv("USERPROFILE", tmpDir) // Windows
	t.Setenv("CLAUDE_CODE_MONITORING_TOKEN", "")
	t.Setenv("AWS_ENDPOINT_URL_STS", stsURL)
	t.Setenv("AWS_EC2_METADATA_DISABLED", "true")
	if err := os.MkdirAll(filepath.Join(tmpDir, ".claude-code-session"), 0o700); err != nil {
		t.Fatalf("mkdir: %v", err)
	}
	return tmpDir
}

func directSTSConfig(quotaURL string, port int) *config.ProfileConfig {
	return &config.ProfileConfig{
		ClientID:           "test-client",
		ProviderDomain:     "test.example.com",
		CredentialStorage:  "session",
		SsoEnabled:         boolPtr(true),
		FederationType:     "direct",
		FederatedRoleARN:   "arn:aws:iam::123456789012:role/TestRole",
		AWSRegion:          "us-east-1",
		MaxSessionDuration: 3600,
		QuotaAPIEndpoint:   quotaURL,
		QuotaFailMode:      "open",
		QuotaCheckTimeout:  2,
		RedirectPort:       port,
	}
}

// assertNoSavedCredentials fails the test when real (non-dummy) credentials
// were persisted for the profile.
func assertNoSavedCredentials(t *testing.T, profile string) {
	t.Helper()
	creds, err := storage.ReadFromCredentialsFile(profile)
	if err != nil || creds == nil || storage.IsExpiredDummy(creds) {
		return
	}
	t.Errorf("credentials were saved for profile %q despite quota block: AccessKeyId=%s",
		profile, creds.AccessKeyID)
}

// TestRun_SilentRefreshPath_QuotaBlockedBeforeSTS is the core regression test
// for #761: with a valid cached id_token and a quota API that answers
// allowed=false, run() must exit non-zero WITHOUT calling STS and WITHOUT
// persisting credentials. Before the fix, trySilentRefresh() exchanged and
// saved AWS credentials first and only then consulted the quota API.
func TestRun_SilentRefreshPath_QuotaBlockedBeforeSTS(t *testing.T) {
	setupNotificationTest(t)
	stsSrv, stsHits := stsRecorder(t)
	quotaSrv, quotaHits := quotaRecorder(t, false)
	tmpDir := newQuotaOrderEnv(t, stsSrv.URL)

	profile := "test-quota-order-silent-blocked"
	idToken := fakeJWT(t, map[string]interface{}{
		"sub": "user-123", "email": "test@example.com",
		"exp": float64(time.Now().Unix() + 3600),
	})
	writeMonitoringToken(t, tmpDir, profile, idToken, time.Now().Unix()+3600)

	app := &credentialApp{
		profile:      profile,
		cfg:          directSTSConfig(quotaSrv.URL, freeLocalPort(t)),
		providerType: "okta",
		redirectPort: 0,
	}
	app.redirectPort = app.cfg.RedirectPort

	res := captureMCPStdout(t, app.run)
	if res.code != 1 {
		t.Fatalf("run() = %d, want 1 (quota blocked)", res.code)
	}
	if res.stdout != "" {
		t.Errorf("run() printed to stdout despite quota block: %q", res.stdout)
	}
	if got := atomic.LoadInt32(quotaHits); got != 1 {
		t.Errorf("quota API hits = %d, want 1", got)
	}
	if got := atomic.LoadInt32(stsHits); got != 0 {
		t.Errorf("STS hits = %d, want 0 — credentials were exchanged before/despite the quota block", got)
	}
	assertNoSavedCredentials(t, profile)
}

// TestRun_RefreshTokenPath_QuotaBlockedBeforeSTS covers the refresh_token
// (Cowork 3P) path: quota must be checked with the freshly-exchanged id_token
// BEFORE any STS call, and a block must leave no credentials behind.
func TestRun_RefreshTokenPath_QuotaBlockedBeforeSTS(t *testing.T) {
	setupNotificationTest(t)
	stsSrv, stsHits := stsRecorder(t)
	quotaSrv, quotaHits := quotaRecorder(t, false)
	newQuotaOrderEnv(t, stsSrv.URL)

	profile := "test-quota-order-refresh-blocked"
	t.Cleanup(func() { storage.ClearRefreshToken(profile) })

	freshIDToken := fakeJWT(t, map[string]interface{}{
		"sub": "user-123", "email": "test@example.com",
		"exp": float64(time.Now().Unix() + 3600),
	})
	idpSrv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		fmt.Fprintf(w, `{"id_token": %q, "refresh_token": "rt_rotated", "token_type": "Bearer"}`, freshIDToken)
	}))
	defer idpSrv.Close()

	if err := storage.SaveRefreshToken(profile, "session", "rt_original"); err != nil {
		t.Fatalf("SaveRefreshToken: %v", err)
	}

	cfg := directSTSConfig(quotaSrv.URL, freeLocalPort(t))
	cfg.OIDCTokenEndpoint = idpSrv.URL
	app := &credentialApp{profile: profile, cfg: cfg, providerType: "generic", redirectPort: cfg.RedirectPort}

	res := captureMCPStdout(t, app.run)
	if res.code != 1 {
		t.Fatalf("run() = %d, want 1 (quota blocked)", res.code)
	}
	if res.stdout != "" {
		t.Errorf("run() printed to stdout despite quota block: %q", res.stdout)
	}
	if got := atomic.LoadInt32(quotaHits); got != 1 {
		t.Errorf("quota API hits = %d, want 1", got)
	}
	if got := atomic.LoadInt32(stsHits); got != 0 {
		t.Errorf("STS hits = %d, want 0 — credentials were exchanged before/despite the quota block", got)
	}
	assertNoSavedCredentials(t, profile)
}

// TestRun_RefreshTokenPath_ShortLivedTokenStillChecked pins the fix for the
// silent-skip variant of #761: the pre-fix code re-read the monitoring token
// from storage and skipped the quota check entirely when that read came back
// empty. An IdP issuing id_tokens with a lifetime inside the 10-minute
// storage buffer (exp - now <= 600s) made that skip systematic: credentials
// were issued with the quota API never called. The fix checks quota with the
// in-scope token, so the block must now fire.
func TestRun_RefreshTokenPath_ShortLivedTokenStillChecked(t *testing.T) {
	setupNotificationTest(t)
	stsSrv, stsHits := stsRecorder(t)
	quotaSrv, quotaHits := quotaRecorder(t, false)
	newQuotaOrderEnv(t, stsSrv.URL)

	profile := "test-quota-order-shortlived"
	t.Cleanup(func() { storage.ClearRefreshToken(profile) })

	// exp within the 600s buffer → storage.GetMonitoringToken returns ""
	shortLivedToken := fakeJWT(t, map[string]interface{}{
		"sub": "user-123", "email": "test@example.com",
		"exp": float64(time.Now().Unix() + 300),
	})
	idpSrv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		fmt.Fprintf(w, `{"id_token": %q, "token_type": "Bearer"}`, shortLivedToken)
	}))
	defer idpSrv.Close()

	if err := storage.SaveRefreshToken(profile, "session", "rt_original"); err != nil {
		t.Fatalf("SaveRefreshToken: %v", err)
	}

	cfg := directSTSConfig(quotaSrv.URL, freeLocalPort(t))
	cfg.OIDCTokenEndpoint = idpSrv.URL
	app := &credentialApp{profile: profile, cfg: cfg, providerType: "generic", redirectPort: cfg.RedirectPort}

	res := captureMCPStdout(t, app.run)
	if res.code != 1 {
		t.Fatalf("run() = %d, want 1 (quota blocked) — short-lived id_token must not skip the quota check", res.code)
	}
	if got := atomic.LoadInt32(quotaHits); got != 1 {
		t.Errorf("quota API hits = %d, want 1 — the check was silently skipped", got)
	}
	if got := atomic.LoadInt32(stsHits); got != 0 {
		t.Errorf("STS hits = %d, want 0", got)
	}
	assertNoSavedCredentials(t, profile)
}

// TestRun_SilentRefreshPath_QuotaAllowedIssuesCredentials proves the happy
// path still works after the reordering: quota allows → STS is called →
// credentials are printed and cached.
func TestRun_SilentRefreshPath_QuotaAllowedIssuesCredentials(t *testing.T) {
	setupNotificationTest(t)
	stsSrv, stsHits := stsRecorder(t)
	quotaSrv, quotaHits := quotaRecorder(t, true)
	tmpDir := newQuotaOrderEnv(t, stsSrv.URL)

	profile := "test-quota-order-allowed"
	idToken := fakeJWT(t, map[string]interface{}{
		"sub": "user-123", "email": "test@example.com",
		"exp": float64(time.Now().Unix() + 3600),
	})
	writeMonitoringToken(t, tmpDir, profile, idToken, time.Now().Unix()+3600)

	cfg := directSTSConfig(quotaSrv.URL, freeLocalPort(t))
	app := &credentialApp{profile: profile, cfg: cfg, providerType: "okta", redirectPort: cfg.RedirectPort}

	res := captureMCPStdout(t, app.run)
	if res.code != 0 {
		t.Fatalf("run() = %d, want 0 (quota allowed)", res.code)
	}
	if got := atomic.LoadInt32(quotaHits); got != 1 {
		t.Errorf("quota API hits = %d, want 1", got)
	}
	if got := atomic.LoadInt32(stsHits); got != 1 {
		t.Errorf("STS hits = %d, want 1", got)
	}
	creds, err := storage.ReadFromCredentialsFile(profile)
	if err != nil || creds == nil {
		t.Fatalf("expected saved credentials after allowed refresh, got err=%v", err)
	}
	if creds.AccessKeyID != "ASIAMOCKSTS12345" {
		t.Errorf("saved AccessKeyId = %q, want mock STS value", creds.AccessKeyID)
	}
}

// TestEnforceQuota_NoTokenHonorsFailMode pins the "never silently skip"
// contract: with a quota endpoint configured but no token available, the
// outcome is decided by quota_fail_mode instead of bypassing the check.
func TestEnforceQuota_NoTokenHonorsFailMode(t *testing.T) {
	cfgClosed := &config.ProfileConfig{QuotaAPIEndpoint: "https://quota.invalid.example.com", QuotaFailMode: "closed"}
	appClosed := &credentialApp{profile: "test-enforce-closed", cfg: cfgClosed}
	if appClosed.enforceQuota("") {
		t.Errorf("enforceQuota(\"\") = true with fail mode 'closed', want false (fail closed)")
	}

	cfgOpen := &config.ProfileConfig{QuotaAPIEndpoint: "https://quota.invalid.example.com", QuotaFailMode: "open"}
	appOpen := &credentialApp{profile: "test-enforce-open", cfg: cfgOpen}
	if !appOpen.enforceQuota("") {
		t.Errorf("enforceQuota(\"\") = false with fail mode 'open', want true")
	}

	cfgNone := &config.ProfileConfig{}
	appNone := &credentialApp{profile: "test-enforce-none", cfg: cfgNone}
	if !appNone.enforceQuota("") {
		t.Errorf("enforceQuota(\"\") = false with no quota endpoint, want true")
	}
}

// TestRunDesktopHelper_QuotaBlockedOnRefresh pins the desktop-helper (#761
// follow-on): the --desktop silent refresh previously minted a Bedrock bearer
// token with NO quota check at all. With CLAUDE_HELPER_CONTEXT=silent (no
// interactive fallback), a quota block must exit 1 without touching STS and
// without emitting a token.
func TestRunDesktopHelper_QuotaBlockedOnRefresh(t *testing.T) {
	setupNotificationTest(t)
	stsSrv, stsHits := stsRecorder(t)
	quotaSrv, quotaHits := quotaRecorder(t, false)
	newQuotaOrderEnv(t, stsSrv.URL)
	t.Setenv("CLAUDE_HELPER_CONTEXT", "silent")

	profile := "test-desktop-quota-blocked"
	t.Cleanup(func() { storage.ClearRefreshToken(profile) })

	freshIDToken := fakeJWT(t, map[string]interface{}{
		"sub": "user-123", "email": "test@example.com",
		"exp": float64(time.Now().Unix() + 3600),
	})
	idpSrv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		fmt.Fprintf(w, `{"id_token": %q, "token_type": "Bearer"}`, freshIDToken)
	}))
	defer idpSrv.Close()

	if err := storage.SaveRefreshToken(profile, "session", "rt_original"); err != nil {
		t.Fatalf("SaveRefreshToken: %v", err)
	}

	cfg := directSTSConfig(quotaSrv.URL, freeLocalPort(t))
	cfg.OIDCTokenEndpoint = idpSrv.URL
	app := &credentialApp{profile: profile, cfg: cfg, providerType: "generic", redirectPort: cfg.RedirectPort}

	res := captureMCPStdout(t, app.runDesktopHelper)
	if res.code != 1 {
		t.Fatalf("runDesktopHelper() = %d, want 1 (quota blocked)", res.code)
	}
	if res.stdout != "" {
		t.Errorf("runDesktopHelper() emitted output despite quota block: %q", res.stdout)
	}
	if got := atomic.LoadInt32(quotaHits); got != 1 {
		t.Errorf("quota API hits = %d, want 1", got)
	}
	if got := atomic.LoadInt32(stsHits); got != 0 {
		t.Errorf("STS hits = %d, want 0 — desktop helper exchanged credentials despite quota block", got)
	}
	assertNoSavedCredentials(t, profile)
}

// TestRunDesktopHelper_QuotaAllowedEmitsToken proves the desktop happy path
// still works with quota enforcement in place: allowed → STS exchange → a
// Bedrock bearer token is emitted.
func TestRunDesktopHelper_QuotaAllowedEmitsToken(t *testing.T) {
	setupNotificationTest(t)
	stsSrv, stsHits := stsRecorder(t)
	quotaSrv, _ := quotaRecorder(t, true)
	newQuotaOrderEnv(t, stsSrv.URL)
	t.Setenv("CLAUDE_HELPER_CONTEXT", "silent")

	profile := "test-desktop-quota-allowed"
	t.Cleanup(func() { storage.ClearRefreshToken(profile) })

	freshIDToken := fakeJWT(t, map[string]interface{}{
		"sub": "user-123", "email": "test@example.com",
		"exp": float64(time.Now().Unix() + 3600),
	})
	idpSrv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		fmt.Fprintf(w, `{"id_token": %q, "token_type": "Bearer"}`, freshIDToken)
	}))
	defer idpSrv.Close()

	if err := storage.SaveRefreshToken(profile, "session", "rt_original"); err != nil {
		t.Fatalf("SaveRefreshToken: %v", err)
	}

	cfg := directSTSConfig(quotaSrv.URL, freeLocalPort(t))
	cfg.OIDCTokenEndpoint = idpSrv.URL
	app := &credentialApp{profile: profile, cfg: cfg, providerType: "generic", redirectPort: cfg.RedirectPort}

	res := captureMCPStdout(t, app.runDesktopHelper)
	if res.code != 0 {
		t.Fatalf("runDesktopHelper() = %d, want 0 (quota allowed)", res.code)
	}
	if got := atomic.LoadInt32(stsHits); got != 1 {
		t.Errorf("STS hits = %d, want 1", got)
	}
	if !strings.Contains(res.stdout, `"token"`) {
		t.Errorf("runDesktopHelper() stdout missing bearer token JSON: %q", res.stdout)
	}
}

// TestPerformQuotaRecheck_ShortLivedTokenStillChecked pins the cache-hit
// variant of the silent-skip fix: after a successful refresh_token exchange,
// performQuotaRecheck must use the in-scope fresh id_token. The pre-fix code
// re-read it from storage, where an id_token expiring inside the 10-minute
// buffer reads back empty — so the recheck failed open and the blocked user
// kept their cached credentials.
func TestPerformQuotaRecheck_ShortLivedTokenStillChecked(t *testing.T) {
	setupNotificationTest(t)
	stsSrv, _ := stsRecorder(t)
	quotaSrv, quotaHits := quotaRecorder(t, false)
	newQuotaOrderEnv(t, stsSrv.URL)

	profile := "test-recheck-shortlived"
	t.Cleanup(func() { storage.ClearRefreshToken(profile) })

	// exp within the 600s buffer → storage.GetMonitoringToken returns ""
	shortLivedToken := fakeJWT(t, map[string]interface{}{
		"sub": "user-123", "email": "test@example.com",
		"exp": float64(time.Now().Unix() + 300),
	})
	idpSrv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		fmt.Fprintf(w, `{"id_token": %q, "token_type": "Bearer"}`, shortLivedToken)
	}))
	defer idpSrv.Close()

	if err := storage.SaveRefreshToken(profile, "session", "rt_original"); err != nil {
		t.Fatalf("SaveRefreshToken: %v", err)
	}
	// Seed cached credentials that the block must wipe.
	seeded := &federation.AWSCredentials{
		Version: 1, AccessKeyID: "ASIASEEDED", SecretAccessKey: "seed",
		SessionToken: "seed", Expiration: time.Now().Add(time.Hour).Format(time.RFC3339),
	}
	if err := storage.SaveToCredentialsFile(seeded, profile); err != nil {
		t.Fatalf("SaveToCredentialsFile: %v", err)
	}

	cfg := directSTSConfig(quotaSrv.URL, freeLocalPort(t))
	cfg.OIDCTokenEndpoint = idpSrv.URL
	app := &credentialApp{profile: profile, cfg: cfg, providerType: "generic", redirectPort: cfg.RedirectPort}

	if allowed := app.performQuotaRecheck(); allowed {
		t.Fatalf("performQuotaRecheck = true with a blocking quota response — short-lived id_token silently skipped the check")
	}
	if got := atomic.LoadInt32(quotaHits); got != 1 {
		t.Errorf("quota API hits = %d, want 1", got)
	}
	if creds, err := storage.ReadFromCredentialsFile(profile); err == nil && creds != nil && !storage.IsExpiredDummy(creds) {
		t.Errorf("cached credentials survived a quota block: AccessKeyId=%s", creds.AccessKeyID)
	}
}
