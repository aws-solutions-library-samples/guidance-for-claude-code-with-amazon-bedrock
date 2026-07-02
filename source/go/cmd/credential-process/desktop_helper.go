package main

// ABOUTME: Desktop credential helper mode (--desktop flag).
// ABOUTME: Outputs a Bedrock bearer token for Claude Desktop's inferenceCredentialHelper.
// ABOUTME: Respects CLAUDE_HELPER_CONTEXT for interactive vs silent refresh behavior.

import (
	"encoding/json"
	"fmt"
	"os"

	"ccwb-go/internal/storage"
)

// runDesktopHelper implements the --desktop flag: outputs a Bedrock bearer token
// suitable for Claude Desktop's inferenceCredentialHelper.
//
// Flow:
//  1. Check CLAUDE_HELPER_CONTEXT to determine if interactive auth is allowed
//  2. Get or refresh AWS credentials (same logic as normal run)
//  3. Generate a Bedrock bearer token from the AWS credentials
//  4. Output {"token": "bedrock-api-key-...", "headers": {}} to stdout
//
// Exit codes:
//   - 0: success, token printed to stdout
//   - 1: failure (no valid credentials, silent refresh failed)
func (a *credentialApp) runDesktopHelper() int {
	helperContext := os.Getenv("CLAUDE_HELPER_CONTEXT")
	debugPrint("Desktop helper mode: CLAUDE_HELPER_CONTEXT=%s", helperContext)

	// Determine if we can open a browser
	allowInteractive := helperContext == "" || helperContext == "interactive"

	// Try cached credentials first
	creds := a.getCachedCredentials()

	if creds == nil {
		// No cached creds — try silent refresh
		if a.cfg.IsSsoEnabled() && !a.cfg.IsIDC() {
			// OIDC: try refresh token
			creds = a.tryRefreshToken()
		}

		if creds == nil && allowInteractive {
			// Interactive allowed — run full auth flow
			debugPrint("No cached credentials, running interactive auth")
			exitCode := a.run()
			if exitCode != 0 {
				return exitCode
			}
			// After successful auth, read the credentials
			creds = a.getCachedCredentials()
		}

		if creds == nil {
			fmt.Fprintf(os.Stderr, "Error: no valid credentials for profile '%s'. ", a.profile)
			if !allowInteractive {
				fmt.Fprintf(os.Stderr, "Silent refresh failed (CLAUDE_HELPER_CONTEXT=%s). Re-open Claude Desktop to trigger interactive sign-in.\n", helperContext)
			} else {
				fmt.Fprintf(os.Stderr, "Authentication failed.\n")
			}
			return 1
		}
	}

	// Check if credentials are expired
	remaining := storage.ParseExpirationSeconds(creds.Expiration)
	if remaining <= 30 {
		// Expired — try refresh
		if a.cfg.IsSsoEnabled() && !a.cfg.IsIDC() {
			creds = a.tryRefreshToken()
		}
		if creds == nil || storage.ParseExpirationSeconds(creds.Expiration) <= 30 {
			if allowInteractive {
				exitCode := a.run()
				if exitCode != 0 {
					return exitCode
				}
				creds = a.getCachedCredentials()
			}
			if creds == nil || storage.ParseExpirationSeconds(creds.Expiration) <= 30 {
				fmt.Fprintf(os.Stderr, "Error: credentials expired for profile '%s' and refresh failed.\n", a.profile)
				return 1
			}
		}
	}

	// Generate Bedrock bearer token from AWS credentials
	region := a.cfg.AWSRegion
	if region == "" {
		region = "us-east-1"
	}

	token, err := generateBedrockToken(creds.AccessKeyID, creds.SecretAccessKey, creds.SessionToken, region)
	if err != nil {
		fmt.Fprintf(os.Stderr, "Error generating Bedrock token: %v\n", err)
		return 1
	}

	// Output in the format Claude Desktop expects
	output := map[string]interface{}{
		"token":   token,
		"headers": map[string]string{},
	}

	data, _ := json.Marshal(output)
	fmt.Println(string(data))
	return 0
}
