package oidc

import (
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
)

// GenerateState returns a cryptographically random URL-safe string for OAuth2 state.
func GenerateState() (string, error) {
	b := make([]byte, 16)
	if _, err := rand.Read(b); err != nil {
		return "", err
	}
	return base64.RawURLEncoding.EncodeToString(b), nil
}

// GenerateNonce returns a cryptographically random URL-safe string for OIDC nonce.
func GenerateNonce() (string, error) {
	b := make([]byte, 16)
	if _, err := rand.Read(b); err != nil {
		return "", err
	}
	return base64.RawURLEncoding.EncodeToString(b), nil
}

// PKCE holds the code verifier and challenge for PKCE flow.
type PKCE struct {
	CodeVerifier  string
	CodeChallenge string
}

// GeneratePKCE creates a new PKCE code verifier and S256 code challenge.
func GeneratePKCE() (*PKCE, error) {
	b := make([]byte, 32)
	if _, err := rand.Read(b); err != nil {
		return nil, err
	}
	verifier := base64.RawURLEncoding.EncodeToString(b)

	h := sha256.Sum256([]byte(verifier))
	challenge := base64.RawURLEncoding.EncodeToString(h[:])

	return &PKCE{
		CodeVerifier:  verifier,
		CodeChallenge: challenge,
	}, nil
}
