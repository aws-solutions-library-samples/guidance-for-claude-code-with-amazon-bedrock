package main

import (
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"strconv"
	"strings"
	"time"

	awsconfig "github.com/aws/aws-sdk-go-v2/config"
	"github.com/aws/aws-sdk-go-v2/service/sts"
	"golang.org/x/term"

	"ccwb-go/internal/config"
	"ccwb-go/internal/federation"
	"ccwb-go/internal/jwt"
	"ccwb-go/internal/oidc"
	"ccwb-go/internal/otel"
	"ccwb-go/internal/portlock"
	"ccwb-go/internal/provider"
	"ccwb-go/internal/quota"
	"ccwb-go/internal/storage"
	"ccwb-go/internal/version"
)

var debug bool

func debugPrint(format string, args ...interface{}) {
	if debug {
		fmt.Fprintf(os.Stderr, "Debug: "+format+"\n", args...)
	}
}

func main() {
	defaultProfile := os.Getenv("CCWB_PROFILE")
	if defaultProfile == "" {
		defaultProfile = "ClaudeCode"
	}

	profileFlag := flag.String("profile", defaultProfile, "Configuration profile to use")
	shortProfile := flag.String("p", "", "Configuration profile to use (short)")
	versionFlag := flag.Bool("version", false, "Show version")
	shortVersion := flag.Bool("v", false, "Show version (short)")
	getMonitoring := flag.Bool("get-monitoring-token", false, "Get cached monitoring token")
	getMCPAuthHeader := flag.Bool("get-mcp-auth-header", false, "Print {\"Authorization\":\"Bearer <id_token>\"} from the cached token for an MCP headersHelper (never opens a browser)")
	clearCache := flag.Bool("clear-cache", false, "Clear cached credentials")
	checkExpiration := flag.Bool("check-expiration", false, "Check if credentials are expired")
	refreshIfNeeded := flag.Bool("refresh-if-needed", false, "Refresh credentials if expired")
	showTags := flag.Bool("show-tags", false, "Print the https://aws.amazon.com/tags claim from the cached ID token (debug)")
	showClaims := flag.Bool("show-claims", false, "Print ALL claims from the ID token as JSON (diagnostic: shows exactly what the IdP is sending — groups, department, custom claims). Uses the cached token; signs in only when none is cached.")
	getTag := flag.String("get-tag", "", "Print the value of a single principal tag from the cached ID token (e.g. --get-tag Zone). Exit codes: 0 hit, 2 absent, 4 expired.")
	login := flag.Bool("login", false, "Interactively sign in (IDC: run device authorization and cache the SSO token), then exit. Use this once on headless/SSH hosts before Claude Code runs.")
	setClientSecret := flag.Bool("set-client-secret", false, "Store Azure AD client secret in OS secure storage. Set CCWB_CLIENT_SECRET env var for non-interactive use, or enter it at the prompt.")
	explain := flag.Bool("explain", false, "Print resolved configuration as JSON and exit (no auth, no network calls)")
	desktop := flag.Bool("desktop", false, "Output a Bedrock bearer token for Claude Desktop inferenceCredentialHelper (respects CLAUDE_HELPER_CONTEXT)")
	flag.Parse()

	if *versionFlag || *shortVersion {
		fmt.Printf("credential-process %s (%s)\n", version.Version, version.Commit)
		os.Exit(0)
	}

	profile := *profileFlag
	if *shortProfile != "" {
		profile = *shortProfile
	}
	if profile == defaultProfile {
		// Try auto-detect if using default
		if detected := config.AutoDetectProfile(); detected != "" {
			profile = detected
		}
	}

	// --set-client-secret runs before config load so it works on fresh machines
	// where config.json may not yet exist.
	if *setClientSecret {
		os.Exit(runSetClientSecret(profile))
	}

	debug = os.Getenv("COGNITO_AUTH_DEBUG") == "1" || os.Getenv("COGNITO_AUTH_DEBUG") == "true" || os.Getenv("COGNITO_AUTH_DEBUG") == "yes"

	cfg, err := config.LoadProfile(profile)
	if err != nil {
		fmt.Fprintf(os.Stderr, "Error: %v\n", err)
		os.Exit(1)
	}

	// Build a minimal app for flag dispatch (works for all auth types).
	app := &credentialApp{
		profile: profile,
		cfg:     cfg,
	}

	// --explain: print resolved config as JSON and exit (no auth, no network).
	if *explain {
		runExplain(profile, cfg)
	}

	// Resolve OIDC provider type + redirect port BEFORE the flag dispatch below.
	// The --get-monitoring-token and --get-mcp-auth-header handlers perform a
	// silent refresh_token exchange that depends on app.providerType (to build the
	// token endpoint URL and pick the Azure confidential-auth path) and, on
	// fall-through to browser auth, on app.redirectPort. Historically both fields
	// were set only after the dispatch block (in the OIDC run() path), so those
	// handlers ran with providerType=="" (empty token URL + no client assertion →
	// failed exchange that wiped the refresh_token) and redirectPort==0 (browser
	// fallback opened http://localhost:0 → ERR_UNSAFE_PORT).
	//
	// Gated to real OIDC profiles only: resolveProviderType calls provider.Detect,
	// which returns "oidc" (→ os.Exit(1)) for the empty provider_domain typical of
	// IDC/none profiles. IDC/none never use this OIDC refresh path, so skip them
	// here and let their own dispatch branches (IsIDC / !IsSsoEnabled) handle them.
	if cfg.IsSsoEnabled() && !cfg.IsIDC() {
		app.providerType = resolveProviderType(cfg)
		app.redirectPort = resolveRedirectPort(cfg)
	}

	// Flag dispatch — must run before auth-type branching so IDC users
	// can use --get-monitoring-token, --show-tags, etc.
	if *clearCache {
		app.clearCache()
		os.Exit(0)
	}
	if *showTags {
		os.Exit(app.showTags())
	}
	if *showClaims {
		os.Exit(app.showClaims())
	}
	if *getTag != "" {
		os.Exit(app.getTag(*getTag))
	}
	if *getMonitoring {
		os.Exit(app.getMonitoringToken())
	}
	if *getMCPAuthHeader {
		os.Exit(app.getMCPAuthHeader())
	}
	if *desktop {
		os.Exit(app.runDesktopHelper())
	}
	if *checkExpiration {
		os.Exit(app.checkExpiration())
	}
	if *login {
		// Interactive sign-in only (no credential JSON on stdout). For IDC this
		// runs device authorization and caches the SSO token so subsequent
		// non-interactive runs (e.g. Claude Code) reuse it silently — the
		// recommended first step on headless/SSH hosts.
		if cfg.IsIDC() {
			os.Exit(app.runIDCLogin())
		}
		fmt.Fprintln(os.Stderr, "--login is only supported for IAM Identity Center (auth_type=idc) profiles.")
		if cfg.IsSsoEnabled() {
			fmt.Fprintln(os.Stderr, "OIDC profiles authenticate automatically via the browser on first use; no separate login step is needed.")
		} else {
			fmt.Fprintln(os.Stderr, "This profile uses the ambient AWS credential chain; no sign-in step is needed.")
		}
		os.Exit(1)
	}

	// Auth dispatch: IDC > legacy passthrough > OIDC
	if cfg.IsIDC() {
		exitAfterNotifications(app.runIDC())
	}
	if !cfg.IsSsoEnabled() {
		// Legacy passthrough: no IDC fields, just ambient credential chain.
		exitAfterNotifications(app.runPassthrough())
	}

	// OIDC path — provider type + redirect port were already resolved above
	// (before the flag dispatch) for this OIDC profile; resolve defensively if
	// somehow unset.
	if app.providerType == "" {
		app.providerType = resolveProviderType(cfg)
	}
	if app.redirectPort == 0 {
		app.redirectPort = resolveRedirectPort(cfg)
	}

	if *refreshIfNeeded {
		if cfg.CredentialStorage != "session" {
			fmt.Fprintln(os.Stderr, "Error: --refresh-if-needed only works with session storage mode")
			os.Exit(1)
		}
		creds, err := storage.ReadFromCredentialsFile(profile)
		if err == nil && creds != nil && !storage.IsExpiredDummy(creds) {
			remaining := storage.ParseExpirationSeconds(creds.Expiration)
			if remaining > 30 {
				debugPrint("Credentials still valid for profile '%s', no refresh needed", profile)
				os.Exit(0)
			}
		}
		// Fall through to normal auth flow
	}

	exitAfterNotifications(app.run())
}

