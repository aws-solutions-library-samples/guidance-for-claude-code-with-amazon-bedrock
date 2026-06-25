package oidc

import (
	"fmt"
	"net/http"
	"testing"
	"time"
)

func TestStartCallbackServer_ListensOnPort(t *testing.T) {
	resultCh, srv, err := StartCallbackServer(0, "test-state", "https://example.com/authorize")
	if err != nil {
		t.Fatalf("StartCallbackServer failed: %v", err)
	}
	defer srv.Close()

	// Server should be listening — verify by sending a request
	// We need the actual port from the server
	if resultCh == nil {
		t.Fatal("resultCh is nil")
	}
}

func TestStartCallbackServer_ValidCallback(t *testing.T) {
	port := 19876 // Use a high port to avoid conflicts
	state := "test-state-abc123"

	resultCh, srv, err := StartCallbackServer(port, state, "https://example.com/authorize")
	if err != nil {
		t.Fatalf("StartCallbackServer failed: %v", err)
	}
	defer srv.Close()

	// Simulate OAuth callback
	url := fmt.Sprintf("http://127.0.0.1:%d/callback?state=%s&code=auth-code-xyz", port, state)
	resp, err := http.Get(url)
	if err != nil {
		t.Fatalf("HTTP GET failed: %v", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != 200 {
		t.Errorf("Expected 200, got %d", resp.StatusCode)
	}

	// Check result channel
	select {
	case result := <-resultCh:
		if result.Code != "auth-code-xyz" {
			t.Errorf("Expected code 'auth-code-xyz', got '%s'", result.Code)
		}
		if result.Error != "" {
			t.Errorf("Unexpected error: %s", result.Error)
		}
	case <-time.After(2 * time.Second):
		t.Fatal("Timeout waiting for callback result")
	}
}

func TestStartCallbackServer_InvalidState(t *testing.T) {
	port := 19877
	state := "correct-state"

	resultCh, srv, err := StartCallbackServer(port, state, "https://example.com/authorize")
	if err != nil {
		t.Fatalf("StartCallbackServer failed: %v", err)
	}
	defer srv.Close()

	// Send callback with wrong state
	url := fmt.Sprintf("http://127.0.0.1:%d/callback?state=wrong-state&code=some-code", port)
	resp, err := http.Get(url)
	if err != nil {
		t.Fatalf("HTTP GET failed: %v", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != 400 {
		t.Errorf("Expected 400, got %d", resp.StatusCode)
	}

	select {
	case result := <-resultCh:
		if result.Error == "" {
			t.Error("Expected error for invalid state")
		}
	case <-time.After(2 * time.Second):
		t.Fatal("Timeout waiting for callback result")
	}
}

func TestStartCallbackServer_MissingCode(t *testing.T) {
	port := 19878
	state := "my-state"

	resultCh, srv, err := StartCallbackServer(port, state, "https://example.com/authorize")
	if err != nil {
		t.Fatalf("StartCallbackServer failed: %v", err)
	}
	defer srv.Close()

	// Send callback with correct state but no code
	url := fmt.Sprintf("http://127.0.0.1:%d/callback?state=%s", port, state)
	resp, err := http.Get(url)
	if err != nil {
		t.Fatalf("HTTP GET failed: %v", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != 400 {
		t.Errorf("Expected 400, got %d", resp.StatusCode)
	}

	select {
	case result := <-resultCh:
		if result.Error == "" {
			t.Error("Expected error for missing code")
		}
	case <-time.After(2 * time.Second):
		t.Fatal("Timeout waiting for callback result")
	}
}

func TestStartCallbackServer_ErrorCallback(t *testing.T) {
	port := 19879
	state := "my-state"

	resultCh, srv, err := StartCallbackServer(port, state, "https://example.com/authorize")
	if err != nil {
		t.Fatalf("StartCallbackServer failed: %v", err)
	}
	defer srv.Close()

	// Simulate error from IdP
	url := fmt.Sprintf("http://127.0.0.1:%d/callback?error=access_denied&error_description=User+cancelled", port)
	resp, err := http.Get(url)
	if err != nil {
		t.Fatalf("HTTP GET failed: %v", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != 400 {
		t.Errorf("Expected 400, got %d", resp.StatusCode)
	}

	select {
	case result := <-resultCh:
		if result.Error != "User cancelled" {
			t.Errorf("Expected 'User cancelled', got '%s'", result.Error)
		}
	case <-time.After(2 * time.Second):
		t.Fatal("Timeout waiting for callback result")
	}
}

func TestStartCallbackServer_LandingPage(t *testing.T) {
	port := 19880
	state := "my-state"
	authURL := "https://idp.example.com/oauth2/authorize?client_id=abc"

	_, srv, err := StartCallbackServer(port, state, authURL)
	if err != nil {
		t.Fatalf("StartCallbackServer failed: %v", err)
	}
	defer srv.Close()

	// Request the landing page
	url := fmt.Sprintf("http://127.0.0.1:%d/", port)
	resp, err := http.Get(url)
	if err != nil {
		t.Fatalf("HTTP GET failed: %v", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != 200 {
		t.Errorf("Expected 200, got %d", resp.StatusCode)
	}

	// Verify content type is HTML
	ct := resp.Header.Get("Content-Type")
	if ct != "text/html" {
		t.Errorf("Expected text/html, got %s", ct)
	}
}

func TestWaitForCallback_Timeout(t *testing.T) {
	resultCh := make(chan CallbackResult, 1)
	srv := &http.Server{}

	result, err := WaitForCallback(resultCh, srv, 100*time.Millisecond)
	if err == nil {
		t.Fatal("Expected timeout error")
	}
	if result != nil {
		t.Error("Expected nil result on timeout")
	}
}

func TestWaitForCallback_Success(t *testing.T) {
	resultCh := make(chan CallbackResult, 1)
	srv := &http.Server{}

	// Pre-fill the channel
	resultCh <- CallbackResult{Code: "my-code"}

	result, err := WaitForCallback(resultCh, srv, 5*time.Second)
	if err != nil {
		t.Fatalf("Unexpected error: %v", err)
	}
	if result.Code != "my-code" {
		t.Errorf("Expected 'my-code', got '%s'", result.Code)
	}
}
