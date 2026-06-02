package storage

import (
	"os"
	"testing"
	"time"

	"ccwb-go/internal/federation"
)

// TestSessionStorageRoundtrip verifies write → read → expiry check lifecycle.
func TestSessionStorageRoundtrip(t *testing.T) {
	tmpHome := t.TempDir()
	t.Setenv("HOME", tmpHome)

	profile := "RoundtripTest"
	futureExpiry := time.Now().Add(8 * time.Hour).Format(time.RFC3339)

	creds := &federation.AWSCredentials{
		Version:         1,
		AccessKeyID:     "AKIATEST123456",
		SecretAccessKey: "SecretKeyHere+WithSpecialChars/123",
		SessionToken:    "IQoJb3JpZ2luX2VjEJ3//wEaCXVzLWVhc3QtMSJHMEUCIFake",
		Expiration:      futureExpiry,
	}

	// Write
	if err := SaveToCredentialsFile(creds, profile); err != nil {
		t.Fatalf("SaveToCredentialsFile failed: %v", err)
	}

	// Read back
	readCreds, err := ReadFromCredentialsFile(profile)
	if err != nil {
		t.Fatalf("ReadFromCredentialsFile failed: %v", err)
	}
	if readCreds == nil {
		t.Fatal("ReadFromCredentialsFile returned nil")
	}

	if readCreds.AccessKeyID != creds.AccessKeyID {
		t.Errorf("AccessKeyID mismatch: got %q, want %q", readCreds.AccessKeyID, creds.AccessKeyID)
	}
	if readCreds.SecretAccessKey != creds.SecretAccessKey {
		t.Errorf("SecretAccessKey mismatch: got %q, want %q", readCreds.SecretAccessKey, creds.SecretAccessKey)
	}
	if readCreds.SessionToken != creds.SessionToken {
		t.Errorf("SessionToken mismatch: got %q, want %q", readCreds.SessionToken, creds.SessionToken)
	}
	if readCreds.Expiration != creds.Expiration {
		t.Errorf("Expiration mismatch: got %q, want %q", readCreds.Expiration, creds.Expiration)
	}
}

// TestSessionStorageAtomicOverwrite verifies that overwriting existing
// credentials for the same profile works correctly.
func TestSessionStorageAtomicOverwrite(t *testing.T) {
	tmpHome := t.TempDir()
	t.Setenv("HOME", tmpHome)

	profile := "OverwriteTest"

	// Write initial
	creds1 := &federation.AWSCredentials{
		Version: 1, AccessKeyID: "AKIAFIRST", SecretAccessKey: "first",
		SessionToken: "token1", Expiration: "2030-01-01T00:00:00Z",
	}
	if err := SaveToCredentialsFile(creds1, profile); err != nil {
		t.Fatalf("First write failed: %v", err)
	}

	// Overwrite with new credentials
	creds2 := &federation.AWSCredentials{
		Version: 1, AccessKeyID: "AKIASECOND", SecretAccessKey: "second",
		SessionToken: "token2", Expiration: "2030-06-01T00:00:00Z",
	}
	if err := SaveToCredentialsFile(creds2, profile); err != nil {
		t.Fatalf("Overwrite failed: %v", err)
	}

	// Read should return second creds
	read, err := ReadFromCredentialsFile(profile)
	if err != nil {
		t.Fatalf("Read after overwrite failed: %v", err)
	}
	if read.AccessKeyID != "AKIASECOND" {
		t.Errorf("Expected AKIASECOND after overwrite, got %s", read.AccessKeyID)
	}
}

// TestSessionStorageMultipleProfiles verifies that multiple profiles
// coexist in the same credentials file without interfering.
func TestSessionStorageMultipleProfiles(t *testing.T) {
	tmpHome := t.TempDir()
	t.Setenv("HOME", tmpHome)

	profiles := map[string]*federation.AWSCredentials{
		"ProfileA": {Version: 1, AccessKeyID: "AKIAA", SecretAccessKey: "a", SessionToken: "ta", Expiration: "2030-01-01T00:00:00Z"},
		"ProfileB": {Version: 1, AccessKeyID: "AKIAB", SecretAccessKey: "b", SessionToken: "tb", Expiration: "2030-01-01T00:00:00Z"},
		"ProfileC": {Version: 1, AccessKeyID: "AKIAC", SecretAccessKey: "c", SessionToken: "tc", Expiration: "2030-01-01T00:00:00Z"},
	}

	// Write all
	for name, creds := range profiles {
		if err := SaveToCredentialsFile(creds, name); err != nil {
			t.Fatalf("Write %s failed: %v", name, err)
		}
	}

	// Read each back and verify
	for name, expected := range profiles {
		read, err := ReadFromCredentialsFile(name)
		if err != nil {
			t.Fatalf("Read %s failed: %v", name, err)
		}
		if read == nil {
			t.Fatalf("Read %s returned nil", name)
		}
		if read.AccessKeyID != expected.AccessKeyID {
			t.Errorf("Profile %s: expected AccessKeyID %s, got %s", name, expected.AccessKeyID, read.AccessKeyID)
		}
	}
}