// exitAfterNotifications waits for any pending quota browser notification to be
// fetched (or time out) before terminating. Credentials are already written to
// stdout by the time run()/runIDC()/runPassthrough() return, so this only holds
// the process open long enough for the browser to connect — it never delays the
// AWS SDK. Without it, os.Exit kills the notification server goroutine before
// the browser connects (ERR_CONNECTION_REFUSED).
func exitAfterNotifications(code int) {
	waitForQuotaNotification()
	os.Exit(code)
}

type credentialApp struct {
	profile      string
	cfg          *config.ProfileConfig
	providerType string
	redirectPort int
}

// resolveRedirectPort returns the OAuth callback port for the browser flow:
// REDIRECT_PORT env override → profile RedirectPort → default 8400. Never returns
// 0 (which would open http://localhost:0 → ERR_UNSAFE_PORT).
func resolveRedirectPort(cfg *config.ProfileConfig) int {
	if envPort := os.Getenv("REDIRECT_PORT"); envPort != "" {
		if p, err := strconv.Atoi(envPort); err == nil && p > 0 {
			return p
		}
	}
	if cfg.RedirectPort > 0 {
		return cfg.RedirectPort
	}
	return 8400
}

func resolveProviderType(cfg *config.ProfileConfig) string {
	if provider.IsKnown(cfg.ProviderType) {
		return cfg.ProviderType
	}
	detected := provider.Detect(cfg.ProviderDomain)
	if detected == "oidc" {
		fmt.Fprintf(os.Stderr, "Error: Unable to auto-detect provider type for domain '%s'.\n", cfg.ProviderDomain)
		fmt.Fprintln(os.Stderr, "Known providers: Okta, Auth0, Microsoft/Azure, AWS Cognito User Pool, Generic OIDC.")
		fmt.Fprintln(os.Stderr, "Set provider_type to \"generic\" in config.json for custom OIDC providers.")
		os.Exit(1)
	}
	return detected
}

func (a *credentialApp) getCachedCredentials() *federation.AWSCredentials {
	var creds *federation.AWSCredentials
	var err error

	if a.cfg.CredentialStorage == "keyring" {
		creds, err = storage.ReadFromKeyring(a.profile)
	} else {
		creds, err = storage.ReadFromCredentialsFile(a.profile)
	}
	if err != nil || creds == nil || storage.IsExpiredDummy(creds) {
		return nil
	}

	remaining := storage.ParseExpirationSeconds(creds.Expiration)
	if remaining <= 30 {
		return nil
	}
	return creds
}

func (a *credentialApp) saveCredentials(creds *federation.AWSCredentials) error {
	if a.cfg.CredentialStorage == "keyring" {
		return storage.SaveToKeyring(creds, a.profile)
	}
	return storage.SaveToCredentialsFile(creds, a.profile)
}

func (a *credentialApp) clearCache() {
	if a.cfg.CredentialStorage == "keyring" {
		_ = storage.ClearKeyring(a.profile)
	}
	// Remove the profile section from ~/.aws/credentials rather than writing an
	// EXPIRED placeholder. That file outranks credential_process in the AWS SDK
	// resolution chain, so a placeholder entry would permanently wedge SDK
	// consumers (Claude Code): they'd keep reading the static EXPIRED keys and
	// never invoke this binary again. With the section removed, the SDK falls
	// through to credential_process and recovery is automatic.
	_ = storage.RemoveFromCredentialsFile(a.profile)
	// Clear refresh token
	storage.ClearRefreshToken(a.profile)
	fmt.Fprintf(os.Stderr, "Cleared cached credentials for profile '%s'\n", a.profile)
}

