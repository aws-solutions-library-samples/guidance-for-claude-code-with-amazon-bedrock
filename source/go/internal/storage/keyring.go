package storage

import (
	"encoding/json"
	"runtime"

	"github.com/99designs/keyring"
	"github.com/bluedoors/ccwb-binaries/internal/federation"
)

const serviceName = "claude-code-with-bedrock"

func openKeyring() (keyring.Keyring, error) {
	return keyring.Open(keyring.Config{
		ServiceName: serviceName,
		// macOS Keychain
		KeychainName:             "login",
		KeychainTrustApplication: true,
		// Linux Secret Service
		LibSecretCollectionName: serviceName,
		// Windows Credential Manager
		WinCredPrefix: serviceName,
	})
}

// ReadFromKeyring reads AWS credentials from the OS keyring.
func ReadFromKeyring(profile string) (*federation.AWSCredentials, error) {
	kr, err := openKeyring()
	if err != nil {
		return nil, err
	}

	if runtime.GOOS == "windows" {
		return readFromKeyringWindows(kr, profile)
	}

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

// SaveToKeyring saves AWS credentials to the OS keyring.
func SaveToKeyring(creds *federation.AWSCredentials, profile string) error {
	kr, err := openKeyring()
	if err != nil {
		return err
	}

	if runtime.GOOS == "windows" {
		return saveToKeyringWindows(kr, creds, profile)
	}

	data, err := json.Marshal(creds)
	if err != nil {
		return err
	}

	return kr.Set(keyring.Item{
		Key:  profile + "-credentials",
		Data: data,
	})
}

// ClearKeyring replaces credentials with an expired dummy to maintain keychain permissions.
func ClearKeyring(profile string) error {
	expired := &federation.AWSCredentials{
		Version:         1,
		AccessKeyID:     "EXPIRED",
		SecretAccessKey: "EXPIRED",
		SessionToken:    "EXPIRED",
		Expiration:      "2000-01-01T00:00:00Z",
	}
	return SaveToKeyring(expired, profile)
}

// ReadMonitoringTokenFromKeyring reads the monitoring token from keyring.
func ReadMonitoringTokenFromKeyring(profile string) (*MonitoringTokenData, error) {
	kr, err := openKeyring()
	if err != nil {
		return nil, err
	}

	item, err := kr.Get(profile + "-monitoring")
	if err != nil {
		return nil, err
	}

	var data MonitoringTokenData
	if err := json.Unmarshal(item.Data, &data); err != nil {
		return nil, err
	}
	return &data, nil
}

// SaveMonitoringTokenToKeyring saves a monitoring token to keyring.
func SaveMonitoringTokenToKeyring(data *MonitoringTokenData, profile string) error {
	kr, err := openKeyring()
	if err != nil {
		return err
	}

	jsonData, err := json.Marshal(data)
	if err != nil {
		return err
	}

	return kr.Set(keyring.Item{
		Key:  profile + "-monitoring",
		Data: jsonData,
	})
}

// MonitoringTokenData represents the monitoring token stored in keyring or file.
type MonitoringTokenData struct {
	Token   string `json:"token"`
	Expires int64  `json:"expires"`
	Email   string `json:"email"`
	Profile string `json:"profile"`
}
