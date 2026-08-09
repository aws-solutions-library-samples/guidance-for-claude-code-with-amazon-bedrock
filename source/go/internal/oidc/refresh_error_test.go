package oidc

import (
	"net/http"
	"net/http/httptest"
	"testing"
)

// TestRefreshTokenExchange_ErrorClassification verifies that RefreshTokenExchange
// distinguishes a definitively-rejected refresh_token (invalid_grant /
// invalid_token → discard) from transient failures (5xx, unexpected 4xx, bad
// URL → retain). Clearing on a transient failure is the bug that permanently
// disabled silent OTEL-bearer renewal until the next browser login.
func TestRefreshTokenExchange_ErrorClassification(t *testing.T) {
	tests := []struct {
		name           string
		status         int
		body           string
		wantDefinitive bool
		wantOAuthCode  string
	}{
		{
			name:           "invalid_grant is definitive",
			status:         http.StatusBadRequest,
			body:           `{"error":"invalid_grant","error_description":"Token expired or revoked"}`,
			wantDefinitive: true,
			wantOAuthCode:  "invalid_grant",
		},
		{
			name:           "invalid_token is definitive",
			status:         http.StatusUnauthorized,
			body:           `{"error":"invalid_token"}`,
			wantDefinitive: true,
			wantOAuthCode:  "invalid_token",
		},
		{
			name:           "500 server error is transient",
			status:         http.StatusInternalServerError,
			body:           `{"error":"server_error"}`,
			wantDefinitive: false,
			wantOAuthCode:  "server_error",
		},
		{
			name:           "temporarily_unavailable is transient",
			status:         http.StatusServiceUnavailable,
			body:           `{"error":"temporarily_unavailable"}`,
			wantDefinitive: false,
			wantOAuthCode:  "temporarily_unavailable",
		},
		{
			name:           "unexpected 400 without invalid_grant is transient",
			status:         http.StatusBadRequest,
			body:           `{"error":"invalid_request","error_description":"malformed"}`,
			wantDefinitive: false,
			wantOAuthCode:  "invalid_request",
		},
		{
			name:           "non-JSON error body is transient",
			status:         http.StatusBadGateway,
			body:           `<html>502 Bad Gateway</html>`,
			wantDefinitive: false,
			wantOAuthCode:  "",
		},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				w.WriteHeader(tc.status)
				_, _ = w.Write([]byte(tc.body))
			}))
			defer srv.Close()

			_, err := RefreshTokenExchange(srv.URL, "rt_value", "client", nil)
			if err == nil {
				t.Fatalf("expected an error for status %d, got nil", tc.status)
			}
			if got := IsDefinitiveRefreshFailure(err); got != tc.wantDefinitive {
				t.Errorf("IsDefinitiveRefreshFailure = %v, want %v (err=%v)", got, tc.wantDefinitive, err)
			}
		})
	}
}

// TestRefreshTokenExchange_EmptyURLIsTransient verifies the defense-in-depth
// guard: an empty/relative token endpoint URL (the symptom of an unresolved
// provider type) must fail as a transient error, never as a definitive rejection
// that would discard the refresh_token.
func TestRefreshTokenExchange_EmptyURLIsTransient(t *testing.T) {
	for _, url := range []string{"", "login.microsoftonline.com/tenant/oauth2/v2.0/token"} {
		_, err := RefreshTokenExchange(url, "rt_value", "client", nil)
		if err == nil {
			t.Fatalf("expected an error for URL %q, got nil", url)
		}
		if IsDefinitiveRefreshFailure(err) {
			t.Errorf("empty/relative URL %q classified as definitive; must be transient", url)
		}
	}
}

// TestIsDefinitiveRefreshFailure_NilAndOther confirms the helper is safe for
// a nil error and for unrelated error types (both → not definitive, so the
// caller retains the token by default).
func TestIsDefinitiveRefreshFailure_NilAndOther(t *testing.T) {
	if IsDefinitiveRefreshFailure(nil) {
		t.Error("nil error must not be definitive")
	}
	if IsDefinitiveRefreshFailure(http.ErrServerClosed) {
		t.Error("unrelated error must not be definitive")
	}
}
