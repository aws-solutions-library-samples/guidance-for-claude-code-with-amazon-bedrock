package azure

import (
	"crypto"
	"crypto/rand"
	"crypto/rsa"
	"crypto/sha256"
	"crypto/x509"
	"crypto/x509/pkix"
	"encoding/base64"
	"encoding/json"
	"encoding/pem"
	"math/big"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func TestBuildClientAssertion(t *testing.T) {
	// Generate test key pair
	privateKey, err := rsa.GenerateKey(rand.Reader, 2048)
	if err != nil {
		t.Fatal(err)
	}

	// Generate self-signed cert
	template := &x509.Certificate{
		SerialNumber: big.NewInt(1),
		Subject:      pkix.Name{CommonName: "test"},
		NotBefore:    time.Now(),
		NotAfter:     time.Now().Add(time.Hour),
	}
	certDER, err := x509.CreateCertificate(rand.Reader, template, template, &privateKey.PublicKey, privateKey)
	if err != nil {
		t.Fatal(err)
	}

	// Write cert and key to temp files
	dir := t.TempDir()
	certPath := filepath.Join(dir, "cert.pem")
	keyPath := filepath.Join(dir, "key.pem")

	certPEM := pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: certDER})
	os.WriteFile(certPath, certPEM, 0600)

	keyDER, err := x509.MarshalPKCS8PrivateKey(privateKey)
	if err != nil {
		t.Fatal(err)
	}
	keyPEM := pem.EncodeToMemory(&pem.Block{Type: "PRIVATE KEY", Bytes: keyDER})
	os.WriteFile(keyPath, keyPEM, 0600)

	// Build assertion
	clientID := "test-client-id"
	tokenURL := "https://login.microsoftonline.com/tenant/oauth2/v2.0/token"

	assertion, err := BuildClientAssertion(certPath, keyPath, clientID, tokenURL)
	if err != nil {
		t.Fatalf("BuildClientAssertion failed: %v", err)
	}

	// Validate JWT structure
	parts := strings.Split(assertion, ".")
	if len(parts) != 3 {
		t.Fatalf("expected 3 JWT parts, got %d", len(parts))
	}

	// Decode and verify header
	headerJSON, err := base64.RawURLEncoding.DecodeString(parts[0])
	if err != nil {
		t.Fatal(err)
	}
	var header map[string]string
	json.Unmarshal(headerJSON, &header)

	if header["alg"] != "PS256" {
		t.Errorf("expected alg=PS256, got %s", header["alg"])
	}
	if header["x5t#S256"] == "" {
		t.Error("expected x5t#S256 to be present")
	}

	// Verify thumbprint matches certificate
	expectedThumbprint := sha256.Sum256(certDER)
	expectedX5t := base64.RawURLEncoding.EncodeToString(expectedThumbprint[:])
	if header["x5t#S256"] != expectedX5t {
		t.Errorf("x5t#S256 mismatch: got %s, want %s", header["x5t#S256"], expectedX5t)
	}

	// Decode and verify payload
	payloadJSON, err := base64.RawURLEncoding.DecodeString(parts[1])
	if err != nil {
		t.Fatal(err)
	}
	var payload map[string]interface{}
	json.Unmarshal(payloadJSON, &payload)

	if payload["aud"] != tokenURL {
		t.Errorf("expected aud=%s, got %v", tokenURL, payload["aud"])
	}
	if payload["iss"] != clientID {
		t.Errorf("expected iss=%s, got %v", clientID, payload["iss"])
	}
	if payload["sub"] != clientID {
		t.Errorf("expected sub=%s, got %v", clientID, payload["sub"])
	}
	if payload["exp"] == nil {
		t.Error("expected exp claim")
	}

	// Verify signature with public key
	signingInput := parts[0] + "." + parts[1]
	signature, err := base64.RawURLEncoding.DecodeString(parts[2])
	if err != nil {
		t.Fatal(err)
	}

	hash := sha256.Sum256([]byte(signingInput))
	err = rsa.VerifyPSS(&privateKey.PublicKey, crypto.SHA256, hash[:], signature, &rsa.PSSOptions{
		SaltLength: rsa.PSSSaltLengthEqualsHash,
	})
	if err != nil {
		t.Errorf("signature verification failed: %v", err)
	}
}

func TestBuildClientAssertionMissingFiles(t *testing.T) {
	_, err := BuildClientAssertion("/nonexistent/cert.pem", "/nonexistent/key.pem", "id", "url")
	if err == nil {
		t.Error("expected error for missing files")
	}
}
