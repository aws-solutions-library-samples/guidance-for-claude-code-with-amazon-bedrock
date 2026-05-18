package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"time"

	"github.com/bluedoors/ccwb-binaries/internal/azure"
	"github.com/bluedoors/ccwb-binaries/internal/config"
	"github.com/bluedoors/ccwb-binaries/internal/federation"
	"github.com/bluedoors/ccwb-binaries/internal/jwt"
	"github.com/bluedoors/ccwb-binaries/internal/oidc"
	"github.com/bluedoors/ccwb-binaries/internal/portlock"
	"github.com/bluedoors/ccwb-binaries/internal/provider"
	"github.com/bluedoors/ccwb-binaries/internal/storage"
	"github.com/bluedoors/ccwb-binaries/internal/version"
	"golang.org/x/term"
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
	clearCache := flag.Bool("clear-cache", false, "Clear cached credentials")
	checkExpiration := flag.Bool("check-expiration", false, "Check if credentials are expired")
	refreshIfNeeded := flag.Bool("refresh-if-needed", false, "Refresh credentials if expired")
	setClientSecret := flag.Bool("set-client-secret", false, "Store Azure AD client secret in OS secure storage")
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

	if *setClientSecret {
		os.Exit(handleSetClientSecret(profile))
	}

	cfg, err := config.LoadProfile(profile)
	if err != nil {
		fmt.Fprintf(os.Stderr, "Error: %v\n", err)
		os.Exit(1)
	}

	// Load client secret from keyring if configured
	if cfg.AzureAuthMode == "secret" {
		if secret, err := azure.ReadClientSecret(profile); err == nil && secret != "" {
			cfg.ClientSecret = secret
		}
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

func (a *credentialApp) trySilentRefresh() (*federation.AWSCredentials, *oidc.AuthResult) {
	token, err := storage.GetMonitoringTokenWithBuffer(a.profile, a.cfg.CredentialStorage, 60)
	if err != nil || token == "" {
		debugPrint("No valid cached id_token for silent refresh")
		return nil, nil
	}

	debugPrint("Found valid cached id_token, attempting silent credential refresh...")
	claims, err := jwt.DecodePayload(token)
	if err != nil {
		debugPrint("Failed to decode cached token: %v", err)
		return nil, nil
	}

	authResult := &oidc.AuthResult{
		IDToken:     token,
		TokenClaims: claims,
	}

	creds, err := a.getAWSCredentials(authResult)
	if err != nil {
		debugPrint("Silent refresh failed, will require browser auth: %v", err)
		return nil, nil
	}

	if err := a.saveCredentials(creds); err != nil {
		debugPrint("Failed to save credentials after silent refresh: %v", err)
	}

	debugPrint("Silent credential refresh succeeded")
	return creds, authResult
}

func (a *credentialApp) run() int {
	// Check cache first
	if cached := a.getCachedCredentials(); cached != nil {
		outputJSON(cached)
		return 0
	}

	// Try silent refresh using cached id_token before opening browser
	if creds, _ := a.trySilentRefresh(); creds != nil {
		outputJSON(creds)
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

	// Debug: log token claims
	if debug {
		debugPrint("\n=== ID Token Claims ===")
		claimsJSON, _ := json.MarshalIndent(authResult.TokenClaims, "", "  ")
		debugPrint("%s", string(claimsJSON))
		debugPrint("\n=== Key Claims for Mapping ===")
		for _, key := range []string{"sub", "email", "name", "preferred_username", "groups", "cognito:groups", "custom:department", "custom:role"} {
			if v := authResult.TokenClaims.GetString(key); v != "" {
				debugPrint("%s: %s", key, v)
			}
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

	// Cache ID token for silent refresh on next invocation
	_ = storage.SaveMonitoringToken(a.profile, a.cfg.CredentialStorage,
		authResult.IDToken, map[string]interface{}(authResult.TokenClaims))

	outputJSON(awsCreds)
	return 0
}

func (a *credentialApp) authenticate() (*oidc.AuthResult, error) {
	opts := &oidc.AuthOptions{
		ProviderDomain: a.cfg.ProviderDomain,
		ClientID:       a.cfg.ClientID,
		ProviderType:   a.providerType,
		RedirectPort:   a.redirectPort,
	}

	if a.cfg.AzureAuthMode == "certificate" {
		tokenURL := "https://" + a.cfg.ProviderDomain + "/oauth2/v2.0/token"
		assertion, err := azure.BuildClientAssertion(
			a.cfg.ClientCertificatePath, a.cfg.ClientCertificateKeyPath,
			a.cfg.ClientID, tokenURL,
		)
		if err != nil {
			return nil, fmt.Errorf("building client assertion: %w", err)
		}
		opts.ConfidentialClient = &oidc.ConfidentialClientOpts{
			ClientAssertion:     assertion,
			ClientAssertionType: "urn:ietf:params:oauth:client-assertion-type:jwt-bearer",
		}
	} else if a.cfg.AzureAuthMode == "secret" && a.cfg.ClientSecret != "" {
		opts.ConfidentialClient = &oidc.ConfidentialClientOpts{
			ClientSecret: a.cfg.ClientSecret,
		}
	}

	return oidc.AuthenticateWithOpts(opts)
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

func handleSetClientSecret(profile string) int {
	envSecret := os.Getenv("CCWB_CLIENT_SECRET")
	var secret string

	if envSecret != "" {
		secret = envSecret
	} else {
		fmt.Fprintf(os.Stderr, "Enter client secret for profile '%s' (press Enter to clear): ", profile)
		rawSecret, err := term.ReadPassword(int(os.Stdin.Fd()))
		fmt.Fprintln(os.Stderr)
		if err != nil {
			fmt.Fprintf(os.Stderr, "Error reading input: %v\n", err)
			return 1
		}
		secret = string(rawSecret)
	}

	if secret == "" {
		if err := azure.DeleteClientSecret(profile); err != nil {
			// Ignore "not found" errors when clearing
			debugPrint("Note: %v", err)
		}
		fmt.Fprintf(os.Stderr, "Client secret cleared for profile '%s'\n", profile)
		return 0
	}

	if err := azure.SaveClientSecret(profile, secret); err != nil {
		fmt.Fprintf(os.Stderr, "Error storing client secret: %v\n", err)
		return 1
	}
	fmt.Fprintf(os.Stderr, "Client secret stored in OS secure storage for profile '%s'\n", profile)
	return 0
}

func outputJSON(v interface{}) {
	data, _ := json.Marshal(v)
	fmt.Println(string(data))
}
