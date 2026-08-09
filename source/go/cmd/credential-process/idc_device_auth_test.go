package main

import (
	"context"
	"errors"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
	"time"

	"github.com/aws/aws-sdk-go-v2/credentials/ssocreds"
	"github.com/aws/aws-sdk-go-v2/service/ssooidc"

	"ccwb-go/internal/config"
	"ccwb-go/internal/portlock"
)

// TestRunDeviceAuthorizationFailsFastWhenHeadlessAndNoTTY is the regression
// test for the silent-hang fix. When stderr is not a terminal (the Claude Code
// credential-hook case), there is no way to surface the verification URL to a
// user who can act on it, so runDeviceAuthorization must return immediately with
// actionable instructions instead of blocking on a poll that can never succeed.
// Under `go test`, stderr is a pipe (not a char device), so stderrIsTerminal()
// is false. We set SSH_CONNECTION here to represent the SSH case; the no-SSH
// case is covered separately below.
//
// The guard runs before any network call, so a nil OIDC client is never
// dereferenced — if the guard regresses, the test fails fast on the nil client
// rather than hanging, which still surfaces the regression.
func TestRunDeviceAuthorizationFailsFastWhenHeadlessAndNoTTY(t *testing.T) {
	for _, e := range []string{"BROWSER", "SSH_TTY", "SSH_CLIENT", "DISPLAY", "WAYLAND_DISPLAY"} {
		t.Setenv(e, "")
	}
	t.Setenv("SSH_CONNECTION", "10.0.0.1 22 10.0.0.2 51000")

	app := &credentialApp{profile: "idc-test"}
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()

	// loginMode=false: the silent credential-export path must always fail fast
	// when stderr is captured, regardless of headless detection.
	err := app.runDeviceAuthorization(ctx, nil, "https://d-1234567890.awsapps.com/start", filepath.Join(t.TempDir(), "tok.json"), false)
	if err == nil {
		t.Fatal("expected fail-fast error when headless without a TTY, got nil")
	}
	msg := err.Error()
	// Plain-language message: explains the reason (expired session, needs a
	// browser), names the claude-bedrock launcher, tells the user to exit Claude
	// Code, and avoids AWS jargon.
	for _, want := range []string{"claude-bedrock", "Exit Claude Code", "expired", "browser"} {
		if !strings.Contains(msg, want) {
			t.Errorf("fail-fast error missing %q; got: %s", want, msg)
		}
	}
	// Should offer ONLY the launcher — not the raw --login command, which
	// refreshes the cache but does not reliably unstick an already-failed
	// session (misleading at this point) — and no AWS jargon.
	for _, unwanted := range []string{"--login", "IAM Identity Center", "non-interactively"} {
		if strings.Contains(msg, unwanted) {
			t.Errorf("fail-fast error should not contain %q; got: %s", unwanted, msg)
		}
	}
}

// TestRunDeviceAuthorizationFailsFastNoTTYWithoutSSH covers the headless-Windows
// gap: a non-SSH host (no SSH_* env) where Claude Code captures stderr. Here
// isHeadless() would return false on Windows/macOS (it assumes a desktop
// browser), so gating the fail-fast on isHeadless() previously let this case
// reach the blocking device-auth poll and hang. With the fix the gate is
// stderrIsTerminal() alone, so it must STILL fail fast with no SSH env set.
// (A nil OIDC client guarantees we never reach the network/poll.)
func TestRunDeviceAuthorizationFailsFastNoTTYWithoutSSH(t *testing.T) {
	// Clear every signal isHeadless() inspects so this is the "looks like a
	// desktop" case — yet stderr is still a pipe under `go test`.
	for _, e := range []string{"BROWSER", "SSH_CONNECTION", "SSH_TTY", "SSH_CLIENT", "DISPLAY", "WAYLAND_DISPLAY"} {
		t.Setenv(e, "")
	}

	app := &credentialApp{profile: "idc-test"}
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()

	err := app.runDeviceAuthorization(ctx, nil, "https://d-1234567890.awsapps.com/start", filepath.Join(t.TempDir(), "tok.json"), false)
	if err == nil {
		t.Fatal("expected fail-fast error when stderr is not a TTY (no SSH), got nil")
	}
	if !strings.Contains(err.Error(), "claude-bedrock") {
		t.Errorf("expected launcher in fail-fast message; got: %s", err.Error())
	}
}

