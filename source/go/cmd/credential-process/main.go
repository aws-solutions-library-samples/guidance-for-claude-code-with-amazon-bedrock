package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"time"

	"github.com/bluedoors/ccwb-binaries/internal/config"
	"github.com/bluedoors/ccwb-binaries/internal/federation"
	"github.com/bluedoors/ccwb-binaries/internal/jwt"
	"github.com/bluedoors/ccwb-binaries/internal/oidc"
	"github.com/bluedoors/ccwb-binaries/internal/portlock"
	"github.com/bluedoors/ccwb-binaries/internal/provider"
	"github.com/bluedoors/ccwb-binaries/internal/quota"
	"github.com/bluedoors/ccwb-binaries/internal/storage"
	"github.com/bluedoors/ccwb-binaries/internal/version"
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

	// Resolve provider type
	providerType := resolveProviderType(cfg)

	app := &credentialApp{
		profile:      profile,
		cfg:          cfg,
		providerType: providerType,
		redirectPort: 8400,
	}

	if *clearCache {
		app.clearCache()
		os.Exit(0)
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
		fmt.Fprintln(os.Stderr, "Known providers: Okta, Auth0, Microsoft/Azure, AWS Cognito User Pool.")
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

	// Authenticate
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

	outputJSON(awsCreds)
	return 0
}

func (a *credentialApp) authenticate() (*oidc.AuthResult, error) {
	return oidc.Authenticate(a.cfg.ProviderDomain, a.cfg.ClientID, a.providerType, a.redirectPort)
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
