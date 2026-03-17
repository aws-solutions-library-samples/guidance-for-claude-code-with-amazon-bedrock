package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"

	"credential-process-go/internal/auth"
	"credential-process-go/internal/config"
	"credential-process-go/internal/federation"
	"credential-process-go/internal/lock"
	"credential-process-go/internal/quota"
	"credential-process-go/internal/storage"
)

var version = "1.0.0-beta" // overridden by -ldflags

func main() {
	os.Exit(run())
}

func run() int {
	// Define flags
	profile := flag.String("profile", "", "Configuration profile to use")
	flag.StringVar(profile, "p", "", "Configuration profile to use (shorthand)")
	showVersion := flag.Bool("version", false, "Show version")
	flag.BoolVar(showVersion, "v", false, "Show version (shorthand)")
	getMonitoringToken := flag.Bool("get-monitoring-token", false, "Get cached monitoring token")
	clearCache := flag.Bool("clear-cache", false, "Clear cached credentials")
	checkExpiration := flag.Bool("check-expiration", false, "Check if credentials are expired")
	refreshIfNeeded := flag.Bool("refresh-if-needed", false, "Refresh credentials if expired")

	flag.Parse()

	if *showVersion {
		fmt.Printf("credential-process %s\n", version)
		return 0
	}

	debug := strings.ToLower(os.Getenv("COGNITO_AUTH_DEBUG"))
	isDebug := debug == "1" || debug == "true" || debug == "yes"

	// Determine binary directory
	binaryDir := ""
	exe, err := os.Executable()
	if err == nil {
		binaryDir = filepath.Dir(exe)
	}

	// Resolve profile name
	profileName := *profile
	if profileName == "" {
		profileName = os.Getenv("CCWB_PROFILE")
	}
	if profileName == "" {
		profileName = config.AutoDetectProfile(binaryDir)
	}
	if profileName == "" {
		profileName = "ClaudeCode"
	}

	// Load config
	cfg, err := config.LoadConfig(profileName, binaryDir)
	if err != nil {
		fmt.Fprintf(os.Stderr, "Error: %v\n", err)
		return 1
	}

	// Initialize storage
	var store storage.Store
	if cfg.CredentialStorage == "keyring" {
		store = &storage.KeyringStore{}
	} else {
		store = &storage.SessionStore{}
	}

	redirectPort := 8400
	if portStr := os.Getenv("REDIRECT_PORT"); portStr != "" {
		fmt.Sscanf(portStr, "%d", &redirectPort)
	}
	redirectURI := fmt.Sprintf("http://localhost:%d/callback", redirectPort)

	// Handle --clear-cache
	if *clearCache {
		cleared := store.ClearCredentials(profileName)
		if len(cleared) > 0 {
			fmt.Fprintf(os.Stderr, "Cleared cached credentials for profile '%s':\n", profileName)
			for _, item := range cleared {
				fmt.Fprintf(os.Stderr, "  • %s\n", item)
			}
		} else {
			fmt.Fprintf(os.Stderr, "No cached credentials found for profile '%s'\n", profileName)
		}
		return 0
	}

	// Handle --get-monitoring-token
	if *getMonitoringToken {
		token := storage.GetMonitoringTokenFromEnvOrStore(store, profileName)
		if token != "" {
			fmt.Println(token)
			return 0
		}

		// No cached token, trigger authentication
		debugPrint(isDebug, "No valid monitoring token found, triggering authentication...")
		token, exitCode := authenticateForMonitoring(cfg, store, profileName, redirectPort, redirectURI, isDebug)
		if token != "" {
			fmt.Println(token)
			return 0
		}
		return exitCode
	}

	// Handle --check-expiration
	if *checkExpiration {
		creds, err := store.GetCredentials(profileName)
		if err != nil || creds == nil || storage.IsExpired(creds) {
			fmt.Fprintf(os.Stderr, "Credentials expired or missing for profile '%s'\n", profileName)
			return 1
		}
		fmt.Fprintf(os.Stderr, "Credentials valid for profile '%s'\n", profileName)
		return 0
	}

	// Handle --refresh-if-needed
	if *refreshIfNeeded {
		if cfg.CredentialStorage != "session" {
			fmt.Fprintln(os.Stderr, "Error: --refresh-if-needed only works with session storage mode")
			return 1
		}
		creds, _ := store.GetCredentials(profileName)
		if creds != nil && !storage.IsExpired(creds) {
			debugPrint(isDebug, fmt.Sprintf("Credentials still valid for profile '%s', no refresh needed", profileName))
			return 0
		}
		// Fall through to normal auth flow
	}

	// Normal credential flow
	return credentialFlow(cfg, store, profileName, redirectPort, redirectURI, isDebug)
}

