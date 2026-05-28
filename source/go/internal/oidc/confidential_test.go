package oidc

import (
	"crypto/rand"
	"crypto/rsa"
	"crypto/sha256"
	"crypto/x509"
	"crypto/x509/pkix"
	"encoding/base64"
	"encoding/json"
	"encoding/pem"
	"io"
	"math/big"
	"net/http"
	"net/http/httptest"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

// captureTokenServer runs a minimal token endpoint that records the POST form.
// Tests use it to assert what the client sent without hitting a real IdP.
func captureTokenServer(t *testing.T) (*httptest.Server, *url.Values) {
	t.Helper()
	var captured url.Values
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		body, _ := io.ReadAll(r.Body)
		parsed, err := url.ParseQuery(string(body))
		if err != nil {
			t.Fatalf("parsing request body: %v", err)
		}
		captured = parsed
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"id_token":"test-id-token","access_token":"a","token_type":"Bearer","expires_in":3600}`))
	}))
	t.Cleanup(srv.Close)
	return srv, &captured
}

func TestExchangeCode_PublicClient(t *testing.T) {
	srv, captured := captureTokenServer(t)

	_, err := ExchangeCode(srv.URL, "code-xyz", "http://localhost:8400/callback", "client-abc", "verifier", nil)
	if err != nil {
		t.Fatalf("ExchangeCode: %v", err)
	}
	if got := captured.Get("grant_type"); got != "authorization_code" {
		t.Errorf("grant_type = %q, want authorization_code", got)
	}
	if captured.Has("client_secret") {
		t.Errorf("public client must not send client_secret")
	}
	if captured.Has("client_assertion") {
		t.Errorf("public client must not send client_assertion")
	}
}

func TestExchangeCode_SecretMode(t *testing.T) {
	srv, captured := captureTokenServer(t)

	conf := &ConfidentialAuth{ClientSecret: "supers3kret"}
	_, err := ExchangeCode(srv.URL, "code", "http://localhost:8400/callback", "client-abc", "verifier", conf)
	if err != nil {
		t.Fatalf("ExchangeCode: %v", err)
	}
	if got := captured.Get("client_secret"); got != "supers3kret" {
		t.Errorf("client_secret = %q, want supers3kret", got)
	}
	if captured.Has("client_assertion") {
		t.Errorf("secret mode must not send client_assertion")
	}
}

func TestExchangeCode_CertificateMode(t *testing.T) {
	certPath, keyPath, cert, _ := writeTestCertAndKey(t)

	srv, captured := captureTokenServer(t)

	conf := &ConfidentialAuth{CertificatePath: certPath, PrivateKeyPath: keyPath}
	_, err := ExchangeCode(srv.URL, "code", "http://localhost:8400/callback", "client-abc", "verifier", conf)
	if err != nil {
		t.Fatalf("ExchangeCode: %v", err)
	}

	if got := captured.Get("client_assertion_type"); got != "urn:ietf:params:oauth:client-assertion-type:jwt-bearer" {
		t.Errorf("client_assertion_type = %q", got)
	}
	assertion := captured.Get("client_assertion")
	if assertion == "" {
		t.Fatal("client_assertion is empty")
	}

	parts := strings.Split(assertion, ".")
	if len(parts) != 3 {
		t.Fatalf("client_assertion has %d parts, want 3", len(parts))
	}

	headerBytes, err := base64.RawURLEncoding.DecodeString(parts[0])
	if err != nil {
		t.Fatalf("decoding header: %v", err)
	}
	var header map[string]string
	if err := json.Unmarshal(headerBytes, &header); err != nil {
		t.Fatalf("parsing header: %v", err)
	}
	if header["alg"] != "PS256" {
		t.Errorf("alg = %q, want PS256", header["alg"])
	}
	if header["x5t#S256"] == "" {
		t.Error("x5t#S256 missing")
	}
	// Thumbprint must be base64url(sha256(DER)) of the cert we wrote.
	wantThumbprint := base64.RawURLEncoding.EncodeToString(sha256SumDER(cert))
	if header["x5t#S256"] != wantThumbprint {
		t.Errorf("x5t#S256 = %q, want %q", header["x5t#S256"], wantThumbprint)
	}

	payloadBytes, err := base64.RawURLEncoding.DecodeString(parts[1])
	if err != nil {
		t.Fatalf("decoding payload: %v", err)
	}
	var payload map[string]interface{}
	if err := json.Unmarshal(payloadBytes, &payload); err != nil {
		t.Fatalf("parsing payload: %v", err)
	}
	if got := payload["aud"]; got != srv.URL {
		t.Errorf("aud = %v, want %s", got, srv.URL)
	}
	if got := payload["iss"]; got != "client-abc" {
		t.Errorf("iss = %v, want client-abc", got)
	}
	if got := payload["sub"]; got != "client-abc" {
		t.Errorf("sub = %v, want client-abc", got)
	}
	if _, ok := payload["jti"]; !ok {
		t.Error("jti missing")
	}
	expFloat, ok := payload["exp"].(float64)
	if !ok {
		t.Fatalf("exp not a number: %T", payload["exp"])
	}
	iatFloat, _ := payload["iat"].(float64)
	if int64(expFloat)-int64(iatFloat) != 300 {
		t.Errorf("exp - iat = %d, want 300", int64(expFloat)-int64(iatFloat))
	}
	if time.Now().Unix() > int64(expFloat) {
		t.Error("assertion already expired at creation time")
	}
}

func TestExchangeCode_CertificateMissingFile(t *testing.T) {
	srv, _ := captureTokenServer(t)

	conf := &ConfidentialAuth{
		CertificatePath: "/nonexistent/cert.pem",
		PrivateKeyPath:  "/nonexistent/key.pem",
	}
	_, err := ExchangeCode(srv.URL, "code", "http://localhost:8400/callback", "client-abc", "verifier", conf)
	if err == nil {
		t.Fatal("want error for missing cert, got nil")
	}
	if !strings.Contains(err.Error(), "certificate file not found") {
		t.Errorf("error = %v, want to mention missing cert", err)
	}
}

func TestExchangeCode_CertificateMissingKey(t *testing.T) {
	certPath, _, _, _ := writeTestCertAndKey(t)

	srv, _ := captureTokenServer(t)

	conf := &ConfidentialAuth{CertificatePath: certPath, PrivateKeyPath: "/nonexistent/key.pem"}
	_, err := ExchangeCode(srv.URL, "code", "http://localhost:8400/callback", "client-abc", "verifier", conf)
	if err == nil {
		t.Fatal("want error for missing key, got nil")
	}
	if !strings.Contains(err.Error(), "private key file not found") {
		t.Errorf("error = %v, want to mention missing key", err)
	}
}

func TestExchangeCode_CertificateBadKey(t *testing.T) {
	certPath, _, _, _ := writeTestCertAndKey(t)

	// Write a PEM file that is not a private key
	tmp := t.TempDir()
	badKey := filepath.Join(tmp, "notakey.pem")
	if err := os.WriteFile(badKey, []byte("-----BEGIN RSA PRIVATE KEY-----\nnotvalidbase64\n-----END RSA PRIVATE KEY-----\n"), 0o600); err != nil {
		t.Fatal(err)
	}

	srv, _ := captureTokenServer(t)

	conf := &ConfidentialAuth{CertificatePath: certPath, PrivateKeyPath: badKey}
	_, err := ExchangeCode(srv.URL, "code", "http://localhost:8400/callback", "client-abc", "verifier", conf)
	if err == nil {
		t.Fatal("want error for bad key, got nil")
	}
}

func TestConfidentialAuth_CertBeatsSecret(t *testing.T) {
	// If both set, certificate wins -- matches Python precedence.
	certPath, keyPath, _, _ := writeTestCertAndKey(t)

	srv, captured := captureTokenServer(t)

	conf := &ConfidentialAuth{
		ClientSecret:    "should-be-ignored",
		CertificatePath: certPath,
		PrivateKeyPath:  keyPath,
	}
	_, err := ExchangeCode(srv.URL, "code", "http://localhost:8400/callback", "client-abc", "verifier", conf)
	if err != nil {
		t.Fatalf("ExchangeCode: %v", err)
	}
	if captured.Has("client_secret") {
		t.Error("client_secret must not be sent when certificate is configured")
	}
	if captured.Get("client_assertion") == "" {
		t.Error("client_assertion missing")
	}
}

// writeTestCertAndKey generates a self-signed RSA cert + PKCS#8 private key,
// writes both to a tempdir, and returns paths + parsed objects.
func writeTestCertAndKey(t *testing.T) (certPath, keyPath string, cert *x509.Certificate, key *rsa.PrivateKey) {
	t.Helper()
	key, err := rsa.GenerateKey(rand.Reader, 2048)
	if err != nil {
		t.Fatal(err)
	}
	tmpl := &x509.Certificate{
		SerialNumber: big.NewInt(42),
		Subject:      pkix.Name{CommonName: "test"},
		NotBefore:    time.Now().Add(-time.Hour),
		NotAfter:     time.Now().Add(time.Hour),
	}
	certDER, err := x509.CreateCertificate(rand.Reader, tmpl, tmpl, &key.PublicKey, key)
	if err != nil {
		t.Fatal(err)
	}
	cert, err = x509.ParseCertificate(certDER)
	if err != nil {
		t.Fatal(err)
	}

	dir := t.TempDir()
	certPath = filepath.Join(dir, "cert.pem")
	keyPath = filepath.Join(dir, "key.pem")

	certPEM := pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: certDER})
	if err := os.WriteFile(certPath, certPEM, 0o600); err != nil {
		t.Fatal(err)
	}

	keyDER, err := x509.MarshalPKCS8PrivateKey(key)
	if err != nil {
		t.Fatal(err)
	}
	keyPEM := pem.EncodeToMemory(&pem.Block{Type: "PRIVATE KEY", Bytes: keyDER})
	if err := os.WriteFile(keyPath, keyPEM, 0o600); err != nil {
		t.Fatal(err)
	}
	return
}

func sha256SumDER(cert *x509.Certificate) []byte {
	sum := sha256.Sum256(cert.Raw)
	return sum[:]
}
