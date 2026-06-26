package storage

import (
	"testing"
)

// TestSaveReadClientSecret is the regression guard for the --set-client-secret
// parity gap: the Go binary had ReadClientSecret but no SaveClientSecret, so
// users on Go-packaged installs could not store a secret without running ccwb init.
func TestSaveReadClientSecret(t *testing.T) {
	profile := "test-client-secret-profile"

	// Ensure clean state.
	if err := SaveClientSecret(profile, ""); err != nil {
		t.Fatalf("clear before test: %v", err)
	}

	// Absent secret must return empty string, not an error.
	got, err := ReadClientSecret(profile)
	if err != nil {
		t.Fatalf("ReadClientSecret on absent key: %v", err)
	}
	if got != "" {
		t.Fatalf("expected empty string for absent secret, got %q", got)
	}

	// Store a secret and read it back.
	const want = "super-secret-value"
	if err := SaveClientSecret(profile, want); err != nil {
		t.Fatalf("SaveClientSecret: %v", err)
	}
	got, err = ReadClientSecret(profile)
	if err != nil {
		t.Fatalf("ReadClientSecret after save: %v", err)
	}
	if got != want {
		t.Fatalf("round-trip mismatch: got %q, want %q", got, want)
	}

	// Clear the secret and confirm it is gone.
	if err := SaveClientSecret(profile, ""); err != nil {
		t.Fatalf("SaveClientSecret clear: %v", err)
	}
	got, err = ReadClientSecret(profile)
	if err != nil {
		t.Fatalf("ReadClientSecret after clear: %v", err)
	}
	if got != "" {
		t.Fatalf("expected empty string after clear, got %q", got)
	}
}
