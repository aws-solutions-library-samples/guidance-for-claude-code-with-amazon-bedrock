package storage

import "time"

// Credentials represents AWS credential output format.
type Credentials struct {
	Version        int    `json:"Version"`
	AccessKeyId    string `json:"AccessKeyId"`
	SecretAccessKey string `json:"SecretAccessKey"`
	SessionToken   string `json:"SessionToken"`
	Expiration     string `json:"Expiration"`
}

// MonitoringToken holds monitoring token data.
type MonitoringToken struct {
	Token   string `json:"token"`
	Expires int64  `json:"expires"`
	Email   string `json:"email"`
	Profile string `json:"profile"`
}

// Store interface for credential storage backends.
type Store interface {
	GetCredentials(profile string) (*Credentials, error)
	SaveCredentials(profile string, creds *Credentials) error
	ClearCredentials(profile string) []string
	GetMonitoringToken(profile string) (*MonitoringToken, error)
	SaveMonitoringToken(profile string, token *MonitoringToken) error
	GetQuotaCheckTime(profile string) (string, error)
	SaveQuotaCheckTime(profile string, timestamp string) error
}

// IsExpired checks if credentials are expired (with 30-second buffer).
// Also returns true for dummy "EXPIRED" credentials.
func IsExpired(creds *Credentials) bool {
	if creds == nil {
		return true
	}
	if creds.AccessKeyId == "EXPIRED" {
		return true
	}
	if creds.Expiration == "" {
		return true
	}

	expTime, err := time.Parse(time.RFC3339, creds.Expiration)
	if err != nil {
		return true
	}

	return time.Until(expTime) <= 30*time.Second
}

// IsMonitoringTokenExpired checks if monitoring token is expired (with 600-second buffer).
func IsMonitoringTokenExpired(token *MonitoringToken) bool {
	if token == nil {
		return true
	}
	if token.Token == "EXPIRED" {
		return true
	}

	remaining := token.Expires - time.Now().Unix()
	return remaining <= 600
}
