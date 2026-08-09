package storage

import (
	"testing"
)

// TestSaveReadClientSecret is the regression guard for the --set-client-secret
// parity gap: the Go binary had ReadClientSecret but no SaveClientSecret, so
// users on Go-packaged installs could not store a secret without running ccwb init.
//
// Driven through the in-memory mockKeyring so it runs on Linux CI, where
// 99designs/keyring has no Secret Service backend.
func TestSaveReadClientSecret(t *testing.T) {
	kr := newMockKeyring()
	profile := "test-client-secret-profile"

	// Absent secret must return empty string, not an error.
	got, err := readClientSecretImpl(kr, profile)
	if err != nil {
		t.Fatalf("ReadClientSecret on absent key: %v", err)
	}
	if got != "" {
		t.Fatalf("expected empty string for absent secret, got %q", got)
	}

	// Store a secret and read it back.
	const want = "placeholder-not-a-real-secret"
	if err := saveClientSecretImpl(kr, profile, want); err != nil {
		t.Fatalf("SaveClientSecret: %v", err)
	}
	got, err = readClientSecretImpl(kr, profile)
	if err != nil {
		t.Fatalf("ReadClientSecret after save: %v", err)
	}
	if got != want {
		t.Fatalf("round-trip mismatch: got %q, want %q", got, want)
	}

	// Clear the secret (empty input) and confirm it is gone.
	if err := saveClientSecretImpl(kr, profile, ""); err != nil {
		t.Fatalf("SaveClientSecret clear: %v", err)
	}
	got, err = readClientSecretImpl(kr, profile)
	if err != nil {
		t.Fatalf("ReadClientSecret after clear: %v", err)
	}
	if got != "" {
		t.Fatalf("expected empty string after clear, got %q", got)
	}

	// Clearing an already-absent secret must be a no-op, not an error
	// (ErrKeyNotFound from Remove must be swallowed).
	if err := saveClientSecretImpl(kr, profile, ""); err != nil {
		t.Fatalf("SaveClientSecret clear on absent key should be no-op, got: %v", err)
	}
}
