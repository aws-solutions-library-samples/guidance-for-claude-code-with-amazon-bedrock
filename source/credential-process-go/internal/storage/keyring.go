//go:build !windows

package storage

import (
	"encoding/json"
	"fmt"

	"github.com/zalando/go-keyring"
)

const keyringService = "claude-code-with-bedrock"

// KeyringStore implements Store using the OS keyring.
type KeyringStore struct{}

// NewKeyringStore creates a new KeyringStore.
func NewKeyringStore() *KeyringStore {
	return &KeyringStore{}
}

// GetCredentials retrieves credentials from the keyring.
func (k *KeyringStore) GetCredentials(profile string) (*Credentials, error) {
	data, err := keyring.Get(keyringService, profile+"-credentials")
	if err != nil {
		return nil, fmt.Errorf("failed to get credentials from keyring: %w", err)
	}

	var creds Credentials
	if err := json.Unmarshal([]byte(data), &creds); err != nil {
		return nil, fmt.Errorf("failed to parse credentials: %w", err)
	}

	return &creds, nil
}

// SaveCredentials stores credentials in the keyring as JSON.
func (k *KeyringStore) SaveCredentials(profile string, creds *Credentials) error {
	data, err := json.Marshal(creds)
	if err != nil {
		return fmt.Errorf("failed to marshal credentials: %w", err)
	}

	if err := keyring.Set(keyringService, profile+"-credentials", string(data)); err != nil {
		return fmt.Errorf("failed to save credentials to keyring: %w", err)
	}

	return nil
}

// ClearCredentials replaces credentials with expired dummy data in the keyring.
// Does not delete entries to preserve macOS keychain permissions.
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