func (a *credentialApp) getMonitoringToken() int {
	token, err := storage.GetMonitoringToken(a.profile, a.cfg.CredentialStorage)
	if err == nil && token != "" {
		fmt.Println(token)
		return 0
	}

	// Cached monitoring token expired or near-expiry. Try refresh_token
	// exchange (PR #447) before opening a browser — this is the only path
	// that works for Cowork 3P (no browser popup possible) and eliminates
	// per-prompt auth interruptions for terminal users whose monitoring
	// token has aged past the 10-min buffer in storage.GetMonitoringToken
	// while their refresh_token is still valid (typically 7-30 days).
	//
	// Note: the cached-token path is intentionally not attempted here — we
	// just observed storage.GetMonitoringToken() returns empty. Only
	// refresh_token (separately stored) is meaningful. tryRefreshToken mints
	// no AWS credentials, so this path cannot bypass quota enforcement.
	if auth := a.tryRefreshToken(); auth != nil {
		fmt.Println(auth.IDToken)
		return 0
	}

	// No refresh_token available, refresh failed, or refresh produced no
	// readable monitoring token — fall back to browser authentication.
	debugPrint("No valid monitoring token found, triggering authentication...")
	authResult, err := a.authenticate()
	if err != nil {
		// IDC/no-SSO path: OIDC auth not available.
		// Fall back to writing OTEL cache from STS caller identity so
		// the otel-helper can serve user attribution headers without a JWT.
		debugPrint("OIDC authentication not available: %v", err)
		debugPrint("Attempting STS identity resolution for OTEL attribution...")
		if a.writeOtelCacheFromSTS() {
			// Return empty token — otel-helper will use the cached headers
			// from Layer 1 (file cache) on next invocation.
			fmt.Println("")
			return 0
		}
		return 1
	}

	// Persist the monitoring token only. Deliberately NO AWS credential
	// exchange here: this entrypoint serves OTEL attribution, and minting
	// credentials on it would bypass quota enforcement (#761) — every
	// credential-minting path must enforce quota first. A blocked user
	// still gets a monitoring token so their telemetry stays attributed.
	a.saveMonitoringTokenAndHeaders(authResult.IDToken, map[string]interface{}(authResult.TokenClaims))

	fmt.Println(authResult.IDToken)
	return 0
}

// getMCPAuthHeader prints {"Authorization":"Bearer <id_token>"} to stdout for
// use as an MCP server headersHelper (the AgentCore web-search gateway uses a
// CUSTOM_JWT authorizer that validates the same OIDC id_token the solution
// already mints). It MUST NOT open a browser and MUST return quickly so it fits
// inside Claude Code's headersHelper budget — so unlike getMonitoringToken it
// never falls through to authenticate(). On a cache miss it attempts only the
// browserless refresh_token exchange; if that also fails it exits non-zero with
// a clear stderr message rather than hanging or prompting.
func (a *credentialApp) getMCPAuthHeader() int {
	token, err := storage.GetMonitoringToken(a.profile, a.cfg.CredentialStorage)
	if (err != nil || token == "") && a.cfg.IsSsoEnabled() && !a.cfg.IsIDC() {
		// Cached id_token expired/near-expiry. Try the silent refresh_token
		// exchange (no browser) before giving up — but stop here: an MCP
		// headersHelper can never drive an interactive login. Only attempt for
		// OIDC; idc/none have no id_token.
		//
		// tryRefreshToken performs only the token exchange (no AWS credential
		// exchange), so a successful refresh is never thrown away because the
		// unrelated AWS STS/IAM credential exchange fails or times out — the
		// gateway's CUSTOM_JWT authorizer only needs the id_token.
		if auth := a.tryRefreshToken(); auth != nil {
			token, err = auth.IDToken, nil
		}
	}
	if err != nil || token == "" {
		fmt.Fprintf(os.Stderr, "Error: no valid cached token for profile '%s'; run the credential process once to authenticate.\n", a.profile)
		return 1
	}

	out, mErr := json.Marshal(map[string]string{"Authorization": "Bearer " + token})
	if mErr != nil {
		fmt.Fprintf(os.Stderr, "Error: failed to encode auth header: %v\n", mErr)
		return 1
	}
	fmt.Println(string(out))
	return 0
}

func (a *credentialApp) checkExpiration() int {
	creds, err := storage.ReadFromCredentialsFile(a.profile)
	if err != nil || creds == nil || storage.IsExpiredDummy(creds) {
		fmt.Fprintf(os.Stderr, "Credentials expired or missing for profile '%s'\n", a.profile)
		return 1
	}
	remaining := storage.ParseExpirationSeconds(creds.Expiration)
	if remaining <= 30 {
		fmt.Fprintf(os.Stderr, "Credentials expired or missing for profile '%s'\n", a.profile)
		return 1
	}
	fmt.Fprintf(os.Stderr, "Credentials valid for profile '%s'\n", a.profile)
	return 0
}

// showTags prints the contents of the `https://aws.amazon.com/tags` claim
// from the cached monitoring token. This is a diagnostic for customers
// setting up session-tag-based cost attribution -- it answers "is my IdP
// actually emitting the tags I expect?" without needing to decode JWTs
// by hand. Triggers a fresh OIDC flow if no cached token is available.
func (a *credentialApp) showTags() int {
	token, _ := storage.GetMonitoringToken(a.profile, a.cfg.CredentialStorage)
	var claims jwt.Claims
	if token != "" {
		if c, err := jwt.DecodePayload(token); err == nil {
			claims = c
		}
	}
	if claims == nil {
		debugPrint("No cached monitoring token; running OIDC flow to read tags claim")
		authResult, err := a.authenticate()
		if err != nil {
			fmt.Fprintf(os.Stderr, "Error: %v\n", err)
			return 1
		}
		claims = authResult.TokenClaims
		a.saveMonitoringTokenAndHeaders(authResult.IDToken, map[string]interface{}(claims))
	}

	// Accept both claim shapes that STS itself accepts:
	//   flat:   claims["https://aws.amazon.com/tags/principal_tags/<Key>"]
	//   nested: claims["https://aws.amazon.com/tags"].principal_tags.<Key>
	// Gather anything we can find, report nothing only when both shapes are absent.
	summary := map[string]interface{}{}
	if nested, ok := claims["https://aws.amazon.com/tags"]; ok {
		summary["https://aws.amazon.com/tags"] = nested
	}
	flat := map[string]string{}
	for k, v := range claims {
		const prefix = "https://aws.amazon.com/tags/principal_tags/"
		if len(k) > len(prefix) && k[:len(prefix)] == prefix {
			if s, ok := v.(string); ok {
				flat[k[len(prefix):]] = s
			}
		}
	}
	if len(flat) > 0 {
		summary["principal_tags (flat)"] = flat
	}
	if len(summary) == 0 {
		fmt.Fprintln(os.Stderr, "No `https://aws.amazon.com/tags` claim present in the ID token.")
		fmt.Fprintln(os.Stderr, "Your IdP is not configured to emit session tags. See assets/docs/COST_ATTRIBUTION.md section 3.")
		return 1
	}
	// Surface the resolved value of the cost-attribution tag regardless of
	// which shape produced it -- this is the exact value the OTel pipeline
	// emits as x-project. Key name comes from config (default "Project") so
	// customers using CostCenter/BillingCode see the same diagnostic.
	costTagKey := a.cfg.CostAttributionTagKey
	if costTagKey == "" {
		costTagKey = "Project"
	}
	if p := otel.ExtractPrincipalTag(claims, costTagKey); p != "" {
		summary[fmt.Sprintf("%s (resolved)", costTagKey)] = p
	}
	pretty, err := json.MarshalIndent(summary, "", "  ")
	if err != nil {
		fmt.Fprintf(os.Stderr, "Could not format tags claim: %v\n", err)
		return 1
	}
	fmt.Println(string(pretty))
	return 0
}

