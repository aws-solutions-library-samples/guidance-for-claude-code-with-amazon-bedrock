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
type GenericEndpoints struct {
	AuthorizeURL string
	TokenURL     string
}

// AuthOptions holds all parameters for the OIDC authentication flow.
// Use this struct to pass configuration without positional parameter coupling.
type AuthOptions struct {
	// ProviderDomain is the OIDC provider's domain (e.g., "mycompany.okta.com").
	ProviderDomain string
	// ClientID is the OAuth 2.0 client identifier.
	ClientID string
	// ProviderType identifies the IdP: "okta", "auth0", "azure", "cognito", "google", "generic".
	ProviderType string
	// OktaAuthServerID is the Okta Custom Authorization Server id. Pass "" for default.
	OktaAuthServerID string
	// RedirectPort is the local port for the OAuth callback (default 8400).
	RedirectPort int
	// Confidential holds Azure-AD confidential-client material. Nil for public-client flows.
	Confidential *ConfidentialAuth
	// Generic holds absolute endpoint URLs for Generic OIDC providers. Nil for named providers.
	Generic *GenericEndpoints
}

// Authenticate performs the full OIDC authorization code flow with PKCE.
// Accepts an AuthOptions struct for extensibility — new provider features can
// be added without changing the function signature.
func Authenticate(opts AuthOptions) (*AuthResult, error) {
	provCfg := provider.ConfigFor(opts.ProviderType, opts.OktaAuthServerID)
	if provCfg.Name == "" {
		return nil, fmt.Errorf("unknown provider type: %s", opts.ProviderType)
	}
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

	redirectURI := fmt.Sprintf("http://localhost:%d/callback", opts.RedirectPort)

	// Build authorization URL
	params := url.Values{
		"client_id":             {opts.ClientID},
		"response_type":        {provCfg.ResponseType},
		"scope":                {provCfg.Scopes},
		"redirect_uri":         {redirectURI},
		"state":                {state},
		"nonce":                {nonce},
		"code_challenge_method": {"S256"},
		"code_challenge":       {pkce.CodeChallenge},
	}
	if opts.ProviderType == "azure" {
		params.Set("response_mode", "query")
		params.Set("prompt", "select_account")
	}

	var authURL, tokenURL string
	if opts.Generic != nil && opts.ProviderType == "generic" {
		authURL = opts.Generic.AuthorizeURL + "?" + params.Encode()
		tokenURL = opts.Generic.TokenURL
	} else {
		domain := opts.ProviderDomain
		if opts.ProviderType == "azure" && strings.HasSuffix(domain, "/v2.0") {
			domain = domain[:len(domain)-5]
		}
		baseURL := "https://" + domain
		authURL = baseURL + provCfg.AuthorizeEndpoint + "?" + params.Encode()
		tokenURL = baseURL + provCfg.TokenEndpoint
	}

	// Start callback server
	resultCh, srv, err := StartCallbackServer(opts.RedirectPort, state)
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
	tokenResp, err := ExchangeCode(tokenURL, result.Code, redirectURI, opts.ClientID, pkce.CodeVerifier, opts.Confidential)
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