// TestRunDeviceAuthorizationHeadlessLoginProceedsPastGate is the regression test
// for the headless mid-session recovery path. In loginMode (--login /
// awsAuthRefresh), Claude Code streams our stderr live, so a headless/SSH user
// sees the verification URL + code and opens it on another device. The gate must
// therefore NOT fail fast here — it must proceed into device authorization.
//
// We prove "got past the gate" without real network: a nil OIDC client makes the
// first call after the gate (RegisterClient) panic with a nil dereference, which
// we recover and treat as success. If the gate regressed to fail-fast, we'd get a
// returned error (with the launcher message) and no panic instead.
func TestRunDeviceAuthorizationHeadlessLoginProceedsPastGate(t *testing.T) {
	for _, e := range []string{"BROWSER", "SSH_TTY", "SSH_CLIENT", "DISPLAY", "WAYLAND_DISPLAY"} {
		t.Setenv(e, "")
	}
	t.Setenv("SSH_CONNECTION", "10.0.0.1 22 10.0.0.2 51000") // headless

	app := &credentialApp{profile: "idc-test"}
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()

	defer func() {
		if r := recover(); r == nil {
			t.Fatal("expected to proceed past the gate into device auth (nil-client panic); " +
				"got no panic — gate likely failed fast on headless login")
		}
	}()

	err := app.runDeviceAuthorization(ctx, nil, "https://d-1234567890.awsapps.com/start", filepath.Join(t.TempDir(), "tok.json"), true)
	// Reaching here (no panic) means the gate returned an error instead of
	// proceeding — that's the regression we're guarding against.
	t.Fatalf("expected gate to proceed into device auth, but it returned: %v", err)
}

// TestCanSurfaceVerificationURL covers the gate that decides whether
// runDeviceAuthorization may run the blocking poll or must fail fast. Under
// `go test`, stderr is a pipe, so stderrIsTerminal() is false throughout —
// which lets us isolate the loginMode + headless contribution. The only case
// that may proceed is loginMode on a non-headless (browser-available) host.
func TestCanSurfaceVerificationURL(t *testing.T) {
	t.Run("silent_path_headless_cannot_surface", func(t *testing.T) {
		for _, e := range []string{"BROWSER", "SSH_TTY", "SSH_CLIENT", "DISPLAY", "WAYLAND_DISPLAY"} {
			t.Setenv(e, "")
		}
		t.Setenv("SSH_CONNECTION", "10.0.0.1 22 10.0.0.2 51000")
		if canSurfaceVerificationURL(false) {
			t.Error("silent path on headless host must not be allowed to poll")
		}
	})

	t.Run("login_headless_may_surface_via_streamed_stderr", func(t *testing.T) {
		// Headless/SSH in the --login (awsAuthRefresh) slot: Claude Code streams
		// our stderr live, so the URL + code reach the user on another device even
		// with no local browser. The poll is allowed; the user opens the link.
		for _, e := range []string{"BROWSER", "SSH_TTY", "SSH_CLIENT", "DISPLAY", "WAYLAND_DISPLAY"} {
			t.Setenv(e, "")
		}
		t.Setenv("SSH_CONNECTION", "10.0.0.1 22 10.0.0.2 51000")
		if !canSurfaceVerificationURL(true) {
			t.Error("login on headless host must be allowed to poll (stderr is streamed live)")
		}
	})

	t.Run("login_with_browser_may_surface", func(t *testing.T) {
		// $BROWSER forces isHeadless()=false on any OS, so loginMode qualifies even
		// though stderr is a pipe under `go test`. This is the desktop mid-session
		// recovery path: pop the browser, poll, exit 0.
		for _, e := range []string{"SSH_CONNECTION", "SSH_TTY", "SSH_CLIENT", "DISPLAY", "WAYLAND_DISPLAY"} {
			t.Setenv(e, "")
		}
		t.Setenv("BROWSER", "/usr/bin/firefox")
		if !canSurfaceVerificationURL(true) {
			t.Error("login with an available browser must be allowed to poll")
		}
	})

	t.Run("silent_with_browser_cannot_surface", func(t *testing.T) {
		// Even with a browser, the SILENT path (awsCredentialExport) must never
		// poll — its stderr is discarded and it must never hang.
		for _, e := range []string{"SSH_CONNECTION", "SSH_TTY", "SSH_CLIENT", "DISPLAY", "WAYLAND_DISPLAY"} {
			t.Setenv(e, "")
		}
		t.Setenv("BROWSER", "/usr/bin/firefox")
		if canSurfaceVerificationURL(false) {
			t.Error("silent path must never poll, even with a browser available")
		}
	})
}