func credentialFlow(cfg *config.ProfileConfig, store storage.Store, profile string, redirectPort int, redirectURI string, debug bool) int {
	// Check cache first
	cached, _ := store.GetCredentials(profile)
	if cached != nil && !storage.IsExpired(cached) {
		// Periodic quota re-check if needed
		if cfg.QuotaAPIEndpoint != "" {
			if shouldRecheckQuota(cfg, store, profile, debug) {
				debugPrint(debug, "Performing periodic quota re-check...")
				idToken := storage.GetMonitoringTokenFromEnvOrStore(store, profile)
				if idToken != "" {
					result := quota.CheckQuota(cfg.QuotaAPIEndpoint, idToken, cfg.QuotaFailMode, cfg.QuotaCheckTimeout, debug)
					saveQuotaCheckTime(store, profile)
					if !result.Allowed {
						quota.HandleBlocked(result)
						quota.ShowBrowserNotification(result, true, redirectPort+1)
						return 1
					}
					if quota.ShouldWarn(result) {
						quota.HandleWarning(result)
						quota.ShowBrowserNotification(result, false, redirectPort+1)
					}
				} else {
					debugPrint(debug, "No cached token for quota re-check, skipping")
				}
			}
		}

		outputCredentials(cached)
		return 0
	}

	// Port-based concurrency lock
	acquired, err := lock.AcquireOrWait(redirectPort)
	if err != nil {
		fmt.Fprintf(os.Stderr, "Error: %v\n", err)
		return 1
	}
	if !acquired {
		// Another process was authenticating, check cache
		cached, _ = store.GetCredentials(profile)
		if cached != nil && !storage.IsExpired(cached) {
			outputCredentials(cached)
			return 0
		}
		debugPrint(debug, "Authentication timeout or failed in another process")
		return 1
	}

	// Check cache again after acquiring lock
	cached, _ = store.GetCredentials(profile)
	if cached != nil && !storage.IsExpired(cached) {
		outputCredentials(cached)
		return 0
	}

	// Authenticate
	debugPrint(debug, fmt.Sprintf("Authenticating with %s for profile '%s'...", auth.ProviderConfigs[cfg.ProviderType].Name, profile))
	idToken, claims, err := auth.Authenticate(cfg.ProviderType, cfg.ProviderDomain, cfg.ClientID, redirectURI, redirectPort, debug)
	if err != nil {
		return handleAuthError(err)
	}

	// Quota check before credential issuance
	if cfg.QuotaAPIEndpoint != "" {
		debugPrint(debug, "Checking quota before credential issuance...")
		claimsMap := jwtClaimsToMap(claims)
		result := quota.CheckQuota(cfg.QuotaAPIEndpoint, idToken, cfg.QuotaFailMode, cfg.QuotaCheckTimeout, debug)
		saveQuotaCheckTime(store, profile)
		if !result.Allowed {
			quota.HandleBlocked(result)
			quota.ShowBrowserNotification(result, true, redirectPort+1)
			return 1
		}
		if quota.ShouldWarn(result) {
			quota.HandleWarning(result)
			quota.ShowBrowserNotification(result, false, redirectPort+1)
		}
		_ = claimsMap // claims used for debug logging
	}

	// Exchange token for AWS credentials
	debugPrint(debug, "Exchanging token for AWS credentials...")
	credMap, err := federation.GetAWSCredentials(cfg, idToken, claims, debug)
	if err != nil {
		// Check for invalid credential errors that indicate cache should be cleared
		errStr := err.Error()
		if strings.Contains(errStr, "credentials were invalid") {
			store.ClearCredentials(profile)
		}
		fmt.Fprintf(os.Stderr, "Error: %v\n", err)
		return 1
	}

	// Convert to Credentials struct for storage
	creds := &storage.Credentials{
		Version:        1,
		AccessKeyId:    fmt.Sprint(credMap["AccessKeyId"]),
		SecretAccessKey: fmt.Sprint(credMap["SecretAccessKey"]),
		SessionToken:   fmt.Sprint(credMap["SessionToken"]),
		Expiration:     fmt.Sprint(credMap["Expiration"]),
	}

	// Save credentials
	if err := store.SaveCredentials(profile, creds); err != nil {
		debugPrint(debug, fmt.Sprintf("Warning: failed to cache credentials: %v", err))
	}

	// Save monitoring token
	exp := int64(0)
	if expVal, ok := claims["exp"]; ok {
		if expFloat, ok := expVal.(float64); ok {
			exp = int64(expFloat)
		}
	}
	email := ""
	if emailVal, ok := claims["email"]; ok {
		email = fmt.Sprint(emailVal)
	}
	monToken := &storage.MonitoringToken{
		Token:   idToken,
		Expires: exp,
		Email:   email,
		Profile: profile,
	}
	if err := store.SaveMonitoringToken(profile, monToken); err != nil {
		debugPrint(debug, fmt.Sprintf("Warning: could not save monitoring token: %v", err))
	}
	os.Setenv("CLAUDE_CODE_MONITORING_TOKEN", idToken)

	outputCredentials(creds)
	return 0
}

