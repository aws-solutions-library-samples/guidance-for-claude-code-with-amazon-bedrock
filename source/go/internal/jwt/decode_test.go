package jwt

import (
	"encoding/base64"
	"encoding/json"
	"testing"
	"time"
)

func makeTestJWT(claims map[string]interface{}) string {
	header := base64.RawURLEncoding.EncodeToString([]byte(`{"alg":"RS256","typ":"JWT"}`))
	payload, _ := json.Marshal(claims)
	payloadB64 := base64.RawURLEncoding.EncodeToString(payload)
	return header + "." + payloadB64 + ".signature"
}

func TestDecodePayload_Basic(t *testing.T) {
	token := makeTestJWT(map[string]interface{}{
		"sub":   "user123",
		"email": "user@example.com",
		"exp":   1700000000.0,
	})

	claims, err := DecodePayload(token)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if claims.GetString("sub") != "user123" {
		t.Errorf("expected sub=user123, got %s", claims.GetString("sub"))
	}
	if claims.GetString("email") != "user@example.com" {
		t.Errorf("expected email=user@example.com, got %s", claims.GetString("email"))
	}
	if claims.GetFloat("exp") != 1700000000.0 {
		t.Errorf("expected exp=1700000000, got %f", claims.GetFloat("exp"))
	}
}

func TestDecodePayload_WithPadding(t *testing.T) {
	// Create a payload that needs padding
	token := makeTestJWT(map[string]interface{}{
		"sub": "a",
	})
	claims, err := DecodePayload(token)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if claims.GetString("sub") != "a" {
		t.Errorf("expected sub=a, got %s", claims.GetString("sub"))
	}
}

func TestDecodePayload_MalformedToken(t *testing.T) {
	_, err := DecodePayload("not.a.valid-base64!!!")
	if err == nil {
		t.Error("expected error for malformed token")
	}
}

func TestDecodePayload_TwoParts(t *testing.T) {
	_, err := DecodePayload("only.twoparts")
	if err == nil {
		t.Error("expected error for 2-part token")
	}
}

func TestDecodePayload_EmptyToken(t *testing.T) {
	_, err := DecodePayload("")
	if err == nil {
		t.Error("expected error for empty token")
	}
}

func TestGetString_Missing(t *testing.T) {
	claims := Claims{}
	if claims.GetString("missing") != "" {
		t.Error("expected empty string for missing key")
	}
}

func TestGetString_WrongType(t *testing.T) {
	claims := Claims{"num": 42.0}
	if claims.GetString("num") != "" {
		t.Error("expected empty string for non-string value")
	}
}

func TestGetFloat_Missing(t *testing.T) {
	claims := Claims{}
	if claims.GetFloat("missing") != 0 {
		t.Error("expected 0 for missing key")
	}
}

func TestGetFloat_WrongType(t *testing.T) {
	claims := Claims{"str": "hello"}
	if claims.GetFloat("str") != 0 {
		t.Error("expected 0 for non-float value")
	}
}

// IsTokenExpired mirrors the Python otel-helper's is_token_expired (60s buffer,
// fail-safe). These cases match the Python regression suite for #561 so the Go
// and Python variants treat the same token identically.

func TestIsTokenExpired_Valid(t *testing.T) {
	token := makeTestJWT(map[string]interface{}{
		"exp": float64(time.Now().Unix() + 3600),
	})
	if IsTokenExpired(token) {
		t.Error("token expiring in 1h should not be expired")
	}
}

func TestIsTokenExpired_Expired(t *testing.T) {
	token := makeTestJWT(map[string]interface{}{
		"exp": float64(time.Now().Unix() - 3600),
	})
	if !IsTokenExpired(token) {
		t.Error("token that expired 1h ago should be expired")
	}
}

func TestIsTokenExpired_WithinBuffer(t *testing.T) {
	// Expires in 30s — inside the 60s buffer, so treated as expired.
	token := makeTestJWT(map[string]interface{}{
		"exp": float64(time.Now().Unix() + 30),
	})
	if !IsTokenExpired(token) {
		t.Error("token expiring within the 60s buffer should be treated as expired")
	}
}

func TestIsTokenExpired_NoExpClaim(t *testing.T) {
	token := makeTestJWT(map[string]interface{}{
		"sub": "user123",
	})
	if !IsTokenExpired(token) {
		t.Error("token without exp claim should be treated as expired (fail-safe)")
	}
}

func TestIsTokenExpired_Malformed(t *testing.T) {
	if !IsTokenExpired("not-a-jwt") {
		t.Error("unparseable token should be treated as expired (fail-safe)")
	}
}

func TestIsTokenExpired_Empty(t *testing.T) {
	if !IsTokenExpired("") {
		t.Error("empty token should be treated as expired (fail-safe)")
	}
}
