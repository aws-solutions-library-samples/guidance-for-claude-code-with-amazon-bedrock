package auth

import (
	"context"
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"strings"
	"time"

	"github.com/golang-jwt/jwt/v5"
	"github.com/pkg/browser"
)

// ProviderConfig defines the OIDC endpoints and scopes for an identity provider.
type ProviderConfig struct {
	Name          string
	AuthorizePath string
	TokenPath     string
	Scopes        string
}

// ProviderConfigs contains the supported OIDC provider configurations.
var ProviderConfigs = map[string]ProviderConfig{
	"okta":    {Name: "Okta", AuthorizePath: "/oauth2/v1/authorize", TokenPath: "/oauth2/v1/token", Scopes: "openid profile email"},
	"auth0":   {Name: "Auth0", AuthorizePath: "/authorize", TokenPath: "/oauth/token", Scopes: "openid profile email"},
	"azure":   {Name: "Azure AD", AuthorizePath: "/oauth2/v2.0/authorize", TokenPath: "/oauth2/v2.0/token", Scopes: "openid profile email"},
	"cognito": {Name: "AWS Cognito User Pool", AuthorizePath: "/oauth2/authorize", TokenPath: "/oauth2/token", Scopes: "openid email"},
}

// generateRandomBase64URL generates n random bytes and returns them as base64url-encoded
// string without padding.
func generateRandomBase64URL(n int) (string, error) {
	b := make([]byte, n)
	if _, err := rand.Read(b); err != nil {
		return "", fmt.Errorf("failed to generate random bytes: %w", err)
	}
	return base64.RawURLEncoding.EncodeToString(b), nil
}

// generatePKCE generates the PKCE code_verifier and code_challenge.
func generatePKCE() (verifier, challenge string, err error) {
	verifier, err = generateRandomBase64URL(32)
	if err != nil {
		return "", "", err
	}
	hash := sha256.Sum256([]byte(verifier))
	challenge = base64.RawURLEncoding.EncodeToString(hash[:])
	return verifier, challenge, nil
}

func debugLog(debug bool, format string, args ...interface{}) {
	if debug {
		fmt.Fprintf(os.Stderr, "Debug: "+format+"\n", args...)
	}
}

// Authenticate performs the OIDC authorization code flow with PKCE.
func Authenticate(providerType, providerDomain, clientID, redirectURI string, redirectPort int, debug bool) (idToken string, claims jwt.MapClaims, err error) {
	config, ok := ProviderConfigs[providerType]
	if !ok {
		return "", nil, fmt.Errorf("unsupported provider type: %s", providerType)
	}

	debugLog(debug, "Using provider: %s (%s)", config.Name, providerType)

	// Validate cognito domain
	if providerType == "cognito" {
		if !strings.Contains(providerDomain, "amazoncognito.com") {
			return "", nil, fmt.Errorf("cognito provider_domain must contain 'amazoncognito.com', got: %s", providerDomain)
		}
	}

	// Generate PKCE parameters
	verifier, challenge, err := generatePKCE()
	if err != nil {
		return "", nil, fmt.Errorf("failed to generate PKCE: %w", err)
	}

	state, err := generateRandomBase64URL(16)
	if err != nil {
		return "", nil, fmt.Errorf("failed to generate state: %w", err)
	}

	nonce, err := generateRandomBase64URL(16)
	if err != nil {
		return "", nil, fmt.Errorf("failed to generate nonce: %w", err)
	}

	debugLog(debug, "Generated PKCE verifier and challenge")

	// Build authorization URL
	domain := providerDomain
	if providerType == "azure" {
		domain = strings.TrimSuffix(domain, "/v2.0")
	}

	authURL, err := url.Parse(fmt.Sprintf("https://%s%s", domain, config.AuthorizePath))
	if err != nil {
		return "", nil, fmt.Errorf("failed to parse auth URL: %w", err)
	}

	params := url.Values{
		"client_id":             {clientID},
		"response_type":        {"code"},
		"scope":                {config.Scopes},
		"redirect_uri":         {redirectURI},
		"state":                {state},
		"nonce":                {nonce},
		"code_challenge_method": {"S256"},
		"code_challenge":       {challenge},
	}

	if providerType == "azure" {
		params.Set("response_mode", "query")
		params.Set("prompt", "select_account")
	}

	authURL.RawQuery = params.Encode()

	debugLog(debug, "Authorization URL: %s", authURL.String())

	// Start callback server
	resultCh, server := startCallbackServer(redirectPort, state)
	defer func() {
		ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		server.Shutdown(ctx)
	}()

	// Open browser
	debugLog(debug, "Opening browser for authentication")
	if err := browser.OpenURL(authURL.String()); err != nil {
		return "", nil, fmt.Errorf("failed to open browser: %w", err)
	}

	// Wait for callback
	debugLog(debug, "Waiting for callback (timeout: 300s)")
	select {
	case result := <-resultCh:
		if result.Error != "" {
			return "", nil, fmt.Errorf("authentication failed: %s", result.Error)
		}
		debugLog(debug, "Received authorization code")

		// Exchange code for token
		idToken, claims, err = exchangeCodeForToken(config, providerDomain, clientID, redirectURI, result.Code, verifier, nonce, debug)
		if err != nil {
			return "", nil, err
		}
		return idToken, claims, nil

	case <-time.After(300 * time.Second):
		return "", nil, fmt.Errorf("authentication timed out after 300 seconds")
	}
}

