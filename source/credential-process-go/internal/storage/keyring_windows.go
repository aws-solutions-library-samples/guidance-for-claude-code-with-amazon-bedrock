//go:build windows

package storage

import (
	"encoding/json"
	"fmt"

	"github.com/zalando/go-keyring"
)

const keyringService = "claude-code-with-bedrock"

// KeyringStore implements Store using the Windows Credential Manager.
// Windows has a 2560-byte limit, so credentials are split across multiple entries.
type KeyringStore struct{}

// NewKeyringStore creates a new KeyringStore.
func NewKeyringStore() *KeyringStore {
	return &KeyringStore{}
}

// keysPayload holds the access key and secret key for split storage.
type keysPayload struct {
	AccessKeyId    string `json:"AccessKeyId"`
	SecretAccessKey string `json:"SecretAccessKey"`
}

// metaPayload holds version and expiration for split storage.
type metaPayload struct {
	Version    int    `json:"Version"`
	Expiration string `json:"Expiration"`
}

// GetCredentials retrieves credentials from the Windows keyring, reassembling split parts.
func (k *KeyringStore) GetCredentials(profile string) (*Credentials, error) {
	// Get keys
	keysData, err := keyring.Get(keyringService, profile+"-keys")
	if err != nil {
		return nil, fmt.Errorf("failed to get keys from keyring: %w", err)
	}
	var keys keysPayload
	if err := json.Unmarshal([]byte(keysData), &keys); err != nil {
		return nil, fmt.Errorf("failed to parse keys: %w", err)
	}

	// Get session token parts
	token1, err := keyring.Get(keyringService, profile+"-token1")
	if err != nil {
		return nil, fmt.Errorf("failed to get token1 from keyring: %w", err)
	}
	token2, err := keyring.Get(keyringService, profile+"-token2")
	if err != nil {
		return nil, fmt.Errorf("failed to get token2 from keyring: %w", err)
	}

	// Get metadata
	metaData, err := keyring.Get(keyringService, profile+"-meta")
	if err != nil {
		return nil, fmt.Errorf("failed to get metadata from keyring: %w", err)
	}
	var meta metaPayload
	if err := json.Unmarshal([]byte(metaData), &meta); err != nil {
		return nil, fmt.Errorf("failed to parse metadata: %w", err)
	}

	creds := &Credentials{
		Version:        meta.Version,
		AccessKeyId:    keys.AccessKeyId,
		SecretAccessKey: keys.SecretAccessKey,
		SessionToken:   token1 + token2,
		Expiration:     meta.Expiration,
	}

	return creds, nil
}

// SaveCredentials stores credentials in the Windows keyring, splitting across multiple entries.
func (k *KeyringStore) SaveCredentials(profile string, creds *Credentials) error {
	// Store keys
	keys := keysPayload{
		AccessKeyId:    creds.AccessKeyId,
		SecretAccessKey: creds.SecretAccessKey,
	}
	keysData, err := json.Marshal(keys)
	if err != nil {
		return fmt.Errorf("failed to marshal keys: %w", err)
	}
	if err := keyring.Set(keyringService, profile+"-keys", string(keysData)); err != nil {
		return fmt.Errorf("failed to save keys to keyring: %w", err)
	}

	// Split and store session token
	token := creds.SessionToken
	mid := len(token) / 2
	token1 := token[:mid]
	token2 := token[mid:]

	if err := keyring.Set(keyringService, profile+"-token1", token1); err != nil {
		return fmt.Errorf("failed to save token1 to keyring: %w", err)
	}
	if err := keyring.Set(keyringService, profile+"-token2", token2); err != nil {
		return fmt.Errorf("failed to save token2 to keyring: %w", err)
	}

	// Store metadata
	meta := metaPayload{
		Version:    creds.Version,
		Expiration: creds.Expiration,
	}
	metaData, err := json.Marshal(meta)
	if err != nil {
		return fmt.Errorf("failed to marshal metadata: %w", err)
	}
	if err := keyring.Set(keyringService, profile+"-meta", string(metaData)); err != nil {
		return fmt.Errorf("failed to save metadata to keyring: %w", err)
	}

	return nil
}

// ClearCredentials replaces credentials with expired dummy data in the keyring.
// Does not delete entries to preserve Windows Credential Manager state.
func (k *KeyringStore) ClearCredentials(profile string) []string {
	var cleared []string

	expiredCreds := &Credentials{
		Version:        1,
		AccessKeyId:    "EXPIRED",
		SecretAccessKey: "EXPIRED",
		SessionToken:   "EXPIRED",
		Expiration:     "2000-01-01T00:00:00Z",
	}

	if err := k.SaveCredentials(profile, expiredCreds); err == nil {
		cleared = append(cleared, "credentials")
	}

	// Clear monitoring token with expired dummy
	expiredToken := &MonitoringToken{
		Token:   "EXPIRED",
		Expires: 0,
	}
	if err := k.SaveMonitoringToken(profile, expiredToken); err == nil {
		cleared = append(cleared, "monitoring token")
	}

	return cleared
}

// GetMonitoringToken retrieves monitoring token from the keyring.
func (k *KeyringStore) GetMonitoringToken(profile string) (*MonitoringToken, error) {
	data, err := keyring.Get(keyringService, profile+"-monitoring")
	if err != nil {
		return nil, fmt.Errorf("failed to get monitoring token from keyring: %w", err)
	}

	var token MonitoringToken
	if err := json.Unmarshal([]byte(data), &token); err != nil {
		return nil, fmt.Errorf("failed to parse monitoring token: %w", err)
	}

	return &token, nil
}

// SaveMonitoringToken stores monitoring token in the keyring as JSON.
func (k *KeyringStore) SaveMonitoringToken(profile string, token *MonitoringToken) error {
	data, err := json.Marshal(token)
	if err != nil {
		return fmt.Errorf("failed to marshal monitoring token: %w", err)
	}

	if err := keyring.Set(keyringService, profile+"-monitoring", string(data)); err != nil {
		return fmt.Errorf("failed to save monitoring token to keyring: %w", err)
	}

	return nil
}

// GetQuotaCheckTime retrieves quota check timestamp from the keyring.
func (k *KeyringStore) GetQuotaCheckTime(profile string) (string, error) {
	timestamp, err := keyring.Get(keyringService, profile+"-quota-check")
	if err != nil {
		return "", fmt.Errorf("failed to get quota check time from keyring: %w", err)
	}

	return timestamp, nil
}

// SaveQuotaCheckTime stores quota check timestamp in the keyring.
func (k *KeyringStore) SaveQuotaCheckTime(profile string, timestamp string) error {
	if err := keyring.Set(keyringService, profile+"-quota-check", timestamp); err != nil {
		return fmt.Errorf("failed to save quota check time to keyring: %w", err)
	}

	return nil
}
