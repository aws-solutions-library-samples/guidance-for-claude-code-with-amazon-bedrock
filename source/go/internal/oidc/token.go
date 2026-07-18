package oidc

import (
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strings"
	"time"
)

// RefreshExchangeError describes a failed refresh_token exchange.
//
// Definitive is true ONLY when the IdP explicitly rejected the refresh_token
// itself (OAuth 2.0 error "invalid_grant" / "invalid_token", RFC 6749 §5.2) —
// i.e. the token is revoked/expired and a full re-authentication is required, so
// the stored refresh_token should be discarded. For every other failure
// (network error, 5xx, timeout, empty/misconfigured token URL, unparseable
// body) Definitive is false and the caller MUST retain the refresh_token so a
// later cycle can retry. Clearing on a transient failure is what permanently
// disabled silent renewal until the next browser login (see the OTEL bearer
// undercount bug).
type RefreshExchangeError struct {
	Definitive bool   // true only for invalid_grant / invalid_token
	OAuthCode  string // parsed OAuth "error" field, if any
	StatusCode int    // HTTP status, if the request completed
	err        error  // underlying formatted error (preserves the old message)
}

func (e *RefreshExchangeError) Error() string { return e.err.Error() }

func (e *RefreshExchangeError) Unwrap() error { return e.err }

// IsDefinitiveRefreshFailure reports whether err from RefreshTokenExchange means
// the refresh_token itself was rejected (invalid_grant / invalid_token) and must
// be discarded. Any other error — including a nil error — is treated as transient
// (retain the token). Callers use this to decide whether to ClearRefreshToken.
func IsDefinitiveRefreshFailure(err error) bool {
	var re *RefreshExchangeError
	if errors.As(err, &re) {
		return re.Definitive
	}
	return false
}

// parseOAuthErrorCode extracts the OAuth 2.0 "error" field from a token-endpoint
// error body (e.g. {"error":"invalid_grant","error_description":"..."}). Returns
// "" when the body is empty or not the expected JSON shape.
func parseOAuthErrorCode(body []byte) string {
	var e struct {
		Error string `json:"error"`
	}
	if json.Unmarshal(body, &e) == nil {
		return e.Error
	}
	return ""
}

// TokenResponse holds the OIDC token endpoint response.
type TokenResponse struct {
	IDToken      string `json:"id_token"`
	AccessToken  string `json:"access_token"`
	RefreshToken string `json:"refresh_token"`
	TokenType    string `json:"token_type"`
	ExpiresIn    int    `json:"expires_in"`
}

// ExchangeCode exchanges an authorization code for tokens at the provider's token endpoint.
// Pass confidential = nil for public PKCE-only clients; Azure confidential-client callers
// construct a ConfidentialAuth to inject client_secret or a certificate-signed client_assertion.
func ExchangeCode(tokenURL, code, redirectURI, clientID, codeVerifier string, confidential *ConfidentialAuth) (*TokenResponse, error) {
	form := map[string]string{
		"grant_type":    "authorization_code",
		"code":          code,
		"redirect_uri":  redirectURI,
		"client_id":     clientID,
		"code_verifier": codeVerifier,
	}
	if err := confidential.apply(form, tokenURL, clientID); err != nil {
		return nil, err
	}
	data := url.Values{}
	for k, v := range form {
		data.Set(k, v)
	}

	client := &http.Client{Timeout: 30 * time.Second}
	resp, err := client.Post(tokenURL, "application/x-www-form-urlencoded", strings.NewReader(data.Encode()))
	if err != nil {
		return nil, fmt.Errorf("token request failed: %w", err)
	}
	defer resp.Body.Close()

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, fmt.Errorf("reading token response: %w", err)
	}

	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("token exchange failed (HTTP %d): %s", resp.StatusCode, string(body))
	}

	var tokenResp TokenResponse
	if err := json.Unmarshal(body, &tokenResp); err != nil {
		return nil, fmt.Errorf("parsing token response: %w", err)
	}

	return &tokenResp, nil
}

// RefreshTokenExchange exchanges a refresh_token for fresh tokens at the
// provider's token endpoint. Returns a new TokenResponse containing a fresh
// id_token (and possibly a rotated refresh_token). Falls back gracefully:
// callers should treat any error as "refresh unavailable, try browser auth."
func RefreshTokenExchange(tokenURL, refreshToken, clientID string, confidential *ConfidentialAuth) (*TokenResponse, error) {
	// Guard against an empty/relative token URL. This should never happen once
	// the provider type is resolved, but if it slips through (as it did on the
	// --get-monitoring-token path before the provider type was resolved) the POST
	// below would fail in a way that must NOT be mistaken for a revoked token —
	// so surface it as an explicit, transient error (Definitive=false).
	if !strings.HasPrefix(tokenURL, "https://") && !strings.HasPrefix(tokenURL, "http://") {
		return nil, &RefreshExchangeError{
			Definitive: false,
			err:        fmt.Errorf("refresh token exchange: invalid token endpoint URL %q (provider type not resolved?)", tokenURL),
		}
	}

	form := map[string]string{
		"grant_type":    "refresh_token",
		"refresh_token": refreshToken,
		"client_id":     clientID,
	}
	if err := confidential.apply(form, tokenURL, clientID); err != nil {
		// Failing to build the client assertion (missing cert, etc.) is a local
		// misconfiguration, not a revoked token — retain the refresh_token.
		return nil, &RefreshExchangeError{Definitive: false, err: err}
	}
	data := url.Values{}
	for k, v := range form {
		data.Set(k, v)
	}

	client := &http.Client{Timeout: 30 * time.Second}
	resp, err := client.Post(tokenURL, "application/x-www-form-urlencoded", strings.NewReader(data.Encode()))
	if err != nil {
		// Network/DNS/timeout — transient, retain the token.
		return nil, &RefreshExchangeError{Definitive: false, err: fmt.Errorf("refresh token request failed: %w", err)}
	}
	defer resp.Body.Close()

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, &RefreshExchangeError{Definitive: false, StatusCode: resp.StatusCode, err: fmt.Errorf("reading refresh response: %w", err)}
	}

	if resp.StatusCode != http.StatusOK {
		// Only invalid_grant / invalid_token mean the refresh_token is dead.
		// Everything else (5xx, throttling, unexpected 4xx) is treated as
		// transient so we don't discard a still-valid token on a server blip.
		oauthCode := parseOAuthErrorCode(body)
		definitive := oauthCode == "invalid_grant" || oauthCode == "invalid_token"
		return nil, &RefreshExchangeError{
			Definitive: definitive,
			OAuthCode:  oauthCode,
			StatusCode: resp.StatusCode,
			err:        fmt.Errorf("refresh token exchange failed (HTTP %d): %s", resp.StatusCode, string(body)),
		}
	}

	var tokenResp TokenResponse
	if err := json.Unmarshal(body, &tokenResp); err != nil {
		return nil, &RefreshExchangeError{Definitive: false, StatusCode: resp.StatusCode, err: fmt.Errorf("parsing refresh response: %w", err)}
	}

	return &tokenResp, nil
}
