package azure

import (
	"crypto"
	"crypto/rand"
	"crypto/rsa"
	"crypto/sha256"
	"crypto/x509"
	"encoding/base64"
	"encoding/json"
	"encoding/pem"
	"fmt"
	"os"
	"time"
)

// BuildClientAssertion creates a PS256-signed JWT client assertion for Azure AD
// certificate-based confidential client authentication.
func BuildClientAssertion(certPath, keyPath, clientID, tokenURL string) (string, error) {
	if envCert := os.Getenv("AZURE_CLIENT_CERTIFICATE_PATH"); envCert != "" {
		certPath = envCert
	}
	if envKey := os.Getenv("AZURE_CLIENT_CERTIFICATE_KEY_PATH"); envKey != "" {
		keyPath = envKey
	}

	certPEM, err := os.ReadFile(certPath)
	if err != nil {
		return "", fmt.Errorf("reading certificate: %w", err)
	}

	keyPEM, err := os.ReadFile(keyPath)
	if err != nil {
		return "", fmt.Errorf("reading private key: %w", err)
	}

	certBlock, _ := pem.Decode(certPEM)
	if certBlock == nil {
		return "", fmt.Errorf("failed to decode certificate PEM")
	}

	cert, err := x509.ParseCertificate(certBlock.Bytes)
	if err != nil {
		return "", fmt.Errorf("parsing certificate: %w", err)
	}

	keyBlock, _ := pem.Decode(keyPEM)
	if keyBlock == nil {
		return "", fmt.Errorf("failed to decode private key PEM")
	}

	privateKey, err := x509.ParsePKCS8PrivateKey(keyBlock.Bytes)
	if err != nil {
		// Try PKCS1 format as fallback
		pk, err2 := x509.ParsePKCS1PrivateKey(keyBlock.Bytes)
		if err2 != nil {
			return "", fmt.Errorf("parsing private key (tried PKCS8 and PKCS1): %w", err)
		}
		privateKey = pk
	}

	rsaKey, ok := privateKey.(*rsa.PrivateKey)
	if !ok {
		return "", fmt.Errorf("private key is not RSA")
	}

	// SHA-256 thumbprint of DER-encoded certificate
	thumbprint := sha256.Sum256(cert.Raw)
	x5tS256 := base64.RawURLEncoding.EncodeToString(thumbprint[:])

	now := time.Now().Unix()
	header := map[string]string{
		"alg":      "PS256",
		"typ":      "JWT",
		"x5t#S256": x5tS256,
	}

	payload := map[string]interface{}{
		"aud": tokenURL,
		"iss": clientID,
		"sub": clientID,
		"jti": generateJTI(),
		"nbf": now,
		"iat": now,
		"exp": now + 300,
	}

	headerJSON, err := json.Marshal(header)
	if err != nil {
		return "", err
	}
	payloadJSON, err := json.Marshal(payload)
	if err != nil {
		return "", err
	}

	headerB64 := base64.RawURLEncoding.EncodeToString(headerJSON)
	payloadB64 := base64.RawURLEncoding.EncodeToString(payloadJSON)

	signingInput := headerB64 + "." + payloadB64
	hash := sha256.Sum256([]byte(signingInput))

	signature, err := rsa.SignPSS(rand.Reader, rsaKey, crypto.SHA256, hash[:], &rsa.PSSOptions{
		SaltLength: rsa.PSSSaltLengthEqualsHash,
	})
	if err != nil {
		return "", fmt.Errorf("signing assertion: %w", err)
	}

	sigB64 := base64.RawURLEncoding.EncodeToString(signature)
	return signingInput + "." + sigB64, nil
}

func generateJTI() string {
	b := make([]byte, 16)
	_, _ = rand.Read(b)
	return base64.RawURLEncoding.EncodeToString(b)
}
