package main

// ABOUTME: Unit tests for doIDCRefresh() — the SSO token refresh path
// ABOUTME: Covers valid refresh, expired refresh token, and network errors

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"testing"
	"time"

	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/service/ssooidc"
)

// TestDoIDCRefresh_ValidRefreshToken tests the happy path: the cached token has
// a valid refresh_token, and the OIDC server exchanges it for a new access
// token. The SDK's SSOTokenProvider reads the cache file, sees it's expired,
// calls CreateToken with the refresh_token grant, and writes back the new token.
func TestDoIDCRefresh_ValidRefreshToken(t *testing.T) {
	// Set up fake OIDC server that accepts refresh_token grant.
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		// The SDK's SSOTokenProvider calls CreateToken with grant_type=refresh_token.
		w.Header().Set("Content-Type", "application/json")
		newExpiry := time.Now().Add(8 * time.Hour).Unix()
		json.NewEncoder(w).Encode(map[string]interface{}{
			"accessToken":  "new-access-token",
			"tokenType":    "Bearer",
			"expiresIn":    int(newExpiry - time.Now().Unix()),
			"refreshToken": "new-refresh-token",
		})
	}))
	defer server.Close()

	client := ssooidc.New(ssooidc.Options{
		Region:       "us-east-1",
		BaseEndpoint: aws.String(server.URL),
		HTTPClient:   server.Client(),
	})

	// Write an expired but refreshable token to a temp file.
	dir := t.TempDir()
	tokenPath := filepath.Join(dir, "sso", "cache", "token.json")
	if err := os.MkdirAll(filepath.Dir(tokenPath), 0o700); err != nil {
		t.Fatal(err)
	}
	expired := ssoCachedToken{
		AccessToken:  "old-expired-token",
		ExpiresAt:    time.Now().Add(-1 * time.Hour).UTC().Format(time.RFC3339),
		RefreshToken: "valid-refresh-token",
		ClientID:     "client-id",
		ClientSecret: "client-secret",
		StartURL:     "https://d-1234567890.awsapps.com/start",
	}
	data, _ := json.Marshal(expired)
	if err := os.WriteFile(tokenPath, data, 0o600); err != nil {
		t.Fatal(err)
	}

	app := &credentialApp{profile: "idc-test"}
	err := app.doIDCRefresh(context.Background(), client, tokenPath)
	if err != nil {
		t.Fatalf("expected successful refresh, got error: %v", err)
	}
}

// TestDoIDCRefresh_ExpiredRefreshToken tests the case where the refresh token
// itself has expired or been revoked. The OIDC server returns an error,
// indicating a fresh device-authorization flow is needed.
func TestDoIDCRefresh_ExpiredRefreshToken(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		// Simulate expired/invalid refresh token.
		w.WriteHeader(400)
		json.NewEncoder(w).Encode(map[string]interface{}{
			"__type":  "InvalidGrantException",
			"error":   "invalid_grant",
			"message": "Refresh token has expired",
		})
	}))
	defer server.Close()

	client := ssooidc.New(ssooidc.Options{
		Region:       "us-east-1",
		BaseEndpoint: aws.String(server.URL),
		HTTPClient:   server.Client(),
	})

	dir := t.TempDir()
	tokenPath := filepath.Join(dir, "sso", "cache", "token.json")
	if err := os.MkdirAll(filepath.Dir(tokenPath), 0o700); err != nil {
		t.Fatal(err)
	}
	expired := ssoCachedToken{
		AccessToken:  "old-token",
		ExpiresAt:    time.Now().Add(-1 * time.Hour).UTC().Format(time.RFC3339),
		RefreshToken: "expired-refresh-token",
		ClientID:     "client-id",
		ClientSecret: "client-secret",
		StartURL:     "https://d-1234567890.awsapps.com/start",
	}
	data, _ := json.Marshal(expired)
	if err := os.WriteFile(tokenPath, data, 0o600); err != nil {
		t.Fatal(err)
	}

	app := &credentialApp{profile: "idc-test"}
	err := app.doIDCRefresh(context.Background(), client, tokenPath)
	if err == nil {
		t.Fatal("expected error for expired refresh token, got nil")
	}
}

// TestDoIDCRefresh_NetworkError tests the case where the OIDC endpoint is
// unreachable. This simulates network failures during refresh.
func TestDoIDCRefresh_NetworkError(t *testing.T) {
	// Create a server and immediately close it to simulate network failure.
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {}))
	serverURL := server.URL
	server.Close() // close immediately — all connections will fail

	client := ssooidc.New(ssooidc.Options{
		Region:       "us-east-1",
		BaseEndpoint: aws.String(serverURL),
	})

	dir := t.TempDir()
	tokenPath := filepath.Join(dir, "sso", "cache", "token.json")
	if err := os.MkdirAll(filepath.Dir(tokenPath), 0o700); err != nil {
		t.Fatal(err)
	}
	expired := ssoCachedToken{
		AccessToken:  "old-token",
		ExpiresAt:    time.Now().Add(-1 * time.Hour).UTC().Format(time.RFC3339),
		RefreshToken: "refresh-token",
		ClientID:     "client-id",
		ClientSecret: "client-secret",
		StartURL:     "https://d-1234567890.awsapps.com/start",
	}
	data, _ := json.Marshal(expired)
	if err := os.WriteFile(tokenPath, data, 0o600); err != nil {
		t.Fatal(err)
	}

	app := &credentialApp{profile: "idc-test"}
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	err := app.doIDCRefresh(ctx, client, tokenPath)
	if err == nil {
		t.Fatal("expected error for network failure, got nil")
	}
}
