package storage

import (
	"encoding/json"
	"os"
	"path/filepath"
	"time"
)

// GetMonitoringToken retrieves a valid monitoring token from the configured storage.
func GetMonitoringToken(profile, storageType string) (string, error) {
	// Check environment first
	if token := os.Getenv("CLAUDE_CODE_MONITORING_TOKEN"); token != "" {
		return token, nil
	}

	var data *MonitoringTokenData
	var err error

	if storageType == "keyring" {
		data, err = ReadMonitoringTokenFromKeyring(profile)
	} else {
		data, err = readMonitoringTokenFromFile(profile)
	}
	if err != nil || data == nil {
		return "", err
	}

	// Check expiration (10 min buffer)
	now := time.Now().Unix()
	if data.Expires-now <= 600 {
		return "", nil
	}

	return data.Token, nil
}

// SaveMonitoringToken saves the monitoring token to configured storage.
func SaveMonitoringToken(profile, storageType, idToken string, claims map[string]interface{}) error {
	exp := int64(0)
	if v, ok := claims["exp"].(float64); ok {
		exp = int64(v)
	}
	email := ""
	if v, ok := claims["email"].(string); ok {
		email = v
	}

	data := &MonitoringTokenData{
		Token:   idToken,
		Expires: exp,
		Email:   email,
		Profile: profile,
	}

	if storageType == "keyring" {
		return SaveMonitoringTokenToKeyring(data, profile)
	}
	return saveMonitoringTokenToFile(data, profile)
}

func readMonitoringTokenFromFile(profile string) (*MonitoringTokenData, error) {
	home, err := os.UserHomeDir()
	if err != nil {
		return nil, err
	}
	path := filepath.Join(home, ".claude-code-session", profile+"-monitoring.json")
	raw, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	var data MonitoringTokenData
	if err := json.Unmarshal(raw, &data); err != nil {
		return nil, err
	}
	return &data, nil
}

func saveMonitoringTokenToFile(data *MonitoringTokenData, profile string) error {
	home, err := os.UserHomeDir()
	if err != nil {
		return err
	}
	dir := filepath.Join(home, ".claude-code-session")
	if err := os.MkdirAll(dir, 0700); err != nil {
		return err
	}

	raw, err := json.Marshal(data)
	if err != nil {
		return err
	}

	path := filepath.Join(dir, profile+"-monitoring.json")
	if err := os.WriteFile(path, raw, 0600); err != nil {
		return err
	}
	return nil
}