// showClaims prints ALL claims from the ID token as JSON. It is the
// full-token sibling of showTags: it answers "what is my IdP actually
// sending?" when wiring group-based quota policies or attribution
// (groups, department, custom claims) without hand-decoding JWTs. Same
// token acquisition as showTags: cached monitoring token first, fresh
// OIDC flow only when nothing is cached.
//
// The Python provider's equivalent is the COGNITO_AUTH_DEBUG=1 claim dump
// during auth (credential-helper-parity: both variants expose the claims).
// Note: prints the token's real claims (email, sub, groups) — it is a local
// diagnostic of the caller's own identity, same exposure as --show-tags.
func (a *credentialApp) showClaims() int {
	token, _ := storage.GetMonitoringToken(a.profile, a.cfg.CredentialStorage)
	var claims jwt.Claims
	if token != "" {
		if c, err := jwt.DecodePayload(token); err == nil {
			claims = c
		}
	}
	if claims == nil {
		debugPrint("No cached monitoring token; running OIDC flow to read claims")
		authResult, err := a.authenticate()
		if err != nil {
			fmt.Fprintf(os.Stderr, "Error: %v\n", err)
			return 1
		}
		claims = authResult.TokenClaims
		a.saveMonitoringTokenAndHeaders(authResult.IDToken, map[string]interface{}(claims))
	}
	if len(claims) == 0 {
		fmt.Fprintln(os.Stderr, "No ID token claims available for this profile.")
		fmt.Fprintln(os.Stderr, "(IDC auth has no JWT — identity comes from the IAM ARN, not IdP claims.)")
		return 1
	}

	pretty, err := json.MarshalIndent(map[string]interface{}(claims), "", "  ")
	if err != nil {
		fmt.Fprintf(os.Stderr, "Could not format claims: %v\n", err)
		return 1
	}
	fmt.Println(string(pretty))
	return 0
}

// getTag prints a single principal-tag value from the cached ID token.
// This backs the install-time shell function that sets ANTHROPIC_MODEL
// from the user's Zone tag on every `claude` launch. It is purely local
// (no OIDC flow, no network) so it's safe to call from a non-interactive
// shell function; missing/expired tokens bubble up as distinct exit codes
// the shell function can translate into a user-readable message.
//
// Exit codes:
//
//	0 -- tag present, value printed to stdout
//	2 -- no cached token, or token has no such tag
//	4 -- token is expired (user needs to re-auth)
func (a *credentialApp) getTag(key string) int {
	token, _ := storage.GetMonitoringToken(a.profile, a.cfg.CredentialStorage)
	if token == "" {
		return 2
	}
	claims, err := jwt.DecodePayload(token)
	if err != nil {
		return 2
	}
	if exp := claims.GetFloat("exp"); exp > 0 && int64(exp) < time.Now().Unix() {
		return 4
	}
	value := otel.ExtractPrincipalTag(claims, key)
	if value == "" {
		return 2
	}
	fmt.Println(value)
	return 0
}

