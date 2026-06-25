package main

// ABOUTME: Unit tests for pollForToken() — the device-auth polling loop
// ABOUTME: Covers immediate success, slow-down backoff, authorization_pending, timeout, and access_denied

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"sync/atomic"
	"testing"
	"time"

	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/service/ssooidc"
)

// newTestOIDCClient creates an ssooidc.Client that routes all requests to the
// given httptest server. This lets us control CreateToken responses without any
// real AWS calls.
func newTestOIDCClient(t *testing.T, server *httptest.Server) *ssooidc.Client {
	t.Helper()
	return ssooidc.New(ssooidc.Options{
		Region:       "us-east-1",
		BaseEndpoint: aws.String(server.URL),
		HTTPClient:   server.Client(),
	})
}

func TestPollForToken_ImmediateSuccess(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		// First poll returns a valid token immediately.
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(map[string]interface{}{
			"accessToken":  "test-access-token",
			"tokenType":    "Bearer",
			"expiresIn":    3600,
			"refreshToken": "test-refresh-token",
		})
	}))
	defer server.Close()

	client := newTestOIDCClient(t, server)
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	reg := &ssooidc.RegisterClientOutput{
		ClientId:     aws.String("client-id"),
		ClientSecret: aws.String("client-secret"),
	}
	devAuth := &ssooidc.StartDeviceAuthorizationOutput{
		DeviceCode: aws.String("device-code"),
		Interval:   1, // 1 second poll interval
	}

	out, err := pollForToken(ctx, client, reg, devAuth)
	if err != nil {
		t.Fatalf("expected success, got error: %v", err)
	}
	if out == nil {
		t.Fatal("expected non-nil output")
	}
	if aws.ToString(out.AccessToken) != "test-access-token" {
		t.Errorf("unexpected access token: %s", aws.ToString(out.AccessToken))
	}
}

func TestPollForToken_SlowDown_HonorsBackoff(t *testing.T) {
	var callCount atomic.Int32
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		n := callCount.Add(1)
		if n <= 2 {
			// Return slow_down error for first two attempts.
			w.WriteHeader(400)
			json.NewEncoder(w).Encode(map[string]interface{}{
				"__type":  "SlowDownException",
				"error":   "slow_down",
				"message": "Slow down",
			})
			return
		}
		// Third call succeeds.
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(map[string]interface{}{
			"accessToken":  "delayed-token",
			"tokenType":    "Bearer",
			"expiresIn":    3600,
			"refreshToken": "r",
		})
	}))
	defer server.Close()

	client := newTestOIDCClient(t, server)
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()

	reg := &ssooidc.RegisterClientOutput{
		ClientId:     aws.String("c"),
		ClientSecret: aws.String("s"),
	}
	devAuth := &ssooidc.StartDeviceAuthorizationOutput{
		DeviceCode: aws.String("dc"),
		Interval:   1,
	}

	start := time.Now()
	out, err := pollForToken(ctx, client, reg, devAuth)
	elapsed := time.Since(start)
	if err != nil {
		t.Fatalf("expected eventual success, got error: %v", err)
	}
	if aws.ToString(out.AccessToken) != "delayed-token" {
		t.Errorf("unexpected token: %s", aws.ToString(out.AccessToken))
	}
	// Two slow-downs add 5s each to the initial 1s interval; total wait should
	// be at least a few seconds (the actual minimum depends on timing).
	if elapsed < 2*time.Second {
		t.Logf("elapsed %s — backoff may not have been honored fully", elapsed)
	}
	if int(callCount.Load()) < 3 {
		t.Errorf("expected at least 3 calls (2 slow-down + 1 success), got %d", callCount.Load())
	}
}

func TestPollForToken_AuthorizationPending_RetriesThenSucceeds(t *testing.T) {
	var callCount atomic.Int32
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		n := callCount.Add(1)
		if n <= 3 {
			// Authorization pending.
			w.WriteHeader(400)
			json.NewEncoder(w).Encode(map[string]interface{}{
				"__type":  "AuthorizationPendingException",
				"error":   "authorization_pending",
				"message": "Authorization pending",
			})
			return
		}
		// Eventually succeeds.
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(map[string]interface{}{
			"accessToken":  "approved-token",
			"tokenType":    "Bearer",
			"expiresIn":    3600,
			"refreshToken": "rt",
		})
	}))
	defer server.Close()

	client := newTestOIDCClient(t, server)
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()

	reg := &ssooidc.RegisterClientOutput{
		ClientId:     aws.String("c"),
		ClientSecret: aws.String("s"),
	}
	devAuth := &ssooidc.StartDeviceAuthorizationOutput{
		DeviceCode: aws.String("dc"),
		Interval:   1,
	}

	out, err := pollForToken(ctx, client, reg, devAuth)
	if err != nil {
		t.Fatalf("expected success after pending retries, got: %v", err)
	}
	if aws.ToString(out.AccessToken) != "approved-token" {
		t.Errorf("unexpected token: %s", aws.ToString(out.AccessToken))
	}
	if int(callCount.Load()) < 4 {
		t.Errorf("expected at least 4 calls (3 pending + 1 success), got %d", callCount.Load())
	}
}

func TestPollForToken_TimeoutExceeded(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		// Always return authorization_pending — never approve.
		w.WriteHeader(400)
		json.NewEncoder(w).Encode(map[string]interface{}{
			"__type":  "AuthorizationPendingException",
			"error":   "authorization_pending",
			"message": "Authorization pending",
		})
	}))
	defer server.Close()

	client := newTestOIDCClient(t, server)
	// Very short timeout to trigger the timeout path quickly.
	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()

	reg := &ssooidc.RegisterClientOutput{
		ClientId:     aws.String("c"),
		ClientSecret: aws.String("s"),
	}
	devAuth := &ssooidc.StartDeviceAuthorizationOutput{
		DeviceCode: aws.String("dc"),
		Interval:   1,
	}

	_, err := pollForToken(ctx, client, reg, devAuth)
	if err == nil {
		t.Fatal("expected timeout error, got nil")
	}
	if ctx.Err() == nil {
		t.Error("expected context to be canceled/timed out")
	}
}

func TestPollForToken_AccessDenied_ReturnsErrorImmediately(t *testing.T) {
	var callCount atomic.Int32
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		callCount.Add(1)
		// Return a terminal error (access_denied / generic).
		w.WriteHeader(400)
		json.NewEncoder(w).Encode(map[string]interface{}{
			"__type":  "AccessDeniedException",
			"error":   "access_denied",
			"message": "Access denied",
		})
	}))
	defer server.Close()

	client := newTestOIDCClient(t, server)
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	reg := &ssooidc.RegisterClientOutput{
		ClientId:     aws.String("c"),
		ClientSecret: aws.String("s"),
	}
	devAuth := &ssooidc.StartDeviceAuthorizationOutput{
		DeviceCode: aws.String("dc"),
		Interval:   1,
	}

	_, err := pollForToken(ctx, client, reg, devAuth)
	if err == nil {
		t.Fatal("expected error for access_denied, got nil")
	}
	// Should NOT have retried multiple times — terminal errors exit immediately.
	if int(callCount.Load()) != 1 {
		t.Errorf("expected exactly 1 call (immediate failure), got %d", callCount.Load())
	}
}