// TestPollForTokenTimeoutIsDeadlineExceeded pins the contract the timeout UX
// depends on: when the context expires before approval, pollForToken must return
// an error that errors.Is(context.DeadlineExceeded) matches. runIDCLogin keys the
// friendly "Sign-in timed out — send another message to retry" message off that
// check, so if the wrapping ever drops %w the user would fall back to the raw
// jargon error. An already-cancelled context makes the poll's select hit
// ctx.Done() before any CreateToken call, so the nil client is never touched.
func TestPollForTokenTimeoutIsDeadlineExceeded(t *testing.T) {
	ctx, cancel := context.WithTimeout(context.Background(), time.Nanosecond)
	defer cancel()
	time.Sleep(time.Millisecond) // ensure the deadline has passed

	reg := &ssooidc.RegisterClientOutput{}
	devAuth := &ssooidc.StartDeviceAuthorizationOutput{Interval: 5}

	_, err := pollForToken(ctx, nil, reg, devAuth)
	if err == nil {
		t.Fatal("expected timeout error from expired context, got nil")
	}
	if !errors.Is(err, context.DeadlineExceeded) {
		t.Errorf("timeout error must wrap context.DeadlineExceeded for the friendly "+
			"retry message to trigger; got: %v", err)
	}
}

// TestIsHeadless verifies the SSH/headless detection that decides whether the
// device-auth flow tries to open a local browser or shows a copy-to-another-
// device prompt. Getting this wrong on a remote host means the binary launches
// a browser the user can never see, then times out waiting for approval.
func TestIsHeadless(t *testing.T) {
	// Clear every signal isHeadless inspects so each case starts from a known
	// state regardless of the real test environment (which may itself be SSH).
	for _, e := range []string{"BROWSER", "SSH_CONNECTION", "SSH_TTY", "SSH_CLIENT", "DISPLAY", "WAYLAND_DISPLAY"} {
		t.Setenv(e, "")
	}

	t.Run("ssh_session_is_headless_on_any_os", func(t *testing.T) {
		t.Setenv("SSH_CONNECTION", "10.0.0.1 22 10.0.0.2 51000")
		if !isHeadless() {
			t.Error("SSH session must be treated as headless")
		}
	})

	t.Run("browser_override_forces_not_headless", func(t *testing.T) {
		// Even inside an SSH session, an explicit $BROWSER means the user told us
		// how to open a browser — honor it.
		t.Setenv("SSH_CONNECTION", "10.0.0.1 22 10.0.0.2 51000")
		t.Setenv("BROWSER", "/usr/bin/firefox")
		if isHeadless() {
			t.Error("explicit $BROWSER must force non-headless")
		}
	})

	t.Run("linux_no_display_is_headless", func(t *testing.T) {
		if runtime.GOOS != "linux" {
			t.Skip("DISPLAY heuristic only applies to Linux/BSD")
		}
		// No SSH, no DISPLAY, no WAYLAND_DISPLAY → no GUI session.
		if !isHeadless() {
			t.Error("Linux with no DISPLAY/WAYLAND_DISPLAY must be headless")
		}
	})

	t.Run("linux_with_display_is_not_headless", func(t *testing.T) {
		if runtime.GOOS != "linux" {
			t.Skip("DISPLAY heuristic only applies to Linux/BSD")
		}
		t.Setenv("DISPLAY", ":0")
		if isHeadless() {
			t.Error("Linux with DISPLAY set must not be headless")
		}
	})

	t.Run("desktop_os_not_headless_without_ssh", func(t *testing.T) {
		if runtime.GOOS != "windows" && runtime.GOOS != "darwin" {
			t.Skip("desktop-OS assumption only applies to Windows/macOS")
		}
		// No SSH and a desktop OS → assume a local browser exists.
		if isHeadless() {
			t.Errorf("%s without SSH must not be headless", runtime.GOOS)
		}
	})
}