// exchangeCodeForToken exchanges the authorization code for tokens.
func exchangeCodeForToken(config ProviderConfig, providerDomain, clientID, redirectURI, code, verifier, nonce string, debug bool) (string, jwt.MapClaims, error) {
	tokenURL := fmt.Sprintf("https://%s%s", providerDomain, config.TokenPath)

	data := url.Values{
		"grant_type":    {"authorization_code"},
		"code":          {code},
		"redirect_uri":  {redirectURI},
		"client_id":     {clientID},
		"code_verifier": {verifier},
	}

	debugLog(debug, "Exchanging code for token at: %s", tokenURL)

	client := &http.Client{Timeout: 30 * time.Second}
	resp, err := client.Post(tokenURL, "application/x-www-form-urlencoded", strings.NewReader(data.Encode()))
	if err != nil {
		return "", nil, fmt.Errorf("token exchange request failed: %w", err)
	}
	defer resp.Body.Close()

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return "", nil, fmt.Errorf("failed to read token response: %w", err)
	}

	if resp.StatusCode != http.StatusOK {
		return "", nil, fmt.Errorf("token exchange failed (status %d): %s", resp.StatusCode, string(body))
	}

	var tokenResp struct {
		IDToken string `json:"id_token"`
	}
	if err := json.Unmarshal(body, &tokenResp); err != nil {
		return "", nil, fmt.Errorf("failed to parse token response: %w", err)
	}

	if tokenResp.IDToken == "" {
		return "", nil, fmt.Errorf("no id_token in token response")
	}

	debugLog(debug, "Received id_token, decoding claims")

	// Decode JWT without verification
	parser := jwt.NewParser(
		jwt.WithoutClaimsValidation(),
	)

	claims := jwt.MapClaims{}
	_, _, err = parser.ParseUnverified(tokenResp.IDToken, claims)
	if err != nil {
		return "", nil, fmt.Errorf("failed to decode id_token: %w", err)
	}

	// Validate nonce if present
	if nonceVal, ok := claims["nonce"]; ok {
		if nonceStr, ok := nonceVal.(string); ok && nonceStr != nonce {
			return "", nil, fmt.Errorf("nonce mismatch: expected %s, got %s", nonce, nonceStr)
		}
	}

	debugLog(debug, "Token claims decoded successfully")

	return tokenResp.IDToken, claims, nil
}