func (a *credentialApp) run() int {
	// Check cache first
	if cached := a.getCachedCredentials(); cached != nil {
		// Periodic quota re-check
		if a.shouldRecheckQuota() {
			if !a.performQuotaRecheck() {
				return 1
			}
		}
		outputJSON(cached)
		return 0
	}

	// Try to acquire port lock
	ln, err := portlock.TryAcquire(a.redirectPort)
	if err != nil {
		fmt.Fprintf(os.Stderr, "Error: %v\n", err)
		return 1
	}
	if ln == nil {
		// Port busy — another auth in progress
		debugPrint("Another authentication is in progress, waiting...")
		if portlock.WaitForRelease(a.redirectPort, 60*time.Second) {
			if cached := a.getCachedCredentials(); cached != nil {
				outputJSON(cached)
				return 0
			}
		}
		debugPrint("Authentication timeout or failed in another process")
		return 1
	}
	// Release the port lock so the callback server can use it
	ln.Close()

	// Check cache again (race condition guard)
	if cached := a.getCachedCredentials(); cached != nil {
		outputJSON(cached)
		return 0
	}

	// Try silent refresh using cached id_token before opening browser.
	// Quota is enforced BEFORE the STS exchange, using the id_token already in
	// hand, so an over-quota user never mints or caches fresh credentials and
	// the check can never be skipped because a separate storage read came back
	// empty (#761).
	if auth := a.cachedTokenAuthResult(); auth != nil {
		if !a.enforceQuota(auth.IDToken) {
			return 1
		}
		if creds := a.exchangeAndSaveCredentials(auth); creds != nil {
			debugPrint("Silent credential refresh succeeded")
			outputJSON(creds)
			return 0
		}
		debugPrint("Silent refresh failed, trying refresh_token exchange...")
	}

	// Try refresh_token exchange before falling back to browser auth.
	// This enables Cowork 3P (Claude Desktop) to refresh silently even after
	// the id_token expires, since Claude Desktop cannot open a browser popup.
	// Same ordering contract as above: quota first, credentials second.
	if auth := a.tryRefreshToken(); auth != nil {
		if !a.enforceQuota(auth.IDToken) {
			return 1
		}
		if creds := a.exchangeAndSaveCredentials(auth); creds != nil {
			debugPrint("Refresh token exchange succeeded — credentials renewed without browser")
			outputJSON(creds)
			return 0
		}
		debugPrint("AWS credential exchange after refresh failed, falling back to browser auth")
	}

	// Authenticate with OIDC provider (browser popup)
	debugPrint("Authenticating with %s for profile '%s'...", a.providerType, a.profile)
	authResult, err := a.authenticate()
	if err != nil {
		fmt.Fprintf(os.Stderr, "Error: %v\n", err)
		return 1
	}

	// Quota check before issuing credentials
	if !a.enforceQuota(authResult.IDToken) {
		return 1
	}

	// Get AWS credentials
	debugPrint("Exchanging token for AWS credentials...")
	awsCreds, err := a.getAWSCredentials(authResult)
	if err != nil {
		if federation.IsRetryableAuthError(err) {
			a.clearCache()
			fmt.Fprintf(os.Stderr, "Authentication failed - cached credentials were invalid and have been cleared.\nPlease try again to re-authenticate.\n")
		} else {
			fmt.Fprintf(os.Stderr, "Error: %v\n", err)
		}
		return 1
	}

	// Cache credentials
	if err := a.saveCredentials(awsCreds); err != nil {
		debugPrint("Failed to save credentials: %v", err)
	}

	// Save monitoring token (non-blocking)
	a.saveMonitoringTokenAndHeaders(authResult.IDToken, map[string]interface{}(authResult.TokenClaims))

	// Persist refresh_token for silent renewal (Cowork 3P support)
	_ = storage.SaveRefreshToken(a.profile, a.cfg.CredentialStorage, authResult.RefreshToken)

	outputJSON(awsCreds)
	return 0
}

func (a *credentialApp) authenticate() (*oidc.AuthResult, error) {
	confidential, err := a.resolveConfidentialAuth()
	if err != nil {
		return nil, err
	}
	var generic *oidc.GenericEndpoints
	if a.providerType == "generic" {
		generic = &oidc.GenericEndpoints{
			AuthorizeURL: a.cfg.OIDCAuthorizationEndpoint,
			TokenURL:     a.cfg.OIDCTokenEndpoint,
		}
	}
	return oidc.Authenticate(
		a.cfg.ProviderDomain,
		a.cfg.ClientID,
		a.providerType,
		a.cfg.OktaAuthServerID, // "" or "default" -> default CAS; anything else rewrites endpoints
		a.redirectPort,
		confidential,
		generic,
		a.cfg.OIDCPrompt,
	)
}

// resolveConfidentialAuth loads Azure confidential-client material -- either a
// client secret from the OS keyring, or a certificate + private-key pair from
// disk. Env-var overrides (AZURE_CLIENT_CERTIFICATE_PATH,
// AZURE_CLIENT_CERTIFICATE_KEY_PATH) take precedence over config.json so
// installs stay portable across machines. Returns nil for public-client flows.
func (a *credentialApp) resolveConfidentialAuth() (*oidc.ConfidentialAuth, error) {
	if a.providerType != "azure" {
		// Non-Azure providers: use client_secret from config.json if present.
		// Google Desktop OAuth requires this for token exchange (Google documents
		// it as non-confidential for installed apps). Other providers use PKCE-only.
		if a.cfg.ClientSecret != "" {
			return &oidc.ConfidentialAuth{ClientSecret: a.cfg.ClientSecret}, nil
		}
		return nil, nil
	}
	mode := a.cfg.AzureAuthMode
	if mode == "" || mode == "public" {
		return nil, nil
	}
	switch mode {
	case "secret":
		secret, err := storage.ReadClientSecret(a.profile)
		if err != nil {
			return nil, fmt.Errorf("reading client secret from keyring: %w", err)
		}
		if secret == "" {
			return nil, fmt.Errorf(
				"azure_auth_mode is 'secret' but no client secret is stored.\n"+
					"Run: credential-process --set-client-secret --profile %s",
				a.profile)
		}
		return &oidc.ConfidentialAuth{ClientSecret: secret}, nil
	case "certificate":
		certPath := os.Getenv("AZURE_CLIENT_CERTIFICATE_PATH")
		if certPath == "" {
			certPath = a.cfg.ClientCertificatePath
		}
		keyPath := os.Getenv("AZURE_CLIENT_CERTIFICATE_KEY_PATH")
		if keyPath == "" {
			keyPath = a.cfg.ClientCertificateKeyPath
		}
		if certPath == "" || keyPath == "" {
			return nil, fmt.Errorf(
				"azure_auth_mode is 'certificate' but no certificate paths are configured.\n" +
					"Set AZURE_CLIENT_CERTIFICATE_PATH and AZURE_CLIENT_CERTIFICATE_KEY_PATH, " +
					"or update 'client_certificate_path' and 'client_certificate_key_path' in config.json.")
		}
		return &oidc.ConfidentialAuth{CertificatePath: certPath, PrivateKeyPath: keyPath}, nil
	default:
		return nil, fmt.Errorf("unknown azure_auth_mode %q (expected public, secret, or certificate)", mode)
	}
}

func (a *credentialApp) getAWSCredentials(auth *oidc.AuthResult) (*federation.AWSCredentials, error) {
	if a.cfg.FederationType == "direct" {
		return federation.AssumeRoleWithWebIdentity(
			a.cfg.AWSRegion, a.cfg.FederatedRoleARN, auth.IDToken,
			auth.TokenClaims, a.cfg.MaxSessionDuration,
		)
	}
	return federation.GetCredentialsViaCognito(
		a.cfg.AWSRegion, a.cfg.IdentityPoolID, a.cfg.ProviderDomain,
		a.providerType, auth.IDToken, auth.TokenClaims,
	)
}