// TestTokenValid covers the gate that decides whether we can reuse a cached SSO
// token or must run a fresh device-authorization flow. A wrong answer here
// either re-prompts the user needlessly (false negative) or hands back an
// about-to-expire token mid-request (false positive).
func TestTokenValid(t *testing.T) {
	dir := t.TempDir()

	write := func(name, contents string) string {
		p := filepath.Join(dir, name)
		if err := os.WriteFile(p, []byte(contents), 0o600); err != nil {
			t.Fatalf("write %s: %v", name, err)
		}
		return p
	}

	future := time.Now().Add(2 * time.Hour).UTC().Format(time.RFC3339)
	past := time.Now().Add(-1 * time.Hour).UTC().Format(time.RFC3339)
	soon := time.Now().Add(30 * time.Second).UTC().Format(time.RFC3339) // inside 60s safety margin

	cases := []struct {
		name string
		path string
		want bool
	}{
		{"missing_file", filepath.Join(dir, "does-not-exist.json"), false},
		{"valid_unexpired", write("valid.json", `{"accessToken":"tok","expiresAt":"`+future+`"}`), true},
		{"expired", write("expired.json", `{"accessToken":"tok","expiresAt":"`+past+`"}`), false},
		{"within_safety_margin", write("soon.json", `{"accessToken":"tok","expiresAt":"`+soon+`"}`), false},
		{"empty_access_token", write("noaccess.json", `{"accessToken":"","expiresAt":"`+future+`"}`), false},
		{"missing_expiry", write("noexp.json", `{"accessToken":"tok"}`), false},
		{"malformed_json", write("bad.json", `{not json`), false},
		{"bad_timestamp", write("badts.json", `{"accessToken":"tok","expiresAt":"not-a-date"}`), false},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			if got := tokenValid(tc.path); got != tc.want {
				t.Errorf("tokenValid(%s) = %v, want %v", tc.name, got, tc.want)
			}
		})
	}
}

// TestWriteSSOTokenCacheReadableBySDK is the core regression test for the IDC
// device-auth fix. The device-authorization flow writes the SSO token to
// ~/.aws/sso/cache/ in the SDK's on-disk format; ssocreds.SSOTokenProvider must
// be able to read it back. If the JSON field names or the RFC3339 expiresAt
// format drift from what the SDK expects, IDC auth breaks with the same
// "failed to read cached SSO token file" error this fix was meant to eliminate.
//
// We assert the round-trip against the REAL SDK reader (ssocreds.SSOTokenProvider,
// the exact type runIDC wires up), not a reimplementation, so the test fails if
// the SDK's on-disk format changes too. For an unexpired token the provider
// reads straight from the cache file and never touches its client, so a nil
// client is safe here.
func TestWriteSSOTokenCacheReadableBySDK(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "sso", "cache", "token.json")

	expiresAt := time.Now().Add(8 * time.Hour)
	token := ssoCachedToken{
		AccessToken:  "access-token-value",
		ExpiresAt:    expiresAt.UTC().Format(time.RFC3339),
		RefreshToken: "refresh-token-value",
		ClientID:     "client-id",
		ClientSecret: "client-secret",
		StartURL:     "https://d-1234567890.awsapps.com/start",
	}

	if err := writeSSOTokenCache(path, token); err != nil {
		t.Fatalf("writeSSOTokenCache: %v", err)
	}

	// Cache file must be created with the parent directories.
	if _, err := os.Stat(path); err != nil {
		t.Fatalf("expected cache file at %s: %v", path, err)
	}

	// The SDK's SSOTokenProvider must be able to read what we wrote. nil client
	// is fine: the token is unexpired so no CreateToken refresh call is made.
	provider := ssocreds.NewSSOTokenProvider(nil, path)
	bt, err := provider.RetrieveBearerToken(context.Background())
	if err != nil {
		t.Fatalf("SDK SSOTokenProvider failed to read our cache: %v", err)
	}
	if bt.Value != token.AccessToken {
		t.Errorf("accessToken round-trip mismatch: got %q want %q", bt.Value, token.AccessToken)
	}
	if !bt.CanExpire || bt.Expires.IsZero() {
		t.Errorf("expiresAt did not round-trip: CanExpire=%v Expires=%v", bt.CanExpire, bt.Expires)
	}
}

