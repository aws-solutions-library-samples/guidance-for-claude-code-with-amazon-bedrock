package oidc

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
	"path/filepath"
	"strings"
	"time"
)

// ConfidentialAuth carries Azure-AD confidential-client material. Pass nil for
// public PKCE-only flows (Okta, Auth0, Cognito, or Azure "public" mode).
//
// Exactly one of ClientSecret or (CertificatePath + PrivateKeyPath) must be
// populated. The caller resolves env-var overrides (AZURE_CLIENT_CERTIFICATE_PATH,
// AZURE_CLIENT_CERTIFICATE_KEY_PATH) and keyring lookups before constructing
// this struct -- this package stays filesystem-only for cert mode and in-memory
// for secret mode.
type ConfidentialAuth struct {
	ClientSecret    string
	CertificatePath string
	PrivateKeyPath  string
}

// ApplyConfidentialForTest exposes the confidential-auth apply step for the
// azure-assertion-smoke regression test binary under cmd/azure-assertion-smoke.
// Not intended for production callers -- they should go through Authenticate.
func ApplyConfidentialForTest(c *ConfidentialAuth, form map[string]string, tokenURL, clientID string) error {
	return c.apply(form, tokenURL, clientID)
}

// apply mutates the token-exchange form with the right confidential-client
// fields. Certificate mode wins over secret mode if both are set (matches the
// Python precedence at credential_provider/__main__.py:946-950).
func (c *ConfidentialAuth) apply(form map[string]string, tokenURL, clientID string) error {
	if c == nil {
		return nil
	}
	if c.CertificatePath != "" && c.PrivateKeyPath != "" {
		assertion, err := buildClientAssertion(c.CertificatePath, c.PrivateKeyPath, tokenURL, clientID)
		if err != nil {
			return err
		}
		form["client_assertion_type"] = "urn:ietf:params:oauth:client-assertion-type:jwt-bearer"
		form["client_assertion"] = assertion
		return nil
	}
	if c.ClientSecret != "" {
		form["client_secret"] = c.ClientSecret // pragma: allowlist secret
		return nil
	}
	return nil
}

// buildClientAssertion signs a JWT for Azure AD certificate-credential auth.
// Follows https://learn.microsoft.com/en-us/entra/identity-platform/certificate-credentials
// -- PS256 over a payload of {aud, iss, sub, jti, nbf, iat, exp} with the
// certificate's SHA-256 thumbprint (x5t#S256) in the JOSE header. The five
// minute expiry matches Python's _build_client_assertion.
func buildClientAssertion(certPath, keyPath, tokenURL, clientID string) (string, error) {
	certPath = expandPath(certPath)
	keyPath = expandPath(keyPath)

	if _, err := os.Stat(certPath); err != nil {
		return "", fmt.Errorf("certificate file not found: %s\n"+
			"Set the AZURE_CLIENT_CERTIFICATE_PATH environment variable to the correct path, "+
			"or update 'client_certificate_path' in config.json.", certPath)
	}
	if _, err := os.Stat(keyPath); err != nil {
		return "", fmt.Errorf("private key file not found: %s\n"+
			"Set the AZURE_CLIENT_CERTIFICATE_KEY_PATH environment variable to the correct path, "+
			"or update 'client_certificate_key_path' in config.json.", keyPath)
	}

	certPEM, err := os.ReadFile(certPath)
	if err != nil {
		return "", fmt.Errorf("reading certificate: %w", err)
	}
	keyPEM, err := os.ReadFile(keyPath)
	if err != nil {
		return "", fmt.Errorf("reading private key: %w", err)
	}

	cert, err := parseCertificate(certPEM)
	if err != nil {
		return "", fmt.Errorf("parsing certificate: %w", err)
	}
	privKey, err := parseRSAPrivateKey(keyPEM)
	if err != nil {
		return "", fmt.Errorf("parsing private key: %w", err)
	}

	thumbprint := sha256.Sum256(cert.Raw)
	x5tS256 := base64.RawURLEncoding.EncodeToString(thumbprint[:])

	header := map[string]string{
		"alg":      "PS256",
		"typ":      "JWT",
		"x5t#S256": x5tS256,
	}

	now := time.Now().Unix()
	jti, err := randomJTI()
	if err != nil {
		return "", fmt.Errorf("generating jti: %w", err)
	}
	payload := map[string]interface{}{
		"aud": tokenURL,
		"iss": clientID,
		"sub": clientID,
		"jti": jti,
		"nbf": now,
		"iat": now,
		"exp": now + 300,
	}

	headerBytes, err := json.Marshal(header)
	if err != nil {
		return "", fmt.Errorf("marshaling header: %w", err)
	}
	payloadBytes, err := json.Marshal(payload)
	if err != nil {
		return "", fmt.Errorf("marshaling payload: %w", err)
	}

	signingInput := base64.RawURLEncoding.EncodeToString(headerBytes) + "." +
		base64.RawURLEncoding.EncodeToString(payloadBytes)

	digest := sha256.Sum256([]byte(signingInput))
	sig, err := rsa.SignPSS(rand.Reader, privKey, crypto.SHA256, digest[:], &rsa.PSSOptions{
		SaltLength: rsa.PSSSaltLengthEqualsHash,
		Hash:       crypto.SHA256,
	})
	if err != nil {
		return "", fmt.Errorf("signing assertion: %w", err)
	}

	return signingInput + "." + base64.RawURLEncoding.EncodeToString(sig), nil
}