// enforceQuota performs the pre-issuance quota check with the given id_token.
// Returns false when credentials must NOT be issued. When a quota endpoint is
// configured but no usable token is available, the outcome is decided by
// quota_fail_mode — never silently skipped (#761).
func (a *credentialApp) enforceQuota(idToken string) bool {
	if a.cfg.QuotaAPIEndpoint == "" {
		return true
	}
	if idToken == "" {
		// The OIDC quota API expects a JWT. Never fall through to the SigV4
		// path here — inside credential-process the default credential chain
		// would recurse into ourselves.
		if a.cfg.QuotaFailMode == "closed" {
			fmt.Fprintln(os.Stderr, "Error: quota enforcement is configured but no identity token is available for the check (quota fail mode: closed).")
			return false
		}
		debugPrint("Quota check has no identity token; allowing per fail mode 'open'")
		return true
	}
	qr := quota.Check(a.cfg.QuotaAPIEndpoint, idToken, a.cfg.QuotaCheckTimeout, a.cfg.QuotaFailMode)
	if !qr.Allowed {
		printQuotaBlocked(qr)
		return false
	}
	printQuotaWarning(qr)
	_ = storage.SaveQuotaState(a.profile)
	return true
}

// cachedTokenAuthResult builds an AuthResult from the cached monitoring
// id_token, or returns nil when no valid unexpired token is cached. It makes
// no network calls — the caller decides what to do with the token (quota
// check first, then STS exchange).
func (a *credentialApp) cachedTokenAuthResult() *oidc.AuthResult {
	token, err := storage.GetMonitoringToken(a.profile, a.cfg.CredentialStorage)
	if err != nil || token == "" {
		debugPrint("No valid cached id_token for silent refresh")
		return nil
	}
	claims, err := jwt.DecodePayload(token)
	if err != nil {
		debugPrint("Failed to decode cached id_token: %v", err)
		return nil
	}
	// Check if the id_token itself is expired
	if exp := claims.GetFloat("exp"); exp > 0 && int64(exp) < time.Now().Unix() {
		debugPrint("Cached id_token is expired, silent refresh not possible")
		return nil
	}
	debugPrint("Found valid cached id_token, attempting silent credential refresh...")
	return &oidc.AuthResult{IDToken: token, TokenClaims: claims}
}

// exchangeAndSaveCredentials exchanges a quota-cleared id_token for AWS
// credentials and persists them plus the monitoring token. Callers MUST run
// enforceQuota first — this is the only place the silent-refresh paths mint
// credentials, which keeps the "quota before STS" ordering in one spot.
// Returns nil on failure so callers can fall through to the next auth path.
func (a *credentialApp) exchangeAndSaveCredentials(auth *oidc.AuthResult) *federation.AWSCredentials {
	creds, err := a.getAWSCredentials(auth)
	if err != nil {
		debugPrint("AWS credential exchange failed: %v", err)
		return nil
	}
	if saveErr := a.saveCredentials(creds); saveErr != nil {
		debugPrint("Failed to save credentials: %v", saveErr)
	}
	// Re-save monitoring token to refresh its expiry tracking
	a.saveMonitoringTokenAndHeaders(auth.IDToken, map[string]interface{}(auth.TokenClaims))
	return creds
}

// tryRefreshToken attempts to use a stored OIDC refresh_token to obtain a
// fresh id_token without browser interaction. This is the key enabler for
// Cowork 3P (Claude Desktop): after the id_token expires, credential-process
// can still silently refresh credentials as long as the refresh_token is valid
// (typically 7-30 days depending on IdP configuration).
//
// It persists the refreshed monitoring token and rotated refresh_token, but
// deliberately does NOT exchange for AWS credentials: quota must be enforced
// on the fresh id_token before any STS call (#761), and callers like
// --get-mcp-auth-header and --get-monitoring-token only need the id_token.
func (a *credentialApp) tryRefreshToken() *oidc.AuthResult {
	refreshToken := storage.LoadRefreshToken(a.profile, a.cfg.CredentialStorage)
	if refreshToken == "" {
		debugPrint("No cached refresh_token, cannot refresh silently")
		return nil
	}

	debugPrint("Found cached refresh_token, attempting token exchange...")

	// Resolve token endpoint URL. Generic providers supply an absolute URL
	// directly; named providers go through the shared builder that normalizes
	// the domain (e.g. strips Azure's trailing /v2.0) so this refresh path and
	// the authorization-code flow always produce the same URL.
	var tokenURL string
	if a.providerType == "generic" {
		tokenURL = a.cfg.OIDCTokenEndpoint
	} else {
		tokenURL = provider.TokenEndpointURL(a.providerType, a.cfg.OktaAuthServerID, a.cfg.ProviderDomain)
	}

	// Resolve confidential client auth (Azure secret/cert)
	confidential, err := a.resolveConfidentialAuth()
	if err != nil {
		debugPrint("Failed to resolve confidential auth for refresh: %v", err)
		return nil
	}

	// Exchange refresh_token for fresh tokens
	tokenResp, err := oidc.RefreshTokenExchange(tokenURL, refreshToken, a.cfg.ClientID, confidential)
	if err != nil {
		debugPrint("Refresh token exchange failed: %v", err)
		// Only discard the refresh_token when the IdP definitively rejected it
		// (invalid_grant / invalid_token). Transient failures — network/5xx/
		// timeout, or a misconfiguration such as an unresolved provider type —
		// must retain the token so a later cycle can retry; clearing on those was
		// what permanently disabled silent renewal until the next browser login.
		if oidc.IsDefinitiveRefreshFailure(err) {
			debugPrint("Refresh_token rejected by IdP (invalid_grant); clearing stored token")
			storage.ClearRefreshToken(a.profile)
		} else {
			debugPrint("Transient refresh failure; retaining refresh_token for next attempt")
		}
		return nil
	}

	if tokenResp.IDToken == "" {
		debugPrint("Refresh response did not contain an id_token")
		return nil
	}

	// Decode fresh id_token
	claims, err := jwt.DecodePayload(tokenResp.IDToken)
	if err != nil {
		debugPrint("Failed to decode refreshed id_token: %v", err)
		return nil
	}

	// Update monitoring token with fresh id_token
	a.saveMonitoringTokenAndHeaders(tokenResp.IDToken, map[string]interface{}(claims))

	// Persist rotated refresh_token (some IdPs rotate on every use)
	if tokenResp.RefreshToken != "" {
		_ = storage.SaveRefreshToken(a.profile, a.cfg.CredentialStorage, tokenResp.RefreshToken)
	}

	debugPrint("id_token refreshed without browser")
	return &oidc.AuthResult{
		IDToken:      tokenResp.IDToken,
		RefreshToken: tokenResp.RefreshToken,
		TokenClaims:  claims,
	}
}

