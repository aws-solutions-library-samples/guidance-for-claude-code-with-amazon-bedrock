package storage

import (
	"encoding/json"

	"github.com/99designs/keyring"
	"github.com/bluedoors/ccwb-binaries/internal/federation"
)

// Windows Credential Manager has a ~2560 byte UTF-16LE limit.
// Split credentials across 4 entries: keys, token1, token2, meta.

func readFromKeyringWindows(kr keyring.Keyring, profile string) (*federation.AWSCredentials, error) {
	keysItem, err := kr.Get(profile + "-keys")
	if err != nil {
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

func saveToKeyringWindows(kr keyring.Keyring, creds *federation.AWSCredentials, profile string) error {
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
