package oidc

import (
	"fmt"
	"net/url"
	"os"
	"time"

	"ccwb-go/internal/browser"
	"ccwb-go/internal/jwt"
	"ccwb-go/internal/provider"
)

// AuthResult holds the result of a successful OIDC authentication.
type AuthResult struct {
	IDToken      string
	RefreshToken string
	TokenClaims  jwt.Claims
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
func Authenticate(providerDomain, clientID, providerType, oktaAuthServerID string, redirectPort int, confidential *ConfidentialAuth, generic *GenericEndpoints, oidcPrompt *string) (*AuthResult, error) {
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
		prompt := "select_account"
		if oidcPrompt != nil {
			prompt = *oidcPrompt
		}
		if prompt != "" {
			params.Set("prompt", prompt)
		}
	}

	var authURL, tokenURL string
	if generic != nil && providerType == "generic" {
		authURL = generic.AuthorizeURL + "?" + params.Encode()
		tokenURL = generic.TokenURL
	} else {
		// Normalize once (e.g. strip Azure's trailing /v2.0) so the authorize
		// and token URLs are built from the same base. TokenEndpointURL applies
		// the identical normalization, keeping this flow and the refresh_token
		// exchange in lockstep.
		baseURL := "https://" + provider.NormalizeDomain(providerType, providerDomain)
		authURL = baseURL + provCfg.AuthorizeEndpoint + "?" + params.Encode()
		tokenURL = provider.TokenEndpointURL(providerType, oktaAuthServerID, providerDomain)
	}

	// Start callback server (serves landing page + handles /callback)
	resultCh, srv, err := StartCallbackServer(redirectPort, state, authURL)
	if err != nil {
		return nil, fmt.Errorf("starting callback server: %w", err)
	}

	// Open browser to the local landing page, which explains what's happening
	// and provides a button to proceed to the IdP. This gives CoWork (GUI) users
	// context about why a browser window appeared.
	landingURL := fmt.Sprintf("http://localhost:%d/", redirectPort)
	if err := browser.OpenURL(landingURL); err != nil {
		// Fallback: try opening the IdP directly
		if err2 := browser.OpenURL(authURL); err2 != nil {
			fmt.Fprintf(os.Stderr, "Could not open browser. Visit: %s\n", landingURL)
		}
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
		IDToken:      tokenResp.IDToken,
		RefreshToken: tokenResp.RefreshToken,
		TokenClaims:  claims,
	}, nil
}
