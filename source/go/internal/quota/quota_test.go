package quota

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestCheck_EmptyToken_FallsToIAMPath(t *testing.T) {
	// When idToken is empty, Check should attempt IAM auth (CheckWithIAM).
	// Without valid AWS credentials in the test env, it will fail gracefully
	// with the fail-open mode returning allowed=true.
	result := Check("http://localhost:1", "", 1, "open")
	if result == nil {
		t.Fatal("Check with empty token should return a result, not nil")
	}
	// In fail-open mode, errors should still allow
	if !result.Allowed {
		t.Errorf("fail-open mode should allow even on error, got allowed=%v reason=%s", result.Allowed, result.Reason)
	}
}

func TestCheck_WithToken_UsesJWTPath(t *testing.T) {
	// Mock a quota endpoint that expects Bearer token
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		auth := r.Header.Get("Authorization")
		if auth != "Bearer test-token-123" {
			w.WriteHeader(401)
			return
		}
		json.NewEncoder(w).Encode(Result{Allowed: true, Reason: "within_limits"})
	}))
	defer server.Close()

	result := Check(server.URL, "test-token-123", 5, "closed")
	if result == nil {
		t.Fatal("expected non-nil result")
	}
	if !result.Allowed {
		t.Errorf("expected allowed=true with valid token, got reason=%s", result.Reason)
	}
}

func TestCheck_WithToken_InvalidToken_Returns401(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(401)
	}))
	defer server.Close()

	result := Check(server.URL, "bad-token", 5, "closed")
	if result == nil {
		t.Fatal("expected non-nil result")
	}
	if result.Allowed {
		t.Error("401 with fail-closed should not be allowed")
	}
	if result.Reason != "jwt_invalid" {
		t.Errorf("reason = %q, want jwt_invalid", result.Reason)
	}
}

func TestCheck_FailOpen_AllowsOnError(t *testing.T) {
	// Unreachable endpoint
	result := Check("http://localhost:1", "token", 1, "open")
	if !result.Allowed {
		t.Error("fail-open mode should allow on connection error")
	}
}

func TestCheck_FailClosed_BlocksOnError(t *testing.T) {
	result := Check("http://localhost:1", "token", 1, "closed")
	if result.Allowed {
		t.Error("fail-closed mode should block on connection error")
	}
}
