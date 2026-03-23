package config

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"runtime"
)

// ProfileConfig represents a single profile's configuration from config.json.
type ProfileConfig struct {
	ProviderDomain    string `json:"provider_domain"`
	ClientID          string `json:"client_id"`
	ProviderType      string `json:"provider_type"`
	AWSRegion         string `json:"aws_region"`
	CredentialStorage string `json:"credential_storage"`

	// Federation - Direct STS
	FederatedRoleARN string `json:"federated_role_arn"`
	FederationType   string `json:"federation_type"`

	// Federation - Cognito
	IdentityPoolID    string `json:"identity_pool_id"`
	IdentityPoolName  string `json:"identity_pool_name"`
	CognitoUserPoolID string `json:"cognito_user_pool_id"`
	RoleARN           string `json:"role_arn"`

	// Session
	MaxSessionDuration int `json:"max_session_duration"`

	// Quota
	QuotaAPIEndpoint   string `json:"quota_api_endpoint"`
	QuotaFailMode      string `json:"quota_fail_mode"`
	QuotaCheckInterval int    `json:"quota_check_interval"`
	QuotaCheckTimeout  int    `json:"quota_check_timeout"`

	// Legacy field names
	OktaDomain   string `json:"okta_domain"`
	OktaClientID string `json:"okta_client_id"`
}

// configFile represents the on-disk config.json format.
type configFile struct {
	Profiles map[string]ProfileConfig `json:"profiles"`
}

// LoadProfile loads a named profile from config.json.
// Search order: directory of the running binary, then ~/claude-code-with-bedrock/.
func LoadProfile(profileName string) (*ProfileConfig, error) {
	data, err := readConfigFile()
	if err != nil {
		return nil, err
	}

	var raw map[string]json.RawMessage
	if err := json.Unmarshal(data, &raw); err != nil {
		return nil, fmt.Errorf("invalid config.json: %w", err)
	}

	var profile ProfileConfig

	if _, ok := raw["profiles"]; ok {
		// New format with "profiles" key
		var cf configFile
		if err := json.Unmarshal(data, &cf); err != nil {
			return nil, fmt.Errorf("invalid config.json: %w", err)
		}
		p, ok := cf.Profiles[profileName]
		if !ok {
			return nil, fmt.Errorf("profile %q not found in configuration", profileName)
		}
		profile = p
	} else {
		// Old format: profile names are top-level keys
		profileData, ok := raw[profileName]
		if !ok {
			return nil, fmt.Errorf("profile %q not found in configuration", profileName)
		}
		if err := json.Unmarshal(profileData, &profile); err != nil {
			return nil, fmt.Errorf("invalid profile %q: %w", profileName, err)
		}
	}

	// Map legacy field names
	if profile.ProviderDomain == "" && profile.OktaDomain != "" {
		profile.ProviderDomain = profile.OktaDomain
	}
	if profile.ClientID == "" && profile.OktaClientID != "" {
		profile.ClientID = profile.OktaClientID
	}

	// Handle identity_pool_name -> identity_pool_id (only for Cognito mode)
	if profile.IdentityPoolID == "" && profile.IdentityPoolName != "" && profile.FederatedRoleARN == "" {
		profile.IdentityPoolID = profile.IdentityPoolName
	}

	// Defaults
	if profile.AWSRegion == "" {
		profile.AWSRegion = "us-east-1"
	}
	if profile.ProviderType == "" {
		profile.ProviderType = "auto"
	}
	if profile.CredentialStorage == "" {
		profile.CredentialStorage = "session"
	}

	// Auto-detect federation type
	if profile.FederationType == "" {
		if profile.FederatedRoleARN != "" {
			profile.FederationType = "direct"
		} else {
			profile.FederationType = "cognito"
		}
	}

	if profile.MaxSessionDuration == 0 {
		if profile.FederationType == "direct" {
			profile.MaxSessionDuration = 43200
		} else {
			profile.MaxSessionDuration = 28800
		}
	}

	if profile.QuotaFailMode == "" {
		profile.QuotaFailMode = "open"
	}
	if profile.QuotaCheckInterval == 0 {
		profile.QuotaCheckInterval = 30
	}
	if profile.QuotaCheckTimeout == 0 {
		profile.QuotaCheckTimeout = 5
	}

	return &profile, nil
}

// AutoDetectProfile returns the profile name if config.json has exactly one profile.
func AutoDetectProfile() string {
	data, err := readConfigFile()
	if err != nil {
		return ""
	}

	var raw map[string]json.RawMessage
	if err := json.Unmarshal(data, &raw); err != nil {
		return ""
	}

	if profilesRaw, ok := raw["profiles"]; ok {
		var profiles map[string]json.RawMessage
		if err := json.Unmarshal(profilesRaw, &profiles); err != nil {
			return ""
		}
		if len(profiles) == 1 {
			for name := range profiles {
				return name
			}
		}
		return ""
	}

	// Old format
	if len(raw) == 1 {
		for name := range raw {
			return name
		}
	}
	return ""
}

func readConfigFile() ([]byte, error) {
	// Try binary directory first
	exePath, err := os.Executable()
	if err == nil {
		p := filepath.Join(filepath.Dir(exePath), "config.json")
		if data, err := os.ReadFile(p); err == nil {
			return data, nil
		}
	}

	// Fall back to ~/claude-code-with-bedrock/config.json
	home, err := os.UserHomeDir()
	if err != nil {
		return nil, fmt.Errorf("cannot determine home directory: %w", err)
	}
	p := filepath.Join(home, "claude-code-with-bedrock", "config.json")
	data, err := os.ReadFile(p)
	if err != nil {
		return nil, fmt.Errorf("config.json not found: %w", err)
	}
	return data, nil
}

// CredentialProcessPath returns the expected path to the credential-process binary.
func CredentialProcessPath() string {
	home, err := os.UserHomeDir()
	if err != nil {
		return "credential-process"
	}
	name := "credential-process"
	if runtime.GOOS == "windows" {
		name = "credential-process.exe"
	}
	return filepath.Join(home, "claude-code-with-bedrock", name)
}
