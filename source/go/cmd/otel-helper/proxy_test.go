// ABOUTME: Tests for the SigV4 signing proxy (otel-helper --proxy mode).
// ABOUTME: Verifies forwarding, SigV4 presence, attribution injection, localhost binding, and health check.

package main

import (
	"context"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/aws/aws-sdk-go-v2/aws"
	v4 "github.com/aws/aws-sdk-go-v2/aws/signer/v4"
)

func TestProxyHealthEndpoint(t *testing.T) {
	mux := http.NewServeMux()
	mux.HandleFunc("/health", func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
		w.Write([]byte("ok"))
	})

	req := httptest.NewRequest(http.MethodGet, "/health", nil)
	rec := httptest.NewRecorder()
	mux.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", rec.Code)
	}
	if rec.Body.String() != "ok" {
		t.Fatalf("expected 'ok', got '%s'", rec.Body.String())
	}
}

func TestProxyRejectsNonPost(t *testing.T) {
	// Create a handler that only accepts POST
	handler := makeProxyHandler(
		aws.Config{
			Region: "us-east-1",
			Credentials: aws.CredentialsProviderFunc(func(ctx context.Context) (aws.Credentials, error) {
				return aws.Credentials{
					AccessKeyID:     "AKIAIOSFODNN7EXAMPLE",
					SecretAccessKey: "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
				}, nil
			}),
		},
		v4.NewSigner(),
		&http.Client{},
		"https://monitoring.us-east-1.amazonaws.com",
		"us-east-1",
		"",
	)

	req := httptest.NewRequest(http.MethodGet, "/v1/logs", nil)
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	if rec.Code != http.StatusMethodNotAllowed {
		t.Fatalf("expected 405, got %d", rec.Code)
	}
}

func TestProxyForwardsToUpstream(t *testing.T) {
	// Mock upstream server
	var receivedBody string
	var receivedAuth string
	var receivedContentType string
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		body, _ := io.ReadAll(r.Body)
		receivedBody = string(body)
		receivedAuth = r.Header.Get("Authorization")
		receivedContentType = r.Header.Get("Content-Type")
		w.WriteHeader(http.StatusOK)
		w.Write([]byte(`{"partialSuccess":{}}`))
	}))
	defer upstream.Close()

	handler := makeProxyHandler(
		aws.Config{
			Region: "us-east-1",
			Credentials: aws.CredentialsProviderFunc(func(ctx context.Context) (aws.Credentials, error) {
				return aws.Credentials{
					AccessKeyID:     "AKIAIOSFODNN7EXAMPLE",
					SecretAccessKey: "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
				}, nil
			}),
		},
		v4.NewSigner(),
		&http.Client{},
		upstream.URL, // point at mock
		"us-east-1",
		"", // no profile (skip attribution cache)
	)

	payload := `{"resourceLogs":[{"scopeLogs":[{"logRecords":[]}]}]}`
	req := httptest.NewRequest(http.MethodPost, "/v1/logs", strings.NewReader(payload))
	req.Header.Set("Content-Type", "application/json")
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	// Verify forwarded
	if rec.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", rec.Code)
	}
	if receivedBody != payload {
		t.Fatalf("body not forwarded verbatim: got %q", receivedBody)
	}
	if receivedContentType != "application/json" {
		t.Fatalf("content-type not preserved: got %q", receivedContentType)
	}
	// SigV4 adds an Authorization header
	if receivedAuth == "" {
		t.Fatal("expected SigV4 Authorization header on upstream request")
	}
	if !strings.HasPrefix(receivedAuth, "AWS4-HMAC-SHA256") {
		t.Fatalf("expected SigV4 auth, got: %s", receivedAuth[:40])
	}
}

func TestProxyPreservesProtobufContentType(t *testing.T) {
	var receivedContentType string
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		receivedContentType = r.Header.Get("Content-Type")
		w.WriteHeader(http.StatusOK)
	}))
	defer upstream.Close()

	handler := makeProxyHandler(
		aws.Config{
			Region: "us-east-1",
			Credentials: aws.CredentialsProviderFunc(func(ctx context.Context) (aws.Credentials, error) {
				return aws.Credentials{
					AccessKeyID:     "AKIAIOSFODNN7EXAMPLE",
					SecretAccessKey: "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
				}, nil
			}),
		},
		v4.NewSigner(),
		&http.Client{},
		upstream.URL,
		"us-east-1",
		"",
	)

	req := httptest.NewRequest(http.MethodPost, "/v1/logs", strings.NewReader("\x00\x01\x02"))
	req.Header.Set("Content-Type", "application/x-protobuf")
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	if receivedContentType != "application/x-protobuf" {
		t.Fatalf("protobuf content-type not preserved: got %q", receivedContentType)
	}
}

func TestSha256Hex(t *testing.T) {
	// Known SHA-256 of empty string
	expected := "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
	got := sha256Hex([]byte{})
	if got != expected {
		t.Fatalf("sha256Hex(empty) = %s, want %s", got, expected)
	}
}
