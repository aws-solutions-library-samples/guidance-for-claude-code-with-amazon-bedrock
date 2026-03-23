package oidc

import (
	"strings"
	"testing"
)

func TestGeneratePKCE(t *testing.T) {
	pkce, err := GeneratePKCE()
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	if pkce.CodeVerifier == "" {
		t.Error("CodeVerifier should not be empty")
	}
	if pkce.CodeChallenge == "" {
		t.Error("CodeChallenge should not be empty")
	}
	if pkce.CodeVerifier == pkce.CodeChallenge {
		t.Error("CodeVerifier and CodeChallenge should differ")
	}

	// Verify no padding
	if strings.Contains(pkce.CodeVerifier, "=") {
		t.Error("CodeVerifier should not have padding")
	}
	if strings.Contains(pkce.CodeChallenge, "=") {
		t.Error("CodeChallenge should not have padding")
	}
}

func TestGeneratePKCE_Uniqueness(t *testing.T) {
	pkce1, _ := GeneratePKCE()
	pkce2, _ := GeneratePKCE()
	if pkce1.CodeVerifier == pkce2.CodeVerifier {
		t.Error("Two PKCE generations should produce different verifiers")
	}
}

func TestGenerateState(t *testing.T) {
	state, err := GenerateState()
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if state == "" {
		t.Error("state should not be empty")
	}
	if strings.Contains(state, "=") {
		t.Error("state should not have padding")
	}
}

func TestGenerateNonce(t *testing.T) {
	nonce, err := GenerateNonce()
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if nonce == "" {
		t.Error("nonce should not be empty")
	}
}
