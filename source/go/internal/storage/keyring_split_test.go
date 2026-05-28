package storage

import (
	"encoding/json"
	"errors"
	"testing"

	"github.com/99designs/keyring"
	"ccwb-go/internal/federation"
)

// mockKeyring is a keyringRW implementation backed by an in-memory map.
// It records every Set call so tests can assert on upconvert writes, and
// returns keyring.ErrKeyNotFound for missing keys (matching the real library).
type mockKeyring struct {
	store       map[string][]byte
	setCalls    []keyring.Item
	failSet     bool
	failSetKey  string
	getErrOverride map[string]error
}

func newMockKeyring() *mockKeyring {
	return &mockKeyring{store: map[string][]byte{}, getErrOverride: map[string]error{}}
}

func (m *mockKeyring) Get(key string) (keyring.Item, error) {
	if err, ok := m.getErrOverride[key]; ok {
		return keyring.Item{}, err
	}
	data, ok := m.store[key]
	if !ok {
		return keyring.Item{}, keyring.ErrKeyNotFound
	}
	return keyring.Item{Key: key, Data: data}, nil
}

func (m *mockKeyring) Set(item keyring.Item) error {
	if m.failSet || (m.failSetKey != "" && item.Key == m.failSetKey) {
		return errors.New("mock set failure")
	}
	m.store[item.Key] = item.Data
	m.setCalls = append(m.setCalls, item)
	return nil
}

// seedNew populates the 4-entry split format.
func seedNew(m *mockKeyring, profile string, creds *federation.AWSCredentials) {
	keysJSON, _ := json.Marshal(map[string]string{
		"AccessKeyId":     creds.AccessKeyID,
		"SecretAccessKey": creds.SecretAccessKey,
	})
	m.store[profile+"-keys"] = keysJSON
	token := creds.SessionToken
	mid := len(token) / 2
	m.store[profile+"-token1"] = []byte(token[:mid])
	m.store[profile+"-token2"] = []byte(token[mid:])
	metaJSON, _ := json.Marshal(map[string]interface{}{
		"Version":    creds.Version,
		"Expiration": creds.Expiration,
	})
	m.store[profile+"-meta"] = metaJSON
}

// seedLegacy populates the pre-Sep-2025 single-entry format.
func seedLegacy(m *mockKeyring, profile string, creds *federation.AWSCredentials) {
	data, _ := json.Marshal(creds)
	m.store[profile+"-credentials"] = data
}

func sampleCreds() *federation.AWSCredentials {
	return &federation.AWSCredentials{
		Version:         1,
		AccessKeyID:     "AKIAEXAMPLE",
		SecretAccessKey: "secret-example-value",
		SessionToken:    "this-is-a-session-token-longer-than-any-sensible-limit-of-length",
		Expiration:      "2026-06-01T00:00:00Z",
	}
}

func TestReadWindowsKeyring_NewFormat(t *testing.T) {
	m := newMockKeyring()
	seedNew(m, "p1", sampleCreds())

	creds, err := readFromKeyringWindowsImpl(m, "p1")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if creds.AccessKeyID != "AKIAEXAMPLE" {
		t.Errorf("AccessKeyID = %q", creds.AccessKeyID)
	}
	if creds.SessionToken != sampleCreds().SessionToken {
		t.Errorf("SessionToken mismatch")
	}
	// Must not touch legacy key
	if _, ok := m.store["p1-credentials"]; ok {
		t.Error("should not have read or written legacy key")
	}
	// Must not have written anything (read-only hit on new format)
	if len(m.setCalls) != 0 {
		t.Errorf("expected 0 Set calls, got %d", len(m.setCalls))
	}
}

func TestReadWindowsKeyring_LegacyFormat(t *testing.T) {
	m := newMockKeyring()
	seedLegacy(m, "p1", sampleCreds())

	creds, err := readFromKeyringWindowsImpl(m, "p1")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if creds.AccessKeyID != "AKIAEXAMPLE" {
		t.Errorf("AccessKeyID = %q", creds.AccessKeyID)
	}
	if creds.SessionToken != sampleCreds().SessionToken {
		t.Errorf("SessionToken mismatch")
	}
	if creds.Expiration != "2026-06-01T00:00:00Z" {
		t.Errorf("Expiration = %q", creds.Expiration)
	}
}

