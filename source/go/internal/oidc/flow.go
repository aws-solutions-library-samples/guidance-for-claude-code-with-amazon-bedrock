package oidc

import (
	"fmt"
	"net/url"
	"os"
	"strings"
	"time"

	"github.com/bluedoors/ccwb-binaries/internal/jwt"
	"github.com/bluedoors/ccwb-binaries/internal/provider"
	"github.com/pkg/browser"
)

// AuthResult holds the result of a successful OIDC authentication.
type AuthResult struct {
	IDToken     string
	TokenClaims jwt.Claims
}

// AuthOptions configures the OIDC authentication flow.
type AuthOptions struct {
	ProviderDomain string
	ClientID       string
	ProviderType   string
	RedirectPort   int
	// Confidential client (optional)
	ConfidentialClient *ConfidentialClientOpts
}

// Authenticate performs the full OIDC authorization code flow with PKCE.
func Authenticate(providerDomain, clientID, providerType string, redirectPort int) (*AuthResult, error) {
	return AuthenticateWithOpts(&AuthOptions{
		ProviderDomain: providerDomain,
		ClientID:       clientID,
		ProviderType:   providerType,
		RedirectPort:   redirectPort,
	})
}

// AuthenticateWithOpts performs the OIDC flow with full options including confidential client support.
func AuthenticateWithOpts(opts *AuthOptions) (*AuthResult, error) {
	provCfg, ok := provider.Configs[opts.ProviderType]
	if !ok {
		return nil, fmt.Errorf("unknown provider type: %s", opts.ProviderType)
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

	// Build base URL
	domain := opts.ProviderDomain
	if opts.ProviderType == "azure" && strings.HasSuffix(domain, "/v2.0") {
		domain = domain[:len(domain)-5]
	}
	baseURL := "https://" + domain

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
	authURL := baseURL + provCfg.AuthorizeEndpoint + "?" + params.Encode()

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
	tokenURL := baseURL + provCfg.TokenEndpoint
	tokenResp, err := ExchangeCodeWithOpts(tokenURL, result.Code, redirectURI, opts.ClientID, pkce.CodeVerifier, opts.ConfidentialClient)
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
