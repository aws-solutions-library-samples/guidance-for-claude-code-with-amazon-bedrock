package storage

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"

	"gopkg.in/ini.v1"
)

// SessionStore implements Store using session files.
type SessionStore struct{}

// NewSessionStore creates a new SessionStore.
func NewSessionStore() *SessionStore {
	return &SessionStore{}
}

func awsCredentialsPath() string {
	home, _ := os.UserHomeDir()
	return filepath.Join(home, ".aws", "credentials")
}

func sessionDir() string {
	home, _ := os.UserHomeDir()
	return filepath.Join(home, ".claude-code-session")
}

func ensureSessionDir() error {
	dir := sessionDir()
	return os.MkdirAll(dir, 0700)
}

// GetCredentials reads credentials from ~/.aws/credentials INI file.
func (s *SessionStore) GetCredentials(profile string) (*Credentials, error) {
	credPath := awsCredentialsPath()

	cfg, err := ini.Load(credPath)
	if err != nil {
		return nil, fmt.Errorf("failed to load credentials file: %w", err)
	}

	section, err := cfg.GetSection(profile)
	if err != nil {
		return nil, fmt.Errorf("profile '%s' not found in credentials file", profile)
	}

	creds := &Credentials{
		Version:        1,
		AccessKeyId:    section.Key("aws_access_key_id").String(),
		SecretAccessKey: section.Key("aws_secret_access_key").String(),
		SessionToken:   section.Key("aws_session_token").String(),
		Expiration:     section.Key("x-expiration").String(),
	}

	return creds, nil
}

// SaveCredentials writes credentials to ~/.aws/credentials INI file atomically.
func (s *SessionStore) SaveCredentials(profile string, creds *Credentials) error {
	credPath := awsCredentialsPath()

	// Ensure directory exists
	if err := os.MkdirAll(filepath.Dir(credPath), 0700); err != nil {
		return fmt.Errorf("failed to create .aws directory: %w", err)
	}

	// Load existing or create new
	cfg, err := ini.Load(credPath)
	if err != nil {
		cfg = ini.Empty()
	}

	section, err := cfg.GetSection(profile)
	if err != nil {
		section, err = cfg.NewSection(profile)
		if err != nil {
			return fmt.Errorf("failed to create profile section: %w", err)
		}
	}

	section.Key("aws_access_key_id").SetValue(creds.AccessKeyId)
	section.Key("aws_secret_access_key").SetValue(creds.SecretAccessKey)
	section.Key("aws_session_token").SetValue(creds.SessionToken)
	section.Key("x-expiration").SetValue(creds.Expiration)

	// Atomic write: temp file, chmod, rename
	tmpFile, err := os.CreateTemp(filepath.Dir(credPath), ".credentials-tmp-*")
	if err != nil {
		return fmt.Errorf("failed to create temp file: %w", err)
	}
	tmpPath := tmpFile.Name()

	if _, err := cfg.WriteTo(tmpFile); err != nil {
		tmpFile.Close()
		os.Remove(tmpPath)
		return fmt.Errorf("failed to write credentials: %w", err)
	}
	tmpFile.Close()

	if err := os.Chmod(tmpPath, 0600); err != nil {
		os.Remove(tmpPath)
		return fmt.Errorf("failed to set file permissions: %w", err)
	}

	if err := os.Rename(tmpPath, credPath); err != nil {
		os.Remove(tmpPath)
		return fmt.Errorf("failed to rename temp file: %w", err)
	}

	return nil
}

// ClearCredentials writes expired dummy credentials and removes monitoring file.
func (s *SessionStore) ClearCredentials(profile string) []string {
	var cleared []string

	expiredCreds := &Credentials{
		Version:        1,
		AccessKeyId:    "EXPIRED",
		SecretAccessKey: "EXPIRED",
		SessionToken:   "EXPIRED",
		Expiration:     "2000-01-01T00:00:00Z",
	}

	if err := s.SaveCredentials(profile, expiredCreds); err == nil {
		cleared = append(cleared, "credentials")
	}

	// Delete monitoring token file
	monPath := filepath.Join(sessionDir(), profile+"-monitoring.json")
	if err := os.Remove(monPath); err == nil {
		cleared = append(cleared, "monitoring token")
	}

	return cleared
}