func TestReadWindowsKeyring_UpconvertOnRead(t *testing.T) {
	m := newMockKeyring()
	seedLegacy(m, "p1", sampleCreds())

	_, err := readFromKeyringWindowsImpl(m, "p1")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	// Expect exactly 4 Set calls for the upconvert
	if len(m.setCalls) != 4 {
		t.Fatalf("expected 4 Set calls, got %d", len(m.setCalls))
	}
	wantKeys := map[string]bool{
		"p1-keys":   true,
		"p1-token1": true,
		"p1-token2": true,
		"p1-meta":   true,
	}
	for _, call := range m.setCalls {
		if !wantKeys[call.Key] {
			t.Errorf("unexpected Set key: %q", call.Key)
		}
	}
}

func TestReadWindowsKeyring_LegacyCorrupt(t *testing.T) {
	m := newMockKeyring()
	m.store["p1-credentials"] = []byte("not valid json")

	_, err := readFromKeyringWindowsImpl(m, "p1")
	if err == nil {
		t.Fatal("expected error for corrupt legacy JSON")
	}
	// The returned error should be the original ErrKeyNotFound from -keys, not
	// a JSON error -- we treat the legacy fallback as best-effort and surface
	// the primary-path error so the caller knows to re-auth.
	if !errors.Is(err, keyring.ErrKeyNotFound) {
		t.Errorf("expected ErrKeyNotFound, got %T: %v", err, err)
	}
}

func TestReadWindowsKeyring_NoEntriesAnywhere(t *testing.T) {
	m := newMockKeyring()

	_, err := readFromKeyringWindowsImpl(m, "p1")
	if err == nil {
		t.Fatal("expected error")
	}
	if !errors.Is(err, keyring.ErrKeyNotFound) {
		t.Errorf("expected ErrKeyNotFound, got %T: %v", err, err)
	}
	if len(m.setCalls) != 0 {
		t.Errorf("no entries should mean no writes; got %d Set calls", len(m.setCalls))
	}
}

func TestReadWindowsKeyring_PartialNewFormat(t *testing.T) {
	// -keys present but -token1 missing. Should NOT fall through to legacy --
	// that would mask a genuine keyring corruption (a write that partially
	// succeeded). Surface the ErrKeyNotFound on -token1.
	m := newMockKeyring()
	keysJSON, _ := json.Marshal(map[string]string{
		"AccessKeyId":     "AKIAEXAMPLE",
		"SecretAccessKey": "secret",
	})
	m.store["p1-keys"] = keysJSON
	// token1/token2/meta deliberately absent
	// Also seed legacy to prove we do NOT fall through to it
	seedLegacy(m, "p1", sampleCreds())

	creds, err := readFromKeyringWindowsImpl(m, "p1")
	if err == nil {
		t.Fatalf("expected error for partial new format, got creds: %+v", creds)
	}
	if !errors.Is(err, keyring.ErrKeyNotFound) {
		t.Errorf("expected ErrKeyNotFound, got %T: %v", err, err)
	}
}

func TestReadWindowsKeyring_UpconvertWriteFailureStillReturnsCreds(t *testing.T) {
	// Legacy read succeeds but the upconvert Set fails. The caller should
	// still get usable credentials -- upconvert is opportunistic, not required.
	m := newMockKeyring()
	seedLegacy(m, "p1", sampleCreds())
	m.failSet = true

	creds, err := readFromKeyringWindowsImpl(m, "p1")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if creds.AccessKeyID != "AKIAEXAMPLE" {
		t.Errorf("AccessKeyID = %q", creds.AccessKeyID)
	}
}

func TestReadWindowsKeyring_TransportErrorOnKeysPropagates(t *testing.T) {
	// A non-ErrKeyNotFound error on -keys must NOT trigger legacy fallback.
	// We don't want to mask real transport/permissions errors.
	m := newMockKeyring()
	seedLegacy(m, "p1", sampleCreds())
	transportErr := errors.New("wincred access denied")
	m.getErrOverride["p1-keys"] = transportErr

	_, err := readFromKeyringWindowsImpl(m, "p1")
	if err == nil {
		t.Fatal("expected transport error to propagate")
	}
	if err != transportErr {
		t.Errorf("expected the exact transport error, got %v", err)
	}
	// Legacy must not have been read
	if len(m.setCalls) != 0 {
		t.Errorf("no upconvert should have happened on transport error; got %d Set calls", len(m.setCalls))
	}
}
