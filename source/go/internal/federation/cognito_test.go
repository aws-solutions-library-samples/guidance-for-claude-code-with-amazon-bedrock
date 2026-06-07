package federation

import (
	"fmt"
	"testing"

	"ccwb-go/internal/jwt"
)

func TestDetermineLoginKey_Cognito_UsesIssuer(t *testing.T) {
	claims := jwt.Claims{
		"iss": "https://cognito-idp.us-east-1.amazonaws.com/us-east-1_ABC123",
		"sub": "user-123",
	}
	key := determineLoginKey("cognito", "cognito-idp.us-east-1.amazonaws.com/us-east-1_ABC123", claims)
	expected := "cognito-idp.us-east-1.amazonaws.com/us-east-1_ABC123"
	if key != expected {
		t.Errorf("Expected %q, got %q", expected, key)
	}
}

func TestDetermineLoginKey_Cognito_FallsBackToDomain(t *testing.T) {
	claims := jwt.Claims{
		"sub": "user-123",
	}
	key := determineLoginKey("cognito", "cognito-idp.us-east-1.amazonaws.com/us-east-1_XYZ", claims)
	expected := "cognito-idp.us-east-1.amazonaws.com/us-east-1_XYZ"
	if key != expected {
		t.Errorf("Expected %q, got %q", expected, key)
	}
}

func TestDetermineLoginKey_NonCognito_UsesDomain(t *testing.T) {
	claims := jwt.Claims{
		"iss":   "https://myorg.okta.com",
		"email": "alice@example.com",
	}
	key := determineLoginKey("okta", "myorg.okta.com", claims)
	expected := "myorg.okta.com"
	if key != expected {
		t.Errorf("Expected %q, got %q", expected, key)
	}
}

func TestDetermineLoginKey_Azure_UsesDomain(t *testing.T) {
	claims := jwt.Claims{
		"iss": "https://login.microsoftonline.com/tenant-guid/v2.0",
	}
	key := determineLoginKey("azure", "login.microsoftonline.com/tenant-guid/v2.0", claims)
	expected := "login.microsoftonline.com/tenant-guid/v2.0"
	if key != expected {
		t.Errorf("Expected %q, got %q", expected, key)
	}
}

func TestIsRetryableAuthError_NilError(t *testing.T) {
	if IsRetryableAuthError(nil) {
		t.Error("nil error should not be retryable")
	}
}

func TestIsRetryableAuthError_InvalidToken(t *testing.T) {
	err := fmt.Errorf("NotAuthorizedException: Token is not from a supported provider")
	if !IsRetryableAuthError(err) {
		t.Error("NotAuthorizedException should be retryable")
	}
}

func TestIsRetryableAuthError_ExpiredToken(t *testing.T) {
	err := fmt.Errorf("ExpiredToken: credentials expired")
	if !IsRetryableAuthError(err) {
		t.Error("ExpiredToken should be retryable")
	}
}

func TestIsRetryableAuthError_UnrelatedError(t *testing.T) {
	err := fmt.Errorf("network timeout: context deadline exceeded")
	if IsRetryableAuthError(err) {
		t.Error("network timeout should not be retryable")
	}
}

func TestIsRetryableAuthError_InvalidJWT(t *testing.T) {
	err := fmt.Errorf("Invalid JWT: malformed token")
	if !IsRetryableAuthError(err) {
		t.Error("Invalid JWT should be retryable")
	}
}

func TestIsRetryableAuthError_InvalidAccessKey(t *testing.T) {
	err := fmt.Errorf("Invalid AccessKeyId: AKIAIOSFODNN7EXAMPLE")
	if !IsRetryableAuthError(err) {
		t.Error("Invalid AccessKeyId should be retryable")
	}
}