// TestWriteSSOTokenCachePermissions verifies the cached bearer token is written
// with user-only (0600) permissions — it grants AWS access and must not be
// world-readable. (No-op semantics on Windows, but enforced on POSIX where the
// EC2/Linux installs run.)
func TestWriteSSOTokenCachePermissions(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "cache", "token.json")
	if err := writeSSOTokenCache(path, ssoCachedToken{AccessToken: "x", ExpiresAt: time.Now().UTC().Format(time.RFC3339)}); err != nil {
		t.Fatalf("writeSSOTokenCache: %v", err)
	}
	info, err := os.Stat(path)
	if err != nil {
		t.Fatalf("stat: %v", err)
	}
	if perm := info.Mode().Perm(); perm != 0o600 && perm != 0o666 /* Windows */ {
		t.Errorf("cache file perms = %o, want 0600", perm)
	}
}

// TestTokenRefreshable covers the gate that distinguishes "expired but the SDK
// can silently refresh via refresh_token" from "no session at all". A false
// negative here forces a premature interactive sign-in the moment the ~1h SSO
// access token expires (the observed 403 -> "sign-in required" regression),
// instead of letting the SDK exchange the refresh token with no browser.
func TestTokenRefreshable(t *testing.T) {
	dir := t.TempDir()
	write := func(name, contents string) string {
		p := filepath.Join(dir, name)
		if err := os.WriteFile(p, []byte(contents), 0o600); err != nil {
			t.Fatal(err)
		}
		return p
	}

	cases := []struct {
		name string
		path string
		want bool
	}{
		{"missing_file", filepath.Join(dir, "nope.json"), false},
		{"full_refresh_material", write("ok.json",
			`{"accessToken":"a","expiresAt":"2020-01-01T00:00:00Z","refreshToken":"r","clientId":"c","clientSecret":"s"}`), true},
		{"no_refresh_token", write("nort.json",
			`{"accessToken":"a","clientId":"c","clientSecret":"s"}`), false},
		{"no_client_id", write("nocid.json",
			`{"refreshToken":"r","clientSecret":"s"}`), false},
		{"no_client_secret", write("nocs.json",
			`{"refreshToken":"r","clientId":"c"}`), false},
		{"malformed", write("bad.json", `{nope`), false},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			if got := tokenRefreshable(tc.path); got != tc.want {
				t.Errorf("tokenRefreshable(%s) = %v, want %v", tc.name, got, tc.want)
			}
		})
	}
}

// TestEnsureIDCToken_RefreshableDoesNotDeviceAuth is the regression test for the
// 1-hour expiry bug. With an EXPIRED access token that still has refresh
// material, ensureIDCToken must take the silent-refresh path, NOT interactive
// device authorization.
//
// We isolate "did not device-auth" from "the refresh network call": another
// goroutine holds the refresh lock and writes a VALID token, so ensureIDCToken
// waits, sees the refreshed token, and returns without ever invoking the (nil)
// oidc client. A nil client guarantees the assertion — if the logic regressed
// to device auth or an unlocked refresh, it would dereference nil and panic.
func TestEnsureIDCToken_RefreshableDoesNotDeviceAuth(t *testing.T) {
	dir := t.TempDir()
	tokenPath := filepath.Join(dir, "tok.json")
	expired := `{"accessToken":"a","expiresAt":"2020-01-01T00:00:00Z","refreshToken":"r","clientId":"c","clientSecret":"s"}`
	if err := os.WriteFile(tokenPath, []byte(expired), 0o600); err != nil {
		t.Fatal(err)
	}

	ln, err := portlock.TryAcquire(idcRefreshLockPort)
	if err != nil || ln == nil {
		t.Skipf("could not acquire refresh lock port %d; skipping", idcRefreshLockPort)
	}
	future := time.Now().Add(1 * time.Hour).UTC().Format(time.RFC3339)
	refreshed := `{"accessToken":"new","expiresAt":"` + future + `","refreshToken":"r2","clientId":"c","clientSecret":"s"}`
	go func() {
		time.Sleep(300 * time.Millisecond)
		_ = os.WriteFile(tokenPath, []byte(refreshed), 0o600)
		ln.Close()
	}()

	app := &credentialApp{profile: "idc-test"}
	if err := app.ensureIDCToken(context.Background(), nil, "https://d-1.awsapps.com/start", tokenPath); err != nil {
		t.Fatalf("expected nil (silent refresh via concurrent winner), got %v", err)
	}
}

