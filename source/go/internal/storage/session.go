package storage

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/bluedoors/ccwb-binaries/internal/federation"
	"gopkg.in/ini.v1"
)

// ReadFromCredentialsFile reads AWS credentials from ~/.aws/credentials for a profile.
func ReadFromCredentialsFile(profile string) (*federation.AWSCredentials, error) {
	credPath := credentialsFilePath()
	if _, err := os.Stat(credPath); os.IsNotExist(err) {
		return nil, nil
	}

	cfg, err := ini.LoadSources(ini.LoadOptions{
		// Don't interpret # as inline comments (for x-expiration values)
		IgnoreInlineComment: true,
	}, credPath)
	if err != nil {
		return nil, fmt.Errorf("reading credentials file: %w", err)
	}

	sec, err := cfg.GetSection(profile)
	if err != nil {
		return nil, nil // Section doesn't exist
	}

	accessKey := sec.Key("aws_access_key_id").String()
	secretKey := sec.Key("aws_secret_access_key").String()
	token := sec.Key("aws_session_token").String()
	expiration := sec.Key("x-expiration").String()

	if accessKey == "" || secretKey == "" || token == "" {
		return nil, nil
	}

	return &federation.AWSCredentials{
		Version:         1,
		AccessKeyID:     accessKey,
		SecretAccessKey: secretKey,
		SessionToken:    token,
		Expiration:      expiration,
	}, nil
}

// SaveToCredentialsFile writes AWS credentials to ~/.aws/credentials for a profile.
func SaveToCredentialsFile(creds *federation.AWSCredentials, profile string) error {
	credPath := credentialsFilePath()

	// Ensure ~/.aws/ exists
	dir := filepath.Dir(credPath)
	if err := os.MkdirAll(dir, 0700); err != nil {
		return fmt.Errorf("creating .aws directory: %w", err)
	}

	cfg := ini.Empty()
	cfg.ValueMapper = func(s string) string { return s } // Don't interpret values

	// Load existing file
	if _, err := os.Stat(credPath); err == nil {
		existing, err := ini.LoadSources(ini.LoadOptions{
			IgnoreInlineComment: true,
		}, credPath)
		if err == nil {
			cfg = existing
		}
	}

	sec, err := cfg.NewSection(profile)
	if err != nil {
		return fmt.Errorf("creating profile section: %w", err)
	}

	sec.Key("aws_access_key_id").SetValue(creds.AccessKeyID)
	sec.Key("aws_secret_access_key").SetValue(creds.SecretAccessKey)
	sec.Key("aws_session_token").SetValue(creds.SessionToken)
	if creds.Expiration != "" {
		sec.Key("x-expiration").SetValue(creds.Expiration)
	}

	// Atomic write
	tmpPath := credPath + ".tmp"
	if err := cfg.SaveTo(tmpPath); err != nil {
		return fmt.Errorf("writing credentials: %w", err)
	}
	if err := os.Chmod(tmpPath, 0600); err != nil {
		os.Remove(tmpPath)
		return err
	}
	if err := os.Rename(tmpPath, credPath); err != nil {
		os.Remove(tmpPath)
		return err
	}
	return nil
}

func credentialsFilePath() string {
	home, _ := os.UserHomeDir()
	return filepath.Join(home, ".aws", "credentials")
}

// IsExpiredDummy checks if credentials are the "EXPIRED" placeholder.
func IsExpiredDummy(creds *federation.AWSCredentials) bool {
	return creds != nil && creds.AccessKeyID == "EXPIRED"
}

// ParseExpirationSeconds parses an ISO 8601 expiration string and returns
// the number of seconds remaining until expiry. Returns 0 if parsing fails.
func ParseExpirationSeconds(expStr string) float64 {
	if expStr == "" {
		return 0
	}
	expStr = strings.Replace(expStr, "Z", "+00:00", 1)

	t, err := time.Parse(time.RFC3339, expStr)
	if err != nil {
		// Try alternate format
		t, err = time.Parse("2006-01-02T15:04:05+00:00", expStr)
		if err != nil {
			return 0
		}
	}
	return time.Until(t).Seconds()
}