// saveMonitoringTokenAndHeaders persists the monitoring token and also writes
// the otel-headers cache so the PowerShell fallback (otel-helper.ps1) can serve
// attribution headers without needing the Go otel-helper binary.
// This is safe to call from any path that obtains a fresh ID token + claims.
func (a *credentialApp) saveMonitoringTokenAndHeaders(idToken string, claims map[string]interface{}) {
	_ = storage.SaveMonitoringToken(a.profile, a.cfg.CredentialStorage, idToken, claims)

	// Also write otel-headers cache for PS1 fallback parity
	jwtClaims, err := jwt.DecodePayload(idToken)
	if err != nil {
		debugPrint("saveMonitoringTokenAndHeaders: JWT decode failed: %v", err)
		return
	}
	costTagKey := "Project"
	if a.cfg.CostAttributionTagKey != "" {
		costTagKey = a.cfg.CostAttributionTagKey
	}
	userInfo := otel.ExtractUserInfoWithTagKey(jwtClaims, costTagKey)
	headers := otel.FormatHeaders(userInfo)
	tokenExp := int64(jwtClaims.GetFloat("exp"))
	if tokenExp > 0 {
		if err := otel.WriteCachedHeaders(a.profile, headers, tokenExp); err != nil {
			debugPrint("saveMonitoringTokenAndHeaders: cache write failed: %v", err)
		}
	}
}

func (a *credentialApp) shouldRecheckQuota() bool {
	if a.cfg.QuotaAPIEndpoint == "" {
		return false
	}
	// Check if enough time has passed since last quota check
	lastCheck := storage.ReadQuotaState(a.profile)
	if lastCheck.IsZero() {
		// Never checked — trigger check
		return true
	}
	interval := time.Duration(a.cfg.QuotaCheckInterval) * time.Minute
	return time.Since(lastCheck) >= interval
}

func (a *credentialApp) performQuotaRecheck() bool {
	token, _ := storage.GetMonitoringToken(a.profile, a.cfg.CredentialStorage)
	if token == "" {
		// Cached id_token aged past the 10-min buffer in GetMonitoringToken.
		// This path is OIDC-only (IDC/passthrough have separate entrypoints),
		// so the quota API expects a JWT — a SigV4 call would 401. Mirror the
		// getMonitoringToken() handler: try a silent refresh_token exchange to
		// mint a fresh id_token before giving up, so an over-quota user is still
		// warned/blocked on the cache-hit fast path instead of silently passing.
		if auth := a.tryRefreshToken(); auth != nil {
			token = auth.IDToken
		}
	}
	if token == "" {
		// No cached token and no usable refresh_token (revoked/absent). The only
		// remaining recovery is a browser flow, which must NOT fire on the
		// cache-hit fast path (runs on every AWS API call). Fail open, but leave
		// the quota-state timestamp unset so the next invocation retries once a
		// fresh token is available.
		debugPrint("Quota recheck skipped: no cached id_token and no usable refresh_token")
		return true
	}
	qr := quota.Check(a.cfg.QuotaAPIEndpoint, token, a.cfg.QuotaCheckTimeout, a.cfg.QuotaFailMode)

	// Persist the check timestamp regardless of outcome
	_ = storage.SaveQuotaState(a.profile)

	if !qr.Allowed {
		printQuotaBlocked(qr)
		// Clear cached credentials so subsequent invocations also block
		a.clearCache()
		return false
	}
	printQuotaWarning(qr)
	return true
}

// writeOtelCacheFromSTS resolves user identity via STS GetCallerIdentity and
// writes OTEL attribution headers to the cache file. This enables OTEL user
// attribution for IDC users who don't have a JWT token.
//
// The email is extracted from the assumed-role ARN session name:
//
//	arn:aws:sts::123456789012:assumed-role/RoleName/user@company.com
//
// Returns true if the cache was written successfully.
func (a *credentialApp) writeOtelCacheFromSTS() bool {
	ctx := context.Background()
	cfg, err := awsconfig.LoadDefaultConfig(ctx)
	if err != nil {
		debugPrint("Could not load AWS config for STS: %v", err)
		return false
	}

	stsClient := sts.NewFromConfig(cfg)
	identity, err := stsClient.GetCallerIdentity(ctx, &sts.GetCallerIdentityInput{})
	if err != nil {
		debugPrint("GetCallerIdentity failed: %v", err)
		return false
	}

	// Extract email from ARN: arn:aws:sts::ACCOUNT:assumed-role/ROLE/SESSION_NAME
	arn := ""
	if identity.Arn != nil {
		arn = *identity.Arn
	}
	email := extractEmailFromARN(arn)
	if email == "" {
		debugPrint("Could not extract email from ARN: %s", arn)
		return false
	}

	debugPrint("Resolved user email from STS: %s", email)

	// Build OTEL headers with the resolved email
	userInfo := otel.UserInfo{Email: email}
	headers := otel.FormatHeaders(userInfo)

	// Cache for 1 hour (IDC sessions are typically longer)
	expiry := time.Now().Add(1 * time.Hour).Unix()
	if err := otel.WriteCachedHeaders(a.profile, headers, expiry); err != nil {
		debugPrint("Failed to write OTEL cache: %v", err)
		return false
	}

	debugPrint("Wrote OTEL attribution cache for IDC user: %s", email)
	return true
}

