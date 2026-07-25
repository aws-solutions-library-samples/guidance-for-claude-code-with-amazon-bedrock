package storage

import (
	"os"
	"path/filepath"
	"testing"

	"ccwb-go/internal/federation"
)

// makeSessionCreds builds a minimal set of AWS credentials for round-trip tests.
func makeSessionCreds() *federation.AWSCredentials {
	return &federation.AWSCredentials{
		Version:         1,
		AccessKeyID:     "AKIAEXAMPLE797",
		SecretAccessKey: "secret797",
		SessionToken:    "token797",
		Expiration:      "2099-01-01T00:00:00Z",
	}
}

// TestCredentialsFilePath_HonorsEnvVar is the #797 regression guard: when
// AWS_SHARED_CREDENTIALS_FILE is set, the binary must read/write/clear THAT
// file — the same one the AWS SDK resolves credentials from. On the unfixed
// code credentialsFilePath() ignored the env var and always returned
// ~/.aws/credentials, so save/read/remove targeted a file the SDK never read.
func TestCredentialsFilePath_HonorsEnvVar(t *testing.T) {
	custom := filepath.Join(t.TempDir(), "relocated", "credentials")
	t.Setenv("AWS_SHARED_CREDENTIALS_FILE", custom)

	if got := credentialsFilePath(); got != custom {
		t.Fatalf("expected credentialsFilePath to honor env var\n got: %s\nwant: %s", got, custom)
	}
}

// TestCredentialsFilePath_FallsBackWhenUnset guards the additive contract:
// with the env var unset the resolved path must be byte-identical to today's
// behavior (~/.aws/credentials under the user home). This is what makes the
// change safe for every existing install (none of which set the env var).
func TestCredentialsFilePath_FallsBackWhenUnset(t *testing.T) {
	// Ensure the var is not inherited from the ambient environment.
	t.Setenv("AWS_SHARED_CREDENTIALS_FILE", "")
	os.Unsetenv("AWS_SHARED_CREDENTIALS_FILE")

	home, _ := os.UserHomeDir()
	want := filepath.Join(home, ".aws", "credentials")
	if got := credentialsFilePath(); got != want {
		t.Fatalf("expected fallback to home path\n got: %s\nwant: %s", got, want)
	}
}

// isolateHome points HOME/USERPROFILE at a fresh temp dir so a fail-without-fix
// run (where credentialsFilePath falls back to the home path) cannot touch the
// developer's real ~/.aws/credentials. Returns the temp home for assertions.
func isolateHome(t *testing.T) string {
	t.Helper()
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home) // Windows
	return home
}

// TestSessionRoundTrip_CustomPath exercises the full save -> read -> remove
// cycle against a relocated credentials file, including auto-creating the
// parent directory. This mirrors the customer's C:\ProgramData\.aws\credentials
// scenario (env var pointing outside the user home).
func TestSessionRoundTrip_CustomPath(t *testing.T) {
	isolateHome(t)
	custom := filepath.Join(t.TempDir(), "programdata", ".aws", "credentials")
	t.Setenv("AWS_SHARED_CREDENTIALS_FILE", custom)

	const profile = "ClaudeCode"
	creds := makeSessionCreds()

	// Save must create the parent directory and write to the custom path.
	if err := SaveToCredentialsFile(creds, profile); err != nil {
		t.Fatalf("SaveToCredentialsFile: %v", err)
	}
	if _, err := os.Stat(custom); err != nil {
		t.Fatalf("expected credentials written to custom path, stat failed: %v", err)
	}

	// Read must return the same credentials from the custom path.
	got, err := ReadFromCredentialsFile(profile)
	if err != nil {
		t.Fatalf("ReadFromCredentialsFile: %v", err)
	}
	if got == nil || got.AccessKeyID != creds.AccessKeyID || got.SessionToken != creds.SessionToken {
		t.Fatalf("read-back credentials mismatch: %+v", got)
	}

	// Remove must clear the section from the custom path — this is the recovery
	// that un-wedges the SDK once a stale session block expires. On the unfixed
	// code it operated on ~/.aws/credentials and never touched the SDK's file.
	if err := RemoveFromCredentialsFile(profile); err != nil {
		t.Fatalf("RemoveFromCredentialsFile: %v", err)
	}
	after, err := ReadFromCredentialsFile(profile)
	if err != nil {
		t.Fatalf("ReadFromCredentialsFile after remove: %v", err)
	}
	if after != nil {
		t.Fatalf("expected section cleared from custom path, got: %+v", after)
	}
}

// TestSession_HomeFileUntouchedWhenEnvSet is the divergence guard: with
// AWS_SHARED_CREDENTIALS_FILE set, save and remove must operate ONLY on the
// relocated file and must NOT touch ~/.aws/credentials. This pins the exact
// #797 defect (binary writes/clears file A while the SDK reads file B). On the
// unfixed code save would write the home path, so the pre-seeded home block
// would be overwritten and this fails.
func TestSession_HomeFileUntouchedWhenEnvSet(t *testing.T) {
	home := isolateHome(t)
	homeCreds := filepath.Join(home, ".aws", "credentials")
	if err := os.MkdirAll(filepath.Dir(homeCreds), 0700); err != nil {
		t.Fatalf("mkdir home .aws: %v", err)
	}
	// Seed a distinct sentinel block at the home path.
	const sentinel = "[ClaudeCode]\naws_access_key_id = HOME_SENTINEL\naws_secret_access_key = s\naws_session_token = t\n"
	if err := os.WriteFile(homeCreds, []byte(sentinel), 0600); err != nil {
		t.Fatalf("seed home creds: %v", err)
	}

	custom := filepath.Join(t.TempDir(), "programdata", ".aws", "credentials")
	t.Setenv("AWS_SHARED_CREDENTIALS_FILE", custom)

	// Save then remove against the relocated path.
	if err := SaveToCredentialsFile(makeSessionCreds(), "ClaudeCode"); err != nil {
		t.Fatalf("SaveToCredentialsFile: %v", err)
	}
	if err := RemoveFromCredentialsFile("ClaudeCode"); err != nil {
		t.Fatalf("RemoveFromCredentialsFile: %v", err)
	}

	// The home file must be byte-for-byte unchanged.
	got, err := os.ReadFile(homeCreds)
	if err != nil {
		t.Fatalf("read home creds: %v", err)
	}
	if string(got) != sentinel {
		t.Fatalf("home credentials file was modified when env var pointed elsewhere\ngot:\n%s", got)
	}
}

// TestSessionRead_NonexistentCustomPath confirms a missing relocated file is
// treated as "no credentials" (nil, nil) rather than an error — matching the
// existing IDC tests that point the env var at a noexist path.
func TestSessionRead_NonexistentCustomPath(t *testing.T) {
	custom := filepath.Join(t.TempDir(), "noexist", "credentials")
	t.Setenv("AWS_SHARED_CREDENTIALS_FILE", custom)

	got, err := ReadFromCredentialsFile("ClaudeCode")
	if err != nil {
		t.Fatalf("expected nil error for missing file, got: %v", err)
	}
	if got != nil {
		t.Fatalf("expected nil credentials for missing file, got: %+v", got)
	}
}