func authenticateForMonitoring(cfg *config.ProfileConfig, store storage.Store, profile string, redirectPort int, redirectURI string, debug bool) (string, int) {
	// Try port lock
	acquired, err := lock.AcquireOrWait(redirectPort)
	if err != nil {
		return "", 1
	}
	if !acquired {
		// Wait for other process, then check for token
		token := storage.GetMonitoringTokenFromEnvOrStore(store, profile)
		if token != "" {
			return token, 0
		}
		debugPrint(debug, "Authentication timeout or failed in another process")
		return "", 1
	}

	debugPrint(debug, fmt.Sprintf("Authenticating with %s for monitoring token...", auth.ProviderConfigs[cfg.ProviderType].Name))
	idToken, claims, err := auth.Authenticate(cfg.ProviderType, cfg.ProviderDomain, cfg.ClientID, redirectURI, redirectPort, debug)
	if err != nil {
		debugPrint(debug, fmt.Sprintf("Error during monitoring authentication: %v", err))
		return "", 1
	}

	// Get AWS credentials too (cache them)
	credMap, err := federation.GetAWSCredentials(cfg, idToken, claims, debug)
	if err != nil {
		debugPrint(debug, fmt.Sprintf("Warning: could not get AWS credentials: %v", err))
	} else {
		creds := &storage.Credentials{
			Version:        1,
			AccessKeyId:    fmt.Sprint(credMap["AccessKeyId"]),
			SecretAccessKey: fmt.Sprint(credMap["SecretAccessKey"]),
			SessionToken:   fmt.Sprint(credMap["SessionToken"]),
			Expiration:     fmt.Sprint(credMap["Expiration"]),
		}
		store.SaveCredentials(profile, creds)
	}

	// Save monitoring token
	exp := int64(0)
	if expVal, ok := claims["exp"]; ok {
		if expFloat, ok := expVal.(float64); ok {
			exp = int64(expFloat)
		}
	}
	email := ""
	if emailVal, ok := claims["email"]; ok {
		email = fmt.Sprint(emailVal)
	}
	monToken := &storage.MonitoringToken{
		Token:   idToken,
		Expires: exp,
		Email:   email,
		Profile: profile,
	}
	store.SaveMonitoringToken(profile, monToken)
	os.Setenv("CLAUDE_CODE_MONITORING_TOKEN", idToken)

	return idToken, 0
}

func shouldRecheckQuota(cfg *config.ProfileConfig, store storage.Store, profile string, debug bool) bool {
	interval := cfg.QuotaCheckInterval
	if interval == 0 {
		return true // Always check
	}

	ts, err := store.GetQuotaCheckTime(profile)
	if err != nil || ts == "" {
		return true // Never checked
	}

	lastCheck, err := time.Parse(time.RFC3339, ts)
	if err != nil {
		// Try alternate formats
		lastCheck, err = time.Parse("2006-01-02T15:04:05.999999999-07:00", ts)
		if err != nil {
			return true
		}
	}

	elapsed := time.Since(lastCheck).Minutes()
	debugPrint(debug, fmt.Sprintf("Quota check: %.1f min since last check, interval=%d min", elapsed, interval))
	return elapsed >= float64(interval)
}

func saveQuotaCheckTime(store storage.Store, profile string) {
	now := time.Now().UTC().Format(time.RFC3339)
	store.SaveQuotaCheckTime(profile, now)
}

func outputCredentials(creds *storage.Credentials) {
	data, _ := json.Marshal(creds)
	fmt.Println(string(data))
}

func handleAuthError(err error) int {
	errMsg := err.Error()

	if strings.Contains(strings.ToLower(errMsg), "timeout") {
		// Timeout errors are debug-only in Python
		return 1
	}

	fmt.Fprintf(os.Stderr, "Error: %s\n", errMsg)

	if strings.Contains(errMsg, "NotAuthorizedException") && strings.Contains(errMsg, "Token is not from a supported provider") {
		fmt.Fprintln(os.Stderr, "\nAuthentication failed: Token provider mismatch")
		fmt.Fprintln(os.Stderr, "Identity pool expects tokens from a specific provider configuration.")
		fmt.Fprintln(os.Stderr, "Please verify your Cognito Identity Pool is configured correctly.")
	} else if strings.Contains(errMsg, "cognito_user_pool_id is required") {
		fmt.Fprintln(os.Stderr, "\nConfiguration error: Missing Cognito User Pool ID")
		fmt.Fprintln(os.Stderr, "Please run 'poetry run ccwb init' to reconfigure.")
	}

	return 1
}

func jwtClaimsToMap(claims interface{}) map[string]interface{} {
	if m, ok := claims.(map[string]interface{}); ok {
		return m
	}
	// Try JSON round-trip
	data, err := json.Marshal(claims)
	if err != nil {
		return nil
	}
	var m map[string]interface{}
	json.Unmarshal(data, &m)
	return m
}

func debugPrint(debug bool, msg string) {
	if debug {
		fmt.Fprintf(os.Stderr, "Debug: %s\n", msg)
	}
}
