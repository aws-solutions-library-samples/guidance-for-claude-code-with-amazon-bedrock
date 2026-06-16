package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"strconv"
	"time"

	"ccwb-go/internal/config"
	"ccwb-go/internal/federation"
	"ccwb-go/internal/jwt"
	"ccwb-go/internal/oidc"
	"ccwb-go/internal/otel"
	"ccwb-go/internal/persona"
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
	clearCache := flag.Bool("clear-cache", false, "Clear cached credentials")
	checkExpiration := flag.Bool("check-expiration", false, "Check if credentials are expired")
	refreshIfNeeded := flag.Bool("refresh-if-needed", false, "Refresh credentials if expired")
	showTags := flag.Bool("show-tags", false, "Print the https://aws.amazon.com/tags claim from the cached ID token (debug)")
	getTag := flag.String("get-tag", "", "Print the value of a single principal tag from the cached ID token (e.g. --get-tag Zone). Exit codes: 0 hit, 2 absent, 4 expired.")
	getPersonaModel := flag.Bool("get-persona-model", false, "Print shell `export` lines routing ANTHROPIC_*_MODEL to the resolved persona's per-tier inference profiles (FR-5.1). Local only. Exit codes: 0 emitted, 2 no persona/ARNs, 4 token expired.")
	personaTier := flag.String("tier", "", "With --get-persona-model: emit only this tier (haiku|sonnet|opus). Default emits all tiers the persona has, plus ANTHROPIC_MODEL=primary.")
	flag.Parse()

	if *versionFlag || *shortVersion {
		fmt.Printf("credential-process %s\n", version.Version)
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

	debug = os.Getenv("COGNITO_AUTH_DEBUG") == "1" || os.Getenv("COGNITO_AUTH_DEBUG") == "true" || os.Getenv("COGNITO_AUTH_DEBUG") == "yes"

	cfg, err := config.LoadProfile(profile)
	if err != nil {
		fmt.Fprintf(os.Stderr, "Error: %v\n", err)
		os.Exit(1)
	}

	// SSO-disabled (passthrough) mode. Resolve before provider-type detection
	// because cfg.ProviderDomain is intentionally "none" for these profiles
	// and would trip the auto-detect error otherwise. Mirrors Python PR #303.
	if !cfg.IsSsoEnabled() {
		// Build a minimal app — we don't need providerType or redirectPort for
		// passthrough, only the ambient AWS chain.
		app := &credentialApp{
			profile: profile,
			cfg:     cfg,
		}
		// Honor the small-but-useful flag set that doesn't depend on OIDC.
		if *clearCache {
			app.clearCache()
			os.Exit(0)
		}
		os.Exit(app.runPassthrough())
	}

	// Resolve provider type
	providerType := resolveProviderType(cfg)

	// Resolve redirect port: REDIRECT_PORT env > config.json > 8400
	redirectPort := 8400
	if envPort := os.Getenv("REDIRECT_PORT"); envPort != "" {
		if p, err := strconv.Atoi(envPort); err == nil && p > 0 {
			redirectPort = p
		}
	} else if cfg.RedirectPort > 0 {
		redirectPort = cfg.RedirectPort
	}

	app := &credentialApp{
		profile:      profile,
		cfg:          cfg,
		providerType: providerType,
		redirectPort: redirectPort,
	}

	if *clearCache {
		app.clearCache()
		os.Exit(0)
	}

	if *showTags {
		os.Exit(app.showTags())
	}

	if *getTag != "" {
		os.Exit(app.getTag(*getTag))
	}

	if *getPersonaModel {
		os.Exit(app.getPersonaModel(*personaTier))
	}

	if *getMonitoring {
		os.Exit(app.getMonitoringToken())
	}

	if *checkExpiration {
		os.Exit(app.checkExpiration())
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

	os.Exit(app.run())
}

type credentialApp struct {
	profile      string
	cfg          *config.ProfileConfig
	providerType string
	redirectPort int
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
	// Also clear session file
	expired := &federation.AWSCredentials{
		Version: 1, AccessKeyID: "EXPIRED", SecretAccessKey: "EXPIRED",
		SessionToken: "EXPIRED", Expiration: "2000-01-01T00:00:00Z",
	}
	_ = storage.SaveToCredentialsFile(expired, a.profile)
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

	// No cached token — trigger authentication
	debugPrint("No valid monitoring token found, triggering authentication...")
	authResult, err := a.authenticate()
	if err != nil {
		debugPrint("Authentication failed: %v", err)
		return 1
	}

	// Get AWS creds (needed to complete the flow)
	awsCreds, err := a.getAWSCredentials(authResult)
	if err != nil {
		debugPrint("Failed to get AWS credentials: %v", err)
		return 1
	}
	_ = a.saveCredentials(awsCreds)

	// Save monitoring token
	_ = storage.SaveMonitoringToken(a.profile, a.cfg.CredentialStorage,
		authResult.IDToken, map[string]interface{}(authResult.TokenClaims))

	fmt.Println(authResult.IDToken)
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
		_ = storage.SaveMonitoringToken(a.profile, a.cfg.CredentialStorage,
			authResult.IDToken, map[string]interface{}(claims))
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

// getPersonaModel resolves the user's persona from the cached ID token's groups
// claim and prints shell `export` lines that point ANTHROPIC_*_MODEL at that
// persona's per-tier Application Inference Profile ARNs (FR-5.1). This backs the
// generated launch wrapper (`persona-model.sh` / `.ps1`) so a persona's traffic
// is attributed to its own cost-tagged profile.
//
// It is purely local (no OIDC flow, no network) so it is safe to call from a
// shell function on every `claude` launch. Output is plain `export KEY=value`
// lines (one per resolved tier) that the wrapper `eval`s; on no match / no ARNs
// it prints nothing and the baked settings.json model stays in effect.
//
// tier (optional) restricts output to a single tier (haiku|sonnet|opus); empty
// emits every tier the persona has an ARN for, plus ANTHROPIC_MODEL set to the
// persona's primary (most-capable) tier.
//
// Exit codes mirror getTag so the wrapper can branch:
//
//	0 -- one or more exports printed
//	2 -- no persona matched, persona has no inference-profile ARNs, or personas
//	     aren't configured (the wrapper then leaves the env untouched)
//	4 -- cached token is expired (user needs to re-auth)
func (a *credentialApp) getPersonaModel(tier string) int {
	if len(a.cfg.Personas) == 0 {
		return 2
	}

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

	lines, code := resolvePersonaModelExports(a.cfg, claims, tier)
	for _, l := range lines {
		fmt.Println(l)
	}
	return code
}

// _tierEnvVar maps a Claude tier to its Claude Code per-tier model env var.
var _tierEnvVar = map[string]string{
	"haiku":  "ANTHROPIC_DEFAULT_HAIKU_MODEL",
	"sonnet": "ANTHROPIC_DEFAULT_SONNET_MODEL",
	"opus":   "ANTHROPIC_DEFAULT_OPUS_MODEL",
}

// _tierOrder is ascending model capability; the last entry a persona has an ARN
// for is its "primary" tier (used for bare ANTHROPIC_MODEL).
var _tierOrder = []string{"haiku", "sonnet", "opus"}

// resolvePersonaModelExports is the pure core of getPersonaModel: given the
// profile config, decoded token claims, and an optional single tier, it returns
// the shell `export` lines to print and the process exit code (0 emitted, 2
// nothing to emit). Factored out (like selectRoleARN) so it is unit-testable
// without touching the credential cache. Expiry is checked by the caller.
func resolvePersonaModelExports(cfg *config.ProfileConfig, claims jwt.Claims, tier string) ([]string, int) {
	if len(cfg.Personas) == 0 {
		return nil, 2
	}
	groupsClaim := cfg.GroupsClaimName
	if groupsClaim == "" {
		groupsClaim = "groups"
	}
	p, err := persona.Resolve(claims.GetStringSlice(groupsClaim), cfg.Personas, cfg.FallbackPersona)
	if err != nil || p == nil || len(p.InferenceProfileArns) == 0 {
		return nil, 2
	}

	var lines []string
	if tier != "" {
		// Single-tier request: emit just that tier's env var if the persona has it.
		envKey, known := _tierEnvVar[tier]
		arn := p.InferenceProfileArns[tier]
		if !known || arn == "" {
			return nil, 2
		}
		lines = append(lines, fmt.Sprintf("export %s=%s", envKey, arn))
		return lines, 0
	}

	// All tiers the persona has, ascending capability so the primary (last) is
	// deterministic. Also set bare ANTHROPIC_MODEL to the primary tier's ARN.
	var primaryARN string
	for _, t := range _tierOrder {
		arn := p.InferenceProfileArns[t]
		if arn == "" {
			continue
		}
		lines = append(lines, fmt.Sprintf("export %s=%s", _tierEnvVar[t], arn))
		primaryARN = arn
	}
	if primaryARN != "" {
		lines = append(lines, fmt.Sprintf("export ANTHROPIC_MODEL=%s", primaryARN))
	}
	if len(lines) == 0 {
		return nil, 2
	}
	return lines, 0
}

func (a *credentialApp) run() int {
	// Check cache first
	if cached := a.getCachedCredentials(); cached != nil {
		// Periodic quota re-check
		if a.shouldRecheckQuota() {
			a.performQuotaRecheck()
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

	// Try silent refresh using cached id_token before opening browser
	if creds := a.trySilentRefresh(); creds != nil {
		if a.cfg.QuotaAPIEndpoint != "" {
			token, _ := storage.GetMonitoringToken(a.profile, a.cfg.CredentialStorage)
			if token != "" {
				qr := quota.Check(a.cfg.QuotaAPIEndpoint, token, a.cfg.QuotaCheckTimeout, a.cfg.QuotaFailMode)
				if !qr.Allowed {
					printQuotaBlocked(qr)
					return 1
				}
			}
		}
		outputJSON(creds)
		return 0
	}

	// Try refresh_token exchange before falling back to browser auth.
	// This enables Cowork 3P (Claude Desktop) to refresh silently even after
	// the id_token expires, since Claude Desktop cannot open a browser popup.
	if creds := a.tryRefreshToken(); creds != nil {
		if a.cfg.QuotaAPIEndpoint != "" {
			token, _ := storage.GetMonitoringToken(a.profile, a.cfg.CredentialStorage)
			if token != "" {
				qr := quota.Check(a.cfg.QuotaAPIEndpoint, token, a.cfg.QuotaCheckTimeout, a.cfg.QuotaFailMode)
				if !qr.Allowed {
					printQuotaBlocked(qr)
					return 1
				}
			}
		}
		outputJSON(creds)
		return 0
	}

	// Authenticate with OIDC provider (browser popup)
	debugPrint("Authenticating with %s for profile '%s'...", a.providerType, a.profile)
	authResult, err := a.authenticate()
	if err != nil {
		fmt.Fprintf(os.Stderr, "Error: %v\n", err)
		return 1
	}

	// Quota check before issuing credentials
	if a.cfg.QuotaAPIEndpoint != "" {
		qr := quota.Check(a.cfg.QuotaAPIEndpoint, authResult.IDToken, a.cfg.QuotaCheckTimeout, a.cfg.QuotaFailMode)
		if !qr.Allowed {
			printQuotaBlocked(qr)
			return 1
		}
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
	_ = storage.SaveMonitoringToken(a.profile, a.cfg.CredentialStorage,
		authResult.IDToken, map[string]interface{}(authResult.TokenClaims))

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
	)
}

// resolveConfidentialAuth loads Azure confidential-client material -- either a
// client secret from the OS keyring, or a certificate + private-key pair from
// disk. Env-var overrides (AZURE_CLIENT_CERTIFICATE_PATH,
// AZURE_CLIENT_CERTIFICATE_KEY_PATH) take precedence over config.json so
// installs stay portable across machines. Returns nil for public-client flows.
func (a *credentialApp) resolveConfidentialAuth() (*oidc.ConfidentialAuth, error) {
	if a.providerType != "azure" {
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
					"Run: ccwb init --profile %s (re-run the Azure step) to store one in the OS keyring.",
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

// selectRoleARN decides which IAM role the direct-STS path should assume.
//
// With no personas configured it returns the profile's FederatedRoleARN —
// byte-for-byte today's behavior, so existing deployments are unaffected. When
// personas are configured (persona-based access, direct-IAM only), it resolves
// the user's persona from their groups claim using the shared §4.3 algorithm
// (persona.Resolve) and returns that persona's role ARN. A user whose groups
// match no persona and for whom no fallback is configured is hard-denied with a
// clear, actionable error rather than silently falling back to a broad role.
//
// This is pure, in-memory resolution — no AWS SDK / boto3 calls (the credential
// process is invoked BY the SDK; calling back into it would recurse, see
// credential-recursion.md). The only AWS call remains the existing STS
// AssumeRoleWithWebIdentity performed by the caller.
func selectRoleARN(cfg *config.ProfileConfig, claims jwt.Claims) (string, error) {
	if len(cfg.Personas) == 0 {
		return cfg.FederatedRoleARN, nil
	}

	groupsClaim := cfg.GroupsClaimName
	if groupsClaim == "" {
		groupsClaim = "groups"
	}
	groups := claims.GetStringSlice(groupsClaim)

	p, err := persona.Resolve(groups, cfg.Personas, cfg.FallbackPersona)
	if err != nil {
		return "", fmt.Errorf("resolving persona: %w", err)
	}
	if p == nil {
		// Distinguish the two no-result cases so the admin sees the right cause:
		// a fallback that names a non-existent persona is a config error to fix,
		// whereas no fallback at all means the user needs a persona group. Both
		// are correctly hard-denied (no role assumed); only the message differs.
		if cfg.FallbackPersona != "" {
			return "", fmt.Errorf(
				"no persona matched your groups %v (claim %q) and the configured fallback_persona %q "+
					"does not name any declared persona; fix fallback_persona in config.yaml and re-run `ccwb package`",
				groups, groupsClaim, cfg.FallbackPersona,
			)
		}
		return "", fmt.Errorf(
			"no persona matched your groups %v (claim %q) and no fallback persona is configured; "+
				"contact your administrator to be added to a persona group",
			groups, groupsClaim,
		)
	}
	if p.RoleARN == "" {
		return "", fmt.Errorf(
			"persona %q matched but has no role ARN in config.json; "+
				"re-run `ccwb package` after deploying the persona stack",
			p.Name,
		)
	}
	return p.RoleARN, nil
}

func (a *credentialApp) getAWSCredentials(auth *oidc.AuthResult) (*federation.AWSCredentials, error) {
	if a.cfg.FederationType == "direct" {
		roleARN, err := selectRoleARN(a.cfg, auth.TokenClaims)
		if err != nil {
			return nil, err
		}
		return federation.AssumeRoleWithWebIdentity(
			a.cfg.AWSRegion, roleARN, auth.IDToken,
			auth.TokenClaims, a.cfg.MaxSessionDuration,
		)
	}
	return federation.GetCredentialsViaCognito(
		a.cfg.AWSRegion, a.cfg.IdentityPoolID, a.cfg.ProviderDomain,
		a.providerType, auth.IDToken, auth.TokenClaims,
	)
}

func (a *credentialApp) trySilentRefresh() *federation.AWSCredentials {
	token, err := storage.GetMonitoringToken(a.profile, a.cfg.CredentialStorage)
	if err != nil || token == "" {
		debugPrint("No valid cached id_token for silent refresh")
		return nil
	}
	debugPrint("Found valid cached id_token, attempting silent credential refresh...")
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
	authResult := &oidc.AuthResult{IDToken: token, TokenClaims: claims}
	creds, err := a.getAWSCredentials(authResult)
	if err != nil {
		debugPrint("Silent refresh failed, will require browser auth: %v", err)
		return nil
	}
	if saveErr := a.saveCredentials(creds); saveErr != nil {
		debugPrint("Failed to save silently-refreshed credentials: %v", saveErr)
	}
	// Re-save monitoring token to refresh its expiry tracking
	_ = storage.SaveMonitoringToken(a.profile, a.cfg.CredentialStorage,
		token, map[string]interface{}(claims))
	debugPrint("Silent credential refresh succeeded")
	return creds
}

// tryRefreshToken attempts to use a stored OIDC refresh_token to obtain a
// fresh id_token without browser interaction. This is the key enabler for
// Cowork 3P (Claude Desktop): after the id_token expires, credential-process
// can still silently refresh credentials as long as the refresh_token is valid
// (typically 7-30 days depending on IdP configuration).
func (a *credentialApp) tryRefreshToken() *federation.AWSCredentials {
	refreshToken := storage.LoadRefreshToken(a.profile, a.cfg.CredentialStorage)
	if refreshToken == "" {
		debugPrint("No cached refresh_token, cannot refresh silently")
		return nil
	}

	debugPrint("Found cached refresh_token, attempting token exchange...")

	// Resolve token endpoint URL
	var tokenURL string
	if a.providerType == "generic" {
		tokenURL = a.cfg.OIDCTokenEndpoint
	} else {
		provCfg := provider.ConfigFor(a.providerType, a.cfg.OktaAuthServerID)
		domain := a.cfg.ProviderDomain
		tokenURL = "https://" + domain + provCfg.TokenEndpoint
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
		// Token may be revoked/expired — clear it so we don't retry next time
		storage.ClearRefreshToken(a.profile)
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

	// Exchange for AWS credentials
	authResult := &oidc.AuthResult{
		IDToken:      tokenResp.IDToken,
		RefreshToken: tokenResp.RefreshToken,
		TokenClaims:  claims,
	}
	creds, err := a.getAWSCredentials(authResult)
	if err != nil {
		debugPrint("AWS credential exchange after refresh failed: %v", err)
		return nil
	}

	// Save refreshed credentials
	if saveErr := a.saveCredentials(creds); saveErr != nil {
		debugPrint("Failed to save refresh-derived credentials: %v", saveErr)
	}

	// Update monitoring token with fresh id_token
	_ = storage.SaveMonitoringToken(a.profile, a.cfg.CredentialStorage,
		tokenResp.IDToken, map[string]interface{}(claims))

	// Persist rotated refresh_token (some IdPs rotate on every use)
	if tokenResp.RefreshToken != "" {
		_ = storage.SaveRefreshToken(a.profile, a.cfg.CredentialStorage, tokenResp.RefreshToken)
	}

	debugPrint("Refresh token exchange succeeded — credentials renewed without browser")
	return creds
}

func (a *credentialApp) shouldRecheckQuota() bool {
	if a.cfg.QuotaAPIEndpoint == "" {
		return false
	}
	// Simple interval check - omitting full persistence for now
	return false
}

func (a *credentialApp) performQuotaRecheck() {
	token, _ := storage.GetMonitoringToken(a.profile, a.cfg.CredentialStorage)
	if token == "" {
		return
	}
	claims, err := jwt.DecodePayload(token)
	if err != nil {
		return
	}
	qr := quota.Check(a.cfg.QuotaAPIEndpoint, token, a.cfg.QuotaCheckTimeout, a.cfg.QuotaFailMode)
	_ = claims // suppress unused
	if !qr.Allowed {
		printQuotaBlocked(qr)
	}
}

func printQuotaBlocked(qr *quota.Result) {
	fmt.Fprintln(os.Stderr)
	fmt.Fprintln(os.Stderr, "============================================================")
	fmt.Fprintln(os.Stderr, "ACCESS BLOCKED - QUOTA EXCEEDED")
	fmt.Fprintln(os.Stderr, "============================================================")
	fmt.Fprintf(os.Stderr, "\n%s\n", qr.Message)
	fmt.Fprintln(os.Stderr, "\nTo request an unblock, contact your administrator.")
	fmt.Fprintln(os.Stderr, "============================================================")
}

func outputJSON(v interface{}) {
	data, _ := json.Marshal(v)
	fmt.Println(string(data))
}
