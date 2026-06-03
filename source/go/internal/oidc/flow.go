package oidc

import (
	"fmt"
	"net/url"
	"os"
	"strings"
	"time"

	"ccwb-go/internal/jwt"
	"ccwb-go/internal/provider"
	"github.com/pkg/browser"
)

// AuthResult holds the result of a successful OIDC authentication.
type AuthResult struct {
	IDToken     string
	TokenClaims jwt.Claims
}

// GenericEndpoints carries absolute endpoint URLs for Generic OIDC providers.
// Pass nil for named providers (Okta, Auth0, Azure, Cognito).
type GenericEndpoints struct {
	AuthorizeURL string
	TokenURL     string
}

// Authenticate performs the full OIDC authorization code flow with PKCE.
// oktaAuthServerID is the Okta Custom Authorization Server id for tenants
// whose CAS isn't named "default". Pass "" (or "default") for every other
// provider and for standard Okta deployments.
//
// confidential is optional Azure-AD confidential-client material (client_secret
// or certificate-signed client_assertion). Pass nil for public-client flows --
// Okta, Auth0, Cognito, and Azure "public" mode all use the PKCE-only path.
//
// generic carries absolute endpoint URLs for Generic OIDC providers (CyberArk,
// PingFederate, Keycloak, ForgeRock, etc.). Pass nil for named providers.
func Authenticate(providerDomain, clientID, providerType, oktaAuthServerID string, redirectPort int, confidential *ConfidentialAuth, generic *GenericEndpoints) (*AuthResult, error) {
	provCfg := provider.ConfigFor(providerType, oktaAuthServerID)
	if provCfg.Name == "" {
		return nil, fmt.Errorf("unknown provider type: %s", providerType)
	}

	// Generate PKCE, state, nonce
	state, err := GenerateState()
	if err != nil {
		return nil, fmt.Errorf("generating state: %w", err)
	}
	nonce, err := GenerateNonce()
	if err != nil {
		return nil, fmt.Errorf("generating nonce: %w", err)
	}
	pkce, err := GeneratePKCE()
	if err != nil {
		return nil, fmt.Errorf("generating PKCE: %w", err)
	}

	redirectURI := fmt.Sprintf("http://localhost:%d/callback", redirectPort)

	// Build authorization URL
	params := url.Values{
		"client_id":             {clientID},
		"response_type":        {provCfg.ResponseType},
		"scope":                {provCfg.Scopes},
		"redirect_uri":         {redirectURI},
		"state":                {state},
		"nonce":                {nonce},
		"code_challenge_method": {"S256"},
		"code_challenge":       {pkce.CodeChallenge},
	}
	if providerType == "azure" {
		params.Set("response_mode", "query")
		params.Set("prompt", "select_account")
	}

	var authURL, tokenURL string
	if generic != nil && providerType == "generic" {
		authURL = generic.AuthorizeURL + "?" + params.Encode()
		tokenURL = generic.TokenURL
	} else {
		domain := providerDomain
		if providerType == "azure" && strings.HasSuffix(domain, "/v2.0") {
			domain = domain[:len(domain)-5]
		}
		baseURL := "https://" + domain
		authURL = baseURL + provCfg.AuthorizeEndpoint + "?" + params.Encode()
		tokenURL = baseURL + provCfg.TokenEndpoint
	}

	// Start callback server
	resultCh, srv, err := StartCallbackServer(redirectPort, state)
	if err != nil {
		return nil, fmt.Errorf("starting callback server: %w", err)
	}

	// Open browser
	if err := browser.OpenURL(authURL); err != nil {
		fmt.Fprintf(os.Stderr, "Could not open browser. Visit: %s\n", authURL)
	}

	// Wait for callback (5 min timeout)
	result, err := WaitForCallback(resultCh, srv, 300*time.Second)
	if err != nil {
		return nil, err
	}
	if result.Error != "" {
		return nil, fmt.Errorf("authentication error: %s", result.Error)
	}

	// Exchange code for tokens
	tokenResp, err := ExchangeCode(tokenURL, result.Code, redirectURI, clientID, pkce.CodeVerifier, confidential)
	if err != nil {
		return nil, err
	}

	// Decode ID token
	claims, err := jwt.DecodePayload(tokenResp.IDToken)
	if err != nil {
		return nil, fmt.Errorf("decoding ID token: %w", err)
	}

	// Validate nonce if present
	if claimNonce := claims.GetString("nonce"); claimNonce != "" && claimNonce != nonce {
		return nil, fmt.Errorf("invalid nonce in ID token")
	}

	return &AuthResult{
		IDToken:     tokenResp.IDToken,
		TokenClaims: claims,
	}, nil
}