// extractEmailFromARN extracts the session name (typically email) from an
// assumed-role ARN. Format: arn:aws:sts::ACCOUNT:assumed-role/ROLE/SESSION
//
// For IAM Identity Center, the session name is the IDC username — which may
// be an email (user@company.com) or a plain username (akshaya.claude).
// Non-email usernames are accepted when the role name contains "AWSReservedSSO"
// (confirming it's an IDC-assumed role, not a Lambda/service role).
func extractEmailFromARN(arn string) string {
	// Split on "/" — assumed-role ARNs have: assumed-role/RoleName/SessionName
	parts := strings.Split(arn, "/")
	if len(parts) < 3 {
		return ""
	}
	sessionName := parts[len(parts)-1]
	if sessionName == "" {
		return ""
	}
	// Standard case: session name is an email address
	if strings.Contains(sessionName, "@") {
		return sessionName
	}
	// Non-email IDC username (e.g. "akshaya.claude") — accept if AWSReservedSSO role
	if strings.Contains(arn, "AWSReservedSSO") {
		return sessionName
	}
	return ""
}

func printQuotaWarning(qr *quota.Result) {
	usage := qr.Usage
	if usage == nil {
		return
	}

	monthlyPercent, _ := usage["monthly_percent"].(float64)
	dailyPercent, _ := usage["daily_percent"].(float64)

	// Only show warning at 80%+ threshold
	if monthlyPercent < 80 && dailyPercent < 80 {
		return
	}

	fmt.Fprintln(os.Stderr)
	fmt.Fprintln(os.Stderr, "============================================================")
	fmt.Fprintln(os.Stderr, "QUOTA WARNING")
	fmt.Fprintln(os.Stderr, "============================================================")

	if monthlyTokens, ok := usage["monthly_tokens"].(float64); ok {
		if monthlyLimit, ok2 := usage["monthly_limit"].(float64); ok2 {
			fmt.Fprintf(os.Stderr, "  Monthly: %s / %s tokens (%.1f%%)\n",
				formatTokens(monthlyTokens), formatTokens(monthlyLimit), monthlyPercent)
		}
	}
	if dailyTokens, ok := usage["daily_tokens"].(float64); ok {
		if dailyLimit, ok2 := usage["daily_limit"].(float64); ok2 {
			fmt.Fprintf(os.Stderr, "  Daily: %s / %s tokens (%.1f%%)\n",
				formatTokens(dailyTokens), formatTokens(dailyLimit), dailyPercent)
		}
	}

	fmt.Fprintln(os.Stderr, "============================================================")

	// Show browser notification for visual feedback (invisible stderr → visible browser)
	showQuotaBrowserNotification(qr, false)
}

func formatTokens(n float64) string {
	return fmt.Sprintf("%s", humanizeNumber(int64(n)))
}

func humanizeNumber(n int64) string {
	if n < 0 {
		return "-" + humanizeNumber(-n)
	}
	if n < 1000 {
		return fmt.Sprintf("%d", n)
	}
	result := ""
	for n > 0 {
		if result != "" {
			result = "," + result
		}
		if n >= 1000 {
			result = fmt.Sprintf("%03d", n%1000) + result
		} else {
			result = fmt.Sprintf("%d", n) + result
		}
		n /= 1000
	}
	return result
}

func printQuotaBlocked(qr *quota.Result) {
	usage := qr.Usage
	policy := qr.Policy

	fmt.Fprintln(os.Stderr)
	fmt.Fprintln(os.Stderr, "============================================================")
	fmt.Fprintln(os.Stderr, "ACCESS BLOCKED - QUOTA EXCEEDED")
	fmt.Fprintln(os.Stderr, "============================================================")
	fmt.Fprintf(os.Stderr, "\n%s\n", qr.Message)

	if usage != nil {
		fmt.Fprintln(os.Stderr, "\nCurrent Usage:")
		if monthlyTokens, ok := usage["monthly_tokens"].(float64); ok {
			if monthlyLimit, ok2 := usage["monthly_limit"].(float64); ok2 {
				monthlyPercent, _ := usage["monthly_percent"].(float64)
				fmt.Fprintf(os.Stderr, "  Monthly: %s / %s tokens (%.1f%%)\n",
					formatTokens(monthlyTokens), formatTokens(monthlyLimit), monthlyPercent)
			}
		}
		if dailyTokens, ok := usage["daily_tokens"].(float64); ok {
			if dailyLimit, ok2 := usage["daily_limit"].(float64); ok2 {
				dailyPercent, _ := usage["daily_percent"].(float64)
				fmt.Fprintf(os.Stderr, "  Daily: %s / %s tokens (%.1f%%)\n",
					formatTokens(dailyTokens), formatTokens(dailyLimit), dailyPercent)
			}
		}
	}

	if policy != nil {
		pType, _ := policy["type"].(string)
		pID, _ := policy["identifier"].(string)
		if pType != "" || pID != "" {
			fmt.Fprintf(os.Stderr, "\nPolicy: %s:%s\n", pType, pID)
		}
	}

	fmt.Fprintln(os.Stderr, "\nTo request an unblock, contact your administrator.")
	fmt.Fprintln(os.Stderr, "============================================================")

	// Show browser notification for blocked state
	showQuotaBrowserNotification(qr, true)
}

func outputJSON(v interface{}) {
	data, _ := json.Marshal(v)
	fmt.Println(string(data))
}

// runSetClientSecret stores an Azure confidential-client secret in the OS keyring.
// Mirrors the Python credential-process --set-client-secret behaviour:
//   - Read secret from CCWB_CLIENT_SECRET env var (non-interactive / automation), or
//   - Prompt via terminal (interactive). Blank input clears the stored secret.
func runSetClientSecret(profile string) int {
	var secret string

	if env := os.Getenv("CCWB_CLIENT_SECRET"); env != "" {
		secret = env // pragma: allowlist secret
	} else {
		fmt.Fprintf(os.Stderr, "Enter client secret for profile '%s' (press Enter to clear): ", profile)
		raw, err := term.ReadPassword(int(os.Stdin.Fd()))
		fmt.Fprintln(os.Stderr) // newline after hidden input
		if err != nil {
			fmt.Fprintf(os.Stderr, "Error reading secret: %v\n", err)
			return 1
		}
		secret = string(raw)
	}

	if err := storage.SaveClientSecret(profile, secret); err != nil {
		fmt.Fprintf(os.Stderr, "Error storing client secret: %v\n", err)
		return 1
	}

	if secret == "" {
		fmt.Fprintf(os.Stderr, "✓ Client secret cleared for profile '%s'\n", profile)
	} else {
		fmt.Fprintf(os.Stderr, "✓ Client secret stored for profile '%s'\n", profile)
	}
	return 0
}