// TestSessionStorageNonExistentProfile returns nil (no error) for missing profiles.
func TestSessionStorageNonExistentProfile(t *testing.T) {
	tmpHome := t.TempDir()
	t.Setenv("HOME", tmpHome)

	creds, err := ReadFromCredentialsFile("DoesNotExist")
	if err != nil {
		t.Fatalf("Expected nil error for missing profile, got: %v", err)
	}
	if creds != nil {
		t.Errorf("Expected nil creds for missing profile, got: %+v", creds)
	}
}

// TestSessionStorageFilePermissions verifies the credentials file has 0600 permissions.
func TestSessionStorageFilePermissions(t *testing.T) {
	tmpHome := t.TempDir()
	t.Setenv("HOME", tmpHome)

	creds := &federation.AWSCredentials{
		Version: 1, AccessKeyID: "AKIAPERMS", SecretAccessKey: "s",
		SessionToken: "t", Expiration: "2030-01-01T00:00:00Z",
	}
	if err := SaveToCredentialsFile(creds, "PermTest"); err != nil {
		t.Fatalf("Write failed: %v", err)
	}

	path := credentialsFilePath()
	info, err := os.Stat(path)
	if err != nil {
		t.Fatalf("Stat failed: %v", err)
	}
	perm := info.Mode().Perm()
	if perm != 0600 {
		t.Errorf("Expected file permissions 0600, got %04o", perm)
	}
}

// TestSessionStorageSpecialCharacters verifies that session tokens with
// special characters (base64, slashes, equals) survive the roundtrip.
func TestSessionStorageSpecialCharacters(t *testing.T) {
	tmpHome := t.TempDir()
	t.Setenv("HOME", tmpHome)

	// Real-world session token format (truncated)
	token := "IQoJb3JpZ2luX2VjEJ///wEaCXVzLWVhc3QtMSJIMEYCIQD+abc/def==ghi"

	creds := &federation.AWSCredentials{
		Version: 1, AccessKeyID: "AKIASPECIAL", SecretAccessKey: "key+with/special=chars",
		SessionToken: token, Expiration: "2030-01-01T00:00:00Z",
	}
	if err := SaveToCredentialsFile(creds, "SpecialChars"); err != nil {
		t.Fatalf("Write failed: %v", err)
	}

	read, err := ReadFromCredentialsFile("SpecialChars")
	if err != nil {
		t.Fatalf("Read failed: %v", err)
	}
	if read.SessionToken != token {
		t.Errorf("Token roundtrip failed:\n  want: %s\n  got:  %s", token, read.SessionToken)
	}
}

// TestParseExpirationSeconds tests various time formats.
func TestParseExpirationSeconds_Formats(t *testing.T) {
	// Standard RFC3339
	future := time.Now().Add(1 * time.Hour).UTC().Format(time.RFC3339)
	s := ParseExpirationSeconds(future)
	if s < 3500 || s > 3700 {
		t.Errorf("RFC3339 format: expected ~3600s, got %.0f", s)
	}

	// With Z suffix (common in AWS responses)
	futureZ := time.Now().Add(1 * time.Hour).UTC().Format("2006-01-02T15:04:05Z")
	s = ParseExpirationSeconds(futureZ)
	if s < 3500 || s > 3700 {
		t.Errorf("Z-suffix format: expected ~3600s, got %.0f", s)
	}

	// Past time → negative
	past := time.Now().Add(-1 * time.Hour).UTC().Format(time.RFC3339)
	s = ParseExpirationSeconds(past)
	if s > 0 {
		t.Errorf("Past time: expected <=0, got %.0f", s)
	}

	// Invalid → 0
	s = ParseExpirationSeconds("not-a-date")
	if s != 0 {
		t.Errorf("Invalid format: expected 0, got %.0f", s)
	}
}

// TestIsExpiredDummyVariants checks various expired placeholder patterns.
func TestIsExpiredDummyVariants(t *testing.T) {
	tests := []struct {
		name     string
		creds    *federation.AWSCredentials
		expected bool
	}{
		{"nil creds", nil, false},
		{"EXPIRED placeholder", &federation.AWSCredentials{AccessKeyID: "EXPIRED"}, true},
		{"valid key", &federation.AWSCredentials{AccessKeyID: "AKIAIOSFODNN7EXAMPLE"}, false},
		{"empty key", &federation.AWSCredentials{AccessKeyID: ""}, false},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if got := IsExpiredDummy(tt.creds); got != tt.expected {
				t.Errorf("IsExpiredDummy() = %v, want %v", got, tt.expected)
			}
		})
	}
}