// GetMonitoringToken reads monitoring token from session directory.
func (s *SessionStore) GetMonitoringToken(profile string) (*MonitoringToken, error) {
	if err := ensureSessionDir(); err != nil {
		return nil, err
	}

	monPath := filepath.Join(sessionDir(), profile+"-monitoring.json")
	data, err := os.ReadFile(monPath)
	if err != nil {
		return nil, fmt.Errorf("failed to read monitoring token: %w", err)
	}

	var token MonitoringToken
	if err := json.Unmarshal(data, &token); err != nil {
		return nil, fmt.Errorf("failed to parse monitoring token: %w", err)
	}

	return &token, nil
}

// SaveMonitoringToken writes monitoring token to session directory atomically.
func (s *SessionStore) SaveMonitoringToken(profile string, token *MonitoringToken) error {
	if err := ensureSessionDir(); err != nil {
		return err
	}

	data, err := json.Marshal(token)
	if err != nil {
		return fmt.Errorf("failed to marshal monitoring token: %w", err)
	}

	monPath := filepath.Join(sessionDir(), profile+"-monitoring.json")
	tmpFile, err := os.CreateTemp(sessionDir(), ".monitoring-tmp-*")
	if err != nil {
		return fmt.Errorf("failed to create temp file: %w", err)
	}
	tmpPath := tmpFile.Name()

	if _, err := tmpFile.Write(data); err != nil {
		tmpFile.Close()
		os.Remove(tmpPath)
		return fmt.Errorf("failed to write monitoring token: %w", err)
	}
	tmpFile.Close()

	if err := os.Chmod(tmpPath, 0600); err != nil {
		os.Remove(tmpPath)
		return fmt.Errorf("failed to set file permissions: %w", err)
	}

	if err := os.Rename(tmpPath, monPath); err != nil {
		os.Remove(tmpPath)
		return fmt.Errorf("failed to rename temp file: %w", err)
	}

	return nil
}

// GetQuotaCheckTime reads the last quota check timestamp from session directory.
func (s *SessionStore) GetQuotaCheckTime(profile string) (string, error) {
	if err := ensureSessionDir(); err != nil {
		return "", err
	}

	quotaPath := filepath.Join(sessionDir(), profile+"-quota-check.json")
	data, err := os.ReadFile(quotaPath)
	if err != nil {
		return "", fmt.Errorf("failed to read quota check time: %w", err)
	}

	var result struct {
		LastCheck string `json:"last_check"`
	}
	if err := json.Unmarshal(data, &result); err != nil {
		return "", fmt.Errorf("failed to parse quota check time: %w", err)
	}

	return result.LastCheck, nil
}

// SaveQuotaCheckTime writes the quota check timestamp to session directory atomically.
func (s *SessionStore) SaveQuotaCheckTime(profile string, timestamp string) error {
	if err := ensureSessionDir(); err != nil {
		return err
	}

	payload := struct {
		LastCheck string `json:"last_check"`
	}{LastCheck: timestamp}

	data, err := json.Marshal(payload)
	if err != nil {
		return fmt.Errorf("failed to marshal quota check time: %w", err)
	}

	quotaPath := filepath.Join(sessionDir(), profile+"-quota-check.json")
	tmpFile, err := os.CreateTemp(sessionDir(), ".quota-tmp-*")
	if err != nil {
		return fmt.Errorf("failed to create temp file: %w", err)
	}
	tmpPath := tmpFile.Name()

	if _, err := tmpFile.Write(data); err != nil {
		tmpFile.Close()
		os.Remove(tmpPath)
		return fmt.Errorf("failed to write quota check time: %w", err)
	}
	tmpFile.Close()

	if err := os.Chmod(tmpPath, 0600); err != nil {
		os.Remove(tmpPath)
		return fmt.Errorf("failed to set file permissions: %w", err)
	}

	if err := os.Rename(tmpPath, quotaPath); err != nil {
		os.Remove(tmpPath)
		return fmt.Errorf("failed to rename temp file: %w", err)
	}

	return nil
}
