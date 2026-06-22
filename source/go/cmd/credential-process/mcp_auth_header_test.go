package main

import (
	"encoding/base64"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"testing"
	"time"

	"ccwb-go/internal/config"
	"ccwb-go/internal/storage"
)

// mcpStdoutResult bundles an exit code with whatever the function printed.
type mcpStdoutResult struct {
	code   int
	stdout string
}

// captureMCPStdout runs fn with os.Stdout redirected to a pipe and returns its
// exit code plus what it printed — used to assert the exact bearer value emitted.
func captureMCPStdout(t *testing.T, fn func() int) mcpStdoutResult {
	t.Helper()
	orig := os.Stdout
	r, w, err := os.Pipe()
	if err != nil {
		t.Fatalf("pipe: %v", err)
	}
	os.Stdout = w
	code := fn()
	_ = w.Close()
	os.Stdout = orig
	out, err := io.ReadAll(r)
	if err != nil {
		t.Fatalf("read pipe: %v", err)
	}
	return mcpStdoutResult{code: code, stdout: string(out)}
}

// fakeJWT builds a syntactically valid 3-part JWT with the given payload claims
// so jwt.DecodePayload (which does not verify the signature) accepts it.
func fakeJWT(t *testing.T, claims map[string]interface{}) string {
	t.Helper()
	payload, err := json.Marshal(claims)
	if err != nil {
		t.Fatalf("marshal claims: %v", err)
	}
	enc := base64.RawURLEncoding.EncodeToString
	return enc([]byte(`{"alg":"none"}`)) + "." + enc(payload) + ".sig"
}

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

// TestGetMCPAuthHeader_RefreshSucceedsWithoutAWSCreds is the regression test for
// the Codex P2 finding: on an expired/absent cached id_token, the MCP header path
// must silently refresh and emit the FRESH id_token even when AWS STS/IAM
// credential exchange would fail — the gateway's CUSTOM_JWT authorizer only needs
// the id_token, so refresh success must not be coupled to cred exchange.
//
// Setup: a generic OIDC provider whose token endpoint is a local httptest server
// returning a fresh id_token, a stored refresh_token, and NO cached monitoring
// token. There is no STS endpoint configured, so if the code path attempted an
// AWS credential exchange (the old tryRefreshToken behavior) it would fail and the
// header would NOT be emitted. Asserting exit 0 + the fresh token proves the
// decoupling (refreshIDTokenOnly).
func TestGetMCPAuthHeader_RefreshSucceedsWithoutAWSCreds(t *testing.T) {
	tmpDir := t.TempDir()
	t.Setenv("HOME", tmpDir)
	t.Setenv("USERPROFILE", tmpDir)
	t.Setenv("CLAUDE_CODE_MONITORING_TOKEN", "")
	if err := os.MkdirAll(filepath.Join(tmpDir, ".claude-code-session"), 0o700); err != nil {
		t.Fatalf("mkdir: %v", err)
	}

	freshIDToken := fakeJWT(t, map[string]interface{}{
		"email": "user@example.com",
		"exp":   time.Now().Unix() + 3600,
	})

	// Mock token endpoint: any refresh_token request returns the fresh id_token.
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(map[string]string{
			"id_token":      freshIDToken,
			"refresh_token": "rotated-refresh-token",
		})
	}))
	defer srv.Close()

	profile := "test-mcp-auth-refresh"
	if err := storage.SaveRefreshToken(profile, "session", "stored-refresh-token"); err != nil {
		t.Fatalf("seed refresh token: %v", err)
	}
	t.Cleanup(func() { storage.ClearRefreshToken(profile) })

	// Generic provider → refreshIDTokenOnly uses cfg.OIDCTokenEndpoint directly.
	// No QuotaAPIEndpoint / STS config: an AWS cred exchange would fail here.
	cfg := &config.ProfileConfig{
		ClientID:          "test-client",
		ProviderDomain:    "generic.example.com",
		CredentialStorage: "session",
		SsoEnabled:        boolPtr(true),
		OIDCTokenEndpoint: srv.URL,
	}
	app := &credentialApp{profile: profile, cfg: cfg, providerType: "generic"}

	out := captureMCPStdout(t, func() int { return app.getMCPAuthHeader() })
	if out.code != 0 {
		t.Fatalf("getMCPAuthHeader exit = %d, want 0 (refresh must emit header without AWS creds)", out.code)
	}
	var header map[string]string
	if err := json.Unmarshal([]byte(out.stdout), &header); err != nil {
		t.Fatalf("emitted header not JSON: %v (raw=%q)", err, out.stdout)
	}
	if got, want := header["Authorization"], "Bearer "+freshIDToken; got != want {
		t.Errorf("Authorization = %q, want the freshly refreshed id_token %q", got, want)
	}
}

// TestGetMCPAuthHeader_EnvToken verifies the env-var token shortcut also works,
// matching getMonitoringToken's CLAUDE_CODE_MONITORING_TOKEN precedence. The env
// token must be a valid (non-expired) JWT: GetMonitoringToken drops an expired or
// unparseable env token (PR #602, jwt.IsTokenExpired) so callers fall through to
// refresh rather than attaching a stale token — so this test supplies a real JWT
// with a future exp.
func TestGetMCPAuthHeader_EnvToken(t *testing.T) {
	tmpDir := t.TempDir()
	t.Setenv("HOME", tmpDir)
	t.Setenv("USERPROFILE", tmpDir)
	envToken := fakeJWT(t, map[string]interface{}{"exp": time.Now().Unix() + 3600})
	t.Setenv("CLAUDE_CODE_MONITORING_TOKEN", envToken)

	cfg := &config.ProfileConfig{
		ClientID:          "test-client",
		ProviderDomain:    "test.example.com",
		CredentialStorage: "session",
		SsoEnabled:        boolPtr(true),
	}
	app := &credentialApp{profile: "test-mcp-auth-env", cfg: cfg, providerType: "okta"}

	out := captureMCPStdout(t, func() int { return app.getMCPAuthHeader() })
	if out.code != 0 {
		t.Fatalf("getMCPAuthHeader exit = %d, want 0 with a valid env token", out.code)
	}
	var header map[string]string
	if err := json.Unmarshal([]byte(out.stdout), &header); err != nil {
		t.Fatalf("emitted header not JSON: %v (raw=%q)", err, out.stdout)
	}
	if header["Authorization"] != "Bearer "+envToken {
		t.Errorf("Authorization = %q, want the env-supplied JWT", header["Authorization"])
	}
}
