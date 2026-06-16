package jwt

import (
	"encoding/base64"
	"encoding/json"
	"testing"
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

func equalStringSlice(a, b []string) bool {
	if len(a) != len(b) {
		return false
	}
	for i := range a {
		if a[i] != b[i] {
			return false
		}
	}
	return true
}

func TestGetStringSlice_Array(t *testing.T) {
	// JSON arrays decode to []interface{}, which is what DecodePayload produces.
	claims := Claims{"groups": []interface{}{"eng-team", "sales-team"}}
	got := claims.GetStringSlice("groups")
	if !equalStringSlice(got, []string{"eng-team", "sales-team"}) {
		t.Errorf("expected [eng-team sales-team], got %v", got)
	}
}

func TestGetStringSlice_ArrayPreservesOrder(t *testing.T) {
	claims := Claims{"groups": []interface{}{"c", "a", "b"}}
	got := claims.GetStringSlice("groups")
	if !equalStringSlice(got, []string{"c", "a", "b"}) {
		t.Errorf("expected order preserved [c a b], got %v", got)
	}
}

func TestGetStringSlice_ScalarString(t *testing.T) {
	claims := Claims{"groups": "eng-team"}
	got := claims.GetStringSlice("groups")
	if !equalStringSlice(got, []string{"eng-team"}) {
		t.Errorf("expected single-element [eng-team], got %v", got)
	}
}

func TestGetStringSlice_Missing(t *testing.T) {
	claims := Claims{}
	if got := claims.GetStringSlice("groups"); got != nil {
		t.Errorf("expected nil for missing key, got %v", got)
	}
}

func TestGetStringSlice_NonStringElementsSkipped(t *testing.T) {
	// A mixed array keeps the strings and skips numbers/objects/nulls.
	claims := Claims{"groups": []interface{}{"eng-team", 42.0, "sales-team", nil, map[string]interface{}{}}}
	got := claims.GetStringSlice("groups")
	if !equalStringSlice(got, []string{"eng-team", "sales-team"}) {
		t.Errorf("expected non-strings skipped -> [eng-team sales-team], got %v", got)
	}
}

func TestGetStringSlice_EmptyArray(t *testing.T) {
	claims := Claims{"groups": []interface{}{}}
	got := claims.GetStringSlice("groups")
	if got == nil {
		t.Error("expected non-nil empty slice for an empty array (present but no groups)")
	}
	if len(got) != 0 {
		t.Errorf("expected zero-length slice, got %v", got)
	}
}

func TestGetStringSlice_WrongScalarType(t *testing.T) {
	// A scalar of the wrong type (number) is not a group list -> nil.
	claims := Claims{"groups": 42.0}
	if got := claims.GetStringSlice("groups"); got != nil {
		t.Errorf("expected nil for non-string scalar, got %v", got)
	}
}

func TestGetStringSlice_EndToEndFromJWT(t *testing.T) {
	// Confirm it works against a real decoded payload, not just hand-built Claims.
	token := makeTestJWT(map[string]interface{}{"groups": []interface{}{"eng-team"}})
	claims, err := DecodePayload(token)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if got := claims.GetStringSlice("groups"); !equalStringSlice(got, []string{"eng-team"}) {
		t.Errorf("expected [eng-team] from decoded JWT, got %v", got)
	}
}
