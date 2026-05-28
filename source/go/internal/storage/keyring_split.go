package storage

import (
	"encoding/json"
	"errors"

	"github.com/99designs/keyring"
	"ccwb-go/internal/federation"
)

// Windows Credential Manager has a ~2560 byte UTF-16LE limit.
// Split credentials across 4 entries: keys, token1, token2, meta.

// keyringRW is the minimal subset of keyring.Keyring the Windows read/write
// paths need. Having it as an interface lets unit tests drive the read path
// with a recording mock so they can run on any OS -- the 99designs/keyring
// library panics at import time on Linux without gnome-keyring.
type keyringRW interface {
	Get(key string) (keyring.Item, error)
	Set(item keyring.Item) error
}

func readFromKeyringWindows(kr keyring.Keyring, profile string) (*federation.AWSCredentials, error) {
	return readFromKeyringWindowsImpl(kr, profile)
}

// readFromKeyringWindowsImpl attempts the current 4-entry split format first.
// On a clean "no entries present" miss (ErrKeyNotFound for the -keys entry),
// it falls back to the legacy single-entry {profile}-credentials format that
// predates upstream commit c894546 (Sep 2025). After a successful legacy read
// we opportunistically upconvert to the 4-entry format so subsequent reads go
// through the fast path. Any other error (transport, JSON decode) aborts --
// we don't want to mask genuine failures as "no cache, re-auth".
func readFromKeyringWindowsImpl(kr keyringRW, profile string) (*federation.AWSCredentials, error) {
	keysItem, err := kr.Get(profile + "-keys")
	if err != nil {
		if errors.Is(err, keyring.ErrKeyNotFound) {
			if creds, legacyErr := readFromKeyringWindowsLegacy(kr, profile); legacyErr == nil {
				// Upconvert: best-effort, don't fail the read if the write errors
				_ = saveToKeyringWindowsImpl(kr, creds, profile)
				return creds, nil
			}
			return nil, err
		}
		return nil, err
	}
	token1Item, err := kr.Get(profile + "-token1")
	if err != nil {
		return nil, err
	}
	token2Item, err := kr.Get(profile + "-token2")
	if err != nil {
		return nil, err
	}
	metaItem, err := kr.Get(profile + "-meta")
	if err != nil {
		return nil, err
	}

	var keys struct {
		AccessKeyID     string `json:"AccessKeyId"`
		SecretAccessKey string `json:"SecretAccessKey"`
	}
	if err := json.Unmarshal(keysItem.Data, &keys); err != nil {
		return nil, err
	}

	var meta struct {
		Version    int    `json:"Version"`
		Expiration string `json:"Expiration"`
	}
	if err := json.Unmarshal(metaItem.Data, &meta); err != nil {
		return nil, err
	}

	return &federation.AWSCredentials{
		Version:         meta.Version,
		AccessKeyID:     keys.AccessKeyID,
		SecretAccessKey: keys.SecretAccessKey,
		SessionToken:    string(token1Item.Data) + string(token2Item.Data),
		Expiration:      meta.Expiration,
	}, nil
}

// readFromKeyringWindowsLegacy reads the pre-Sep-2025 Windows format:
// a single entry at {profile}-credentials holding the whole
// federation.AWSCredentials JSON (same layout macOS and Linux still use).
func readFromKeyringWindowsLegacy(kr keyringRW, profile string) (*federation.AWSCredentials, error) {
	item, err := kr.Get(profile + "-credentials")
	if err != nil {
		return nil, err
	}
	var creds federation.AWSCredentials
	if err := json.Unmarshal(item.Data, &creds); err != nil {
		return nil, err
	}
	return &creds, nil
}

func saveToKeyringWindows(kr keyring.Keyring, creds *federation.AWSCredentials, profile string) error {
	return saveToKeyringWindowsImpl(kr, creds, profile)
}

func saveToKeyringWindowsImpl(kr keyringRW, creds *federation.AWSCredentials, profile string) error {
	// Keys
	keysJSON, _ := json.Marshal(map[string]string{
		"AccessKeyId":     creds.AccessKeyID,
		"SecretAccessKey": creds.SecretAccessKey,
	})
	if err := kr.Set(keyring.Item{Key: profile + "-keys", Data: keysJSON}); err != nil {
		return err
	}

	// Split token
	token := creds.SessionToken
	mid := len(token) / 2
	if err := kr.Set(keyring.Item{Key: profile + "-token1", Data: []byte(token[:mid])}); err != nil {
		return err
	}
	if err := kr.Set(keyring.Item{Key: profile + "-token2", Data: []byte(token[mid:])}); err != nil {
		return err
	}

	// Meta
	metaJSON, _ := json.Marshal(map[string]interface{}{
		"Version":    creds.Version,
		"Expiration": creds.Expiration,
	})
	return kr.Set(keyring.Item{Key: profile + "-meta", Data: metaJSON})
}