// TestRefreshIDCTokenLocked_WaitsForConcurrentRefresh is the regression test for
// the rotating-refresh-token race. When another process already holds the
// refresh lock and leaves behind a valid (refreshed) token, refreshIDCTokenLocked
// must wait, observe the valid token, and return WITHOUT attempting its own
// refresh — otherwise it would redeem the already-consumed refresh token and get
// InvalidGrantException. We prove "no refresh attempt" by passing a nil oidc
// client: if the lock logic regressed and tried to refresh, doIDCRefresh would
// dereference nil and panic.
func TestRefreshIDCTokenLocked_WaitsForConcurrentRefresh(t *testing.T) {
	dir := t.TempDir()
	tokenPath := filepath.Join(dir, "tok.json")
	// Start with an EXPIRED-but-refreshable token (what a racing caller sees).
	expired := `{"accessToken":"old","expiresAt":"2020-01-01T00:00:00Z","refreshToken":"r","clientId":"c","clientSecret":"s"}`
	if err := os.WriteFile(tokenPath, []byte(expired), 0o600); err != nil {
		t.Fatal(err)
	}

	// Simulate the "winner" holding the refresh lock, then completing: it writes
	// a VALID token and releases the lock shortly after.
	ln, err := portlock.TryAcquire(idcRefreshLockPort)
	if err != nil || ln == nil {
		t.Skipf("could not acquire refresh lock port %d (in use); skipping", idcRefreshLockPort)
	}
	future := time.Now().Add(1 * time.Hour).UTC().Format(time.RFC3339)
	refreshed := `{"accessToken":"new","expiresAt":"` + future + `","refreshToken":"r2","clientId":"c","clientSecret":"s"}`
	go func() {
		time.Sleep(300 * time.Millisecond)
		_ = os.WriteFile(tokenPath, []byte(refreshed), 0o600)
		ln.Close() // release the lock
	}()

	app := &credentialApp{profile: "idc-test"}
	// nil oidc client: must NOT be used, because the token becomes valid via the
	// concurrent "winner" and this caller should just read it.
	if err := app.refreshIDCTokenLocked(context.Background(), nil, tokenPath); err != nil {
		t.Fatalf("expected nil after concurrent refresh, got %v", err)
	}
}

// runIDCLoginCapturingStderr runs runIDCLogin with the given config wired into a
// credentialApp, capturing os.Stderr so the test can assert on the user-facing
// message. It points the SSO cache at tokenPath by pre-seeding HOME so
// StandardCachedTokenFilepath resolves there.
func runIDCLoginWithProfile(t *testing.T, cfg *config.ProfileConfig) (int, string) {
	t.Helper()
	r, w, _ := os.Pipe()
	old := os.Stderr
	os.Stderr = w
	app := &credentialApp{profile: "idc-test", cfg: cfg}
	code := app.runIDCLogin()
	w.Close()
	os.Stderr = old
	var buf [4096]byte
	n, _ := r.Read(buf[:])
	return code, string(buf[:n])
}