// parseCertificate accepts a standard PEM bundle and returns the first
// CERTIFICATE block. Callers hand in the same file Python passes to
// cryptography.x509.load_pem_x509_certificate, so we ignore extra blocks
// rather than erroring on bundles that include a chain.
func parseCertificate(pemData []byte) (*x509.Certificate, error) {
	rest := pemData
	for {
		var block *pem.Block
		block, rest = pem.Decode(rest)
		if block == nil {
			return nil, fmt.Errorf("no PEM CERTIFICATE block found")
		}
		if block.Type == "CERTIFICATE" {
			return x509.ParseCertificate(block.Bytes)
		}
	}
}

// parseRSAPrivateKey accepts PKCS#1 ("RSA PRIVATE KEY") or PKCS#8 ("PRIVATE KEY")
// PEM blocks. Azure requires RSA keys (PS256 is RSA-only); non-RSA keys return
// an explicit error so misconfiguration surfaces at auth time rather than as a
// cryptic signing failure.
func parseRSAPrivateKey(pemData []byte) (*rsa.PrivateKey, error) {
	rest := pemData
	for {
		var block *pem.Block
		block, rest = pem.Decode(rest)
		if block == nil {
			return nil, fmt.Errorf("no PEM PRIVATE KEY block found")
		}
		switch block.Type {
		case "RSA PRIVATE KEY":
			return x509.ParsePKCS1PrivateKey(block.Bytes)
		case "PRIVATE KEY":
			parsed, err := x509.ParsePKCS8PrivateKey(block.Bytes)
			if err != nil {
				return nil, err
			}
			rsaKey, ok := parsed.(*rsa.PrivateKey)
			if !ok {
				return nil, fmt.Errorf("private key is %T, not *rsa.PrivateKey (Azure certificate auth requires RSA)", parsed)
			}
			return rsaKey, nil
		}
	}
}

func randomJTI() (string, error) {
	buf := make([]byte, 16)
	if _, err := rand.Read(buf); err != nil {
		return "", err
	}
	return base64.RawURLEncoding.EncodeToString(buf), nil
}

func expandPath(p string) string {
	if strings.HasPrefix(p, "~/") || p == "~" {
		if home, err := os.UserHomeDir(); err == nil {
			return filepath.Join(home, strings.TrimPrefix(p, "~"))
		}
	}
	return p
}