// TestRunIDCLogin_ValidToken_ReportsSignedIn: a still-valid access token short-
// circuits to "already signed in" with no refresh or device auth (nil oidc
// client never touched).
func TestRunIDCLogin_ValidToken_ReportsSignedIn(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	// Neutralize ambient AWS config so LoadDefaultConfig doesn't try to load a
	// named shared-config profile (e.g. a developer's AWS_PROFILE) that won't
	// exist under the temp HOME.
	t.Setenv("AWS_PROFILE", "")
	t.Setenv("AWS_REGION", "us-east-1")
	t.Setenv("AWS_CONFIG_FILE", filepath.Join(home, "noexist-config"))
	t.Setenv("AWS_SHARED_CREDENTIALS_FILE", filepath.Join(home, "noexist-creds"))
	startURL := "https://d-1234567890.awsapps.com/start"

	tokenPath, err := ssocreds.StandardCachedTokenFilepath(startURL)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.MkdirAll(filepath.Dir(tokenPath), 0o700); err != nil {
		t.Fatal(err)
	}
	future := time.Now().Add(2 * time.Hour).UTC().Format(time.RFC3339)
	valid := `{"accessToken":"a","expiresAt":"` + future + `","refreshToken":"r","clientId":"c","clientSecret":"s"}`
	if err := os.WriteFile(tokenPath, []byte(valid), 0o600); err != nil {
		t.Fatal(err)
	}

	cfg := &config.ProfileConfig{
		AuthType:             "idc",
		IDCStartURL:          startURL,
		IDCAccountID:         "123456789012",
		IDCPermissionSetName: "Role",
		IDCRegion:            "us-east-1",
	}
	code, out := runIDCLoginWithProfile(t, cfg)
	if code != 0 {
		t.Fatalf("expected exit 0 for valid token, got %d (stderr: %s)", code, out)
	}
	if !strings.Contains(out, "Already signed in") {
		t.Errorf("expected 'Already signed in' message, got: %s", out)
	}
}

// TestRunIDCLogin_RefreshableViaConcurrentWinner_ReportsRefreshed is the
// regression test for the "Already signed in" bug: runIDCLogin must no longer
// short-circuit purely because refresh FIELDS exist. It now routes through
// refreshIDCTokenLocked; when a concurrent winner refreshes the token, this
// caller observes the now-valid token and reports "session refreshed" without
// device auth (nil oidc client proves no network/refresh call by this caller).
func TestRunIDCLogin_RefreshableViaConcurrentWinner_ReportsRefreshed(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	// Neutralize ambient AWS config so LoadDefaultConfig doesn't try to load a
	// named shared-config profile (e.g. a developer's AWS_PROFILE) that won't
	// exist under the temp HOME.
	t.Setenv("AWS_PROFILE", "")
	t.Setenv("AWS_REGION", "us-east-1")
	t.Setenv("AWS_CONFIG_FILE", filepath.Join(home, "noexist-config"))
	t.Setenv("AWS_SHARED_CREDENTIALS_FILE", filepath.Join(home, "noexist-creds"))
	startURL := "https://d-1234567890.awsapps.com/start"

	tokenPath, err := ssocreds.StandardCachedTokenFilepath(startURL)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.MkdirAll(filepath.Dir(tokenPath), 0o700); err != nil {
		t.Fatal(err)
	}
	expired := `{"accessToken":"old","expiresAt":"2020-01-01T00:00:00Z","refreshToken":"r","clientId":"c","clientSecret":"s"}`
	if err := os.WriteFile(tokenPath, []byte(expired), 0o600); err != nil {
		t.Fatal(err)
	}

	ln, err := portlock.TryAcquire(idcRefreshLockPort)
	if err != nil || ln == nil {
		t.Skipf("could not acquire refresh lock port %d; skipping", idcRefreshLockPort)
	}
	future := time.Now().Add(1 * time.Hour).UTC().Format(time.RFC3339)
	refreshed := `{"accessToken":"new","expiresAt":"` + future + `","refreshToken":"r2","clientId":"c","clientSecret":"s"}`
	go func() {
		time.Sleep(300 * time.Millisecond)
		_ = os.WriteFile(tokenPath, []byte(refreshed), 0o600)
		ln.Close()
	}()

	cfg := &config.ProfileConfig{
		AuthType:             "idc",
		IDCStartURL:          startURL,
		IDCAccountID:         "123456789012",
		IDCPermissionSetName: "Role",
		IDCRegion:            "us-east-1",
	}
	code, out := runIDCLoginWithProfile(t, cfg)
	if code != 0 {
		t.Fatalf("expected exit 0 after concurrent refresh, got %d (stderr: %s)", code, out)
	}
	if !strings.Contains(out, "refreshed") {
		t.Errorf("expected session-refreshed message, got: %s", out)
	}
}
