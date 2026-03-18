package config

import (
	"encoding/json"
	"fmt"
	"net/url"
	"os"
	"path/filepath"
	"strings"
)

// ProfileConfig holds all configuration for a single profile.
type ProfileConfig struct {
	ProviderDomain    string `json:"provider_domain"`
	ClientID          string `json:"client_id"`
	AWSRegion         string `json:"aws_region"`
	CredentialStorage string `json:"credential_storage"`

	// Federation
	FederationType     string `json:"federation_type"`
	FederatedRoleARN   string `json:"federated_role_arn"`
	IdentityPoolID     string `json:"identity_pool_id"`
	IdentityPoolName   string `json:"identity_pool_name"`
	MaxSessionDuration int    `json:"max_session_duration"`

	// Provider
	ProviderType      string `json:"provider_type"`
	CognitoUserPoolID string `json:"cognito_user_pool_id"`

	// Quota
	QuotaAPIEndpoint   string `json:"quota_api_endpoint"`
	QuotaFailMode      string `json:"quota_fail_mode"`
	QuotaCheckInterval int    `json:"quota_check_interval"`
	QuotaCheckTimeout  int    `json:"quota_check_timeout"`

	// Legacy field support
	OktaDomain   string `json:"okta_domain"`
	OktaClientID string `json:"okta_client_id"`

	// Role ARN (for Cognito enhanced flow)
	RoleARN string `json:"role_arn"`
}

// configFile represents the JSON config file structure.
type configFile struct {
	Profiles map[string]json.RawMessage `json:"profiles"`
}

// LoadConfig loads profile configuration from config.json.
func LoadConfig(profileName string, binaryDir string) (*ProfileConfig, error) {
	configPath := findConfigFile(binaryDir)
	if configPath == "" {
		return nil, fmt.Errorf("configuration file not found in binary directory or ~/claude-code-with-bedrock/")
	}

	data, err := os.ReadFile(configPath)
	if err != nil {
		return nil, fmt.Errorf("failed to read config file: %w", err)
	}

	var raw map[string]json.RawMessage
	if err := json.Unmarshal(data, &raw); err != nil {
		return nil, fmt.Errorf("failed to parse config file: %w", err)
	}

	var profileData []byte

	if profilesRaw, ok := raw["profiles"]; ok {
		// New format: {"profiles": {"Name": {...}}}
		var profiles map[string]json.RawMessage
		if err := json.Unmarshal(profilesRaw, &profiles); err != nil {
			return nil, fmt.Errorf("failed to parse profiles: %w", err)
		}
		pd, ok := profiles[profileName]
		if !ok {
			return nil, fmt.Errorf("profile '%s' not found in configuration", profileName)
		}
		profileData = pd
	} else {
		// Legacy format: {"Name": {...}}
		pd, ok := raw[profileName]
		if !ok {
			return nil, fmt.Errorf("profile '%s' not found in configuration", profileName)
		}
		profileData = pd
	}

	var cfg ProfileConfig
	if err := json.Unmarshal(profileData, &cfg); err != nil {
		return nil, fmt.Errorf("failed to parse profile config: %w", err)
	}

	// Migrate legacy fields
	if cfg.ProviderDomain == "" && cfg.OktaDomain != "" {
		cfg.ProviderDomain = cfg.OktaDomain
	}
	if cfg.ClientID == "" && cfg.OktaClientID != "" {
		cfg.ClientID = cfg.OktaClientID
	}

	// Handle identity_pool_name → identity_pool_id (only if not direct STS)
	if cfg.IdentityPoolName != "" && cfg.FederatedRoleARN == "" && cfg.IdentityPoolID == "" {
		cfg.IdentityPoolID = cfg.IdentityPoolName
	}

	// Auto-detect federation type
	detectFederationType(&cfg)

	// Validate required fields
	if err := validateConfig(&cfg); err != nil {
		return nil, err
	}

	// Set defaults
	if cfg.AWSRegion == "" {
		cfg.AWSRegion = "us-east-1"
	}
	if cfg.ProviderType == "" {
		cfg.ProviderType = "auto"
	}
	if cfg.CredentialStorage == "" {
		cfg.CredentialStorage = "session"
	}
	if cfg.MaxSessionDuration == 0 {
		if cfg.FederationType == "direct" {
			cfg.MaxSessionDuration = 43200
		} else {
			cfg.MaxSessionDuration = 28800
		}
	}
	if cfg.QuotaFailMode == "" {
		cfg.QuotaFailMode = "open"
	}
	if cfg.QuotaCheckInterval == 0 {
		cfg.QuotaCheckInterval = 30
	}
	if cfg.QuotaCheckTimeout == 0 {
		cfg.QuotaCheckTimeout = 5
	}

	// Resolve provider type
	if cfg.ProviderType == "auto" {
		pt, err := DetectProviderType(cfg.ProviderDomain)
		if err != nil {
			return nil, err
		}
		cfg.ProviderType = pt
	}

	return &cfg, nil
}

// AutoDetectProfile returns the profile name if exactly one profile exists.
func AutoDetectProfile(binaryDir string) string {
	configPath := findConfigFile(binaryDir)
	if configPath == "" {
		return ""
	}

	data, err := os.ReadFile(configPath)
	if err != nil {
		return ""
	}

	var raw map[string]json.RawMessage
	if err := json.Unmarshal(data, &raw); err != nil {
		return ""
	}

	var profileNames []string

	if profilesRaw, ok := raw["profiles"]; ok {
		var profiles map[string]json.RawMessage
		if err := json.Unmarshal(profilesRaw, &profiles); err != nil {
			return ""
		}
		for k := range profiles {
			profileNames = append(profileNames, k)
		}
	} else {
		for k := range raw {
			profileNames = append(profileNames, k)
		}
	}

	if len(profileNames) == 1 {
		return profileNames[0]
	}
	return ""
}

// DetectProviderType determines the OIDC provider from the domain.
func DetectProviderType(domain string) (string, error) {
	if domain == "" {
		return "", fmt.Errorf("unable to auto-detect provider type for empty domain")
	}

	urlStr := domain
	if !strings.HasPrefix(domain, "http://") && !strings.HasPrefix(domain, "https://") {
		urlStr = "https://" + domain
	}

	u, err := url.Parse(urlStr)
	if err != nil {
		return "", fmt.Errorf("unable to auto-detect provider type for domain '%s': %w", domain, err)
	}

	hostname := strings.ToLower(u.Hostname())
	if hostname == "" {
		return "", fmt.Errorf("unable to auto-detect provider type for domain '%s'", domain)
	}

	switch {
	case strings.HasSuffix(hostname, ".okta.com") || hostname == "okta.com":
		return "okta", nil
	case strings.HasSuffix(hostname, ".auth0.com") || hostname == "auth0.com":
		return "auth0", nil
	case strings.HasSuffix(hostname, ".microsoftonline.com") || hostname == "microsoftonline.com":
		return "azure", nil
	case strings.HasSuffix(hostname, ".windows.net") || hostname == "windows.net":
		return "azure", nil
	case strings.HasSuffix(hostname, ".amazoncognito.com") || hostname == "amazoncognito.com":
		return "cognito", nil
	default:
		return "", fmt.Errorf(
			"unable to auto-detect provider type for domain '%s'. "+
				"Known providers: Okta, Auth0, Microsoft/Azure, AWS Cognito User Pool", domain)
	}
}

func detectFederationType(cfg *ProfileConfig) {
	if cfg.FederationType != "" {
		return
	}
	if cfg.FederatedRoleARN != "" {
		cfg.FederationType = "direct"
	} else if cfg.IdentityPoolID != "" || cfg.IdentityPoolName != "" {
		cfg.FederationType = "cognito"
	} else {
		cfg.FederationType = "cognito"
	}
}

func validateConfig(cfg *ProfileConfig) error {
	var required []string
	if cfg.FederationType == "direct" {
		required = []string{"provider_domain", "client_id", "federated_role_arn"}
	} else {
		required = []string{"provider_domain", "client_id", "identity_pool_id"}
	}

	var missing []string
	for _, field := range required {
		switch field {
		case "provider_domain":
			if cfg.ProviderDomain == "" {
				missing = append(missing, field)
			}
		case "client_id":
			if cfg.ClientID == "" {
				missing = append(missing, field)
			}
		case "federated_role_arn":
			if cfg.FederatedRoleARN == "" {
				missing = append(missing, field)
			}
		case "identity_pool_id":
			if cfg.IdentityPoolID == "" {
				missing = append(missing, field)
			}
		}
	}

	if len(missing) > 0 {
		return fmt.Errorf("missing required configuration: %s", strings.Join(missing, ", "))
	}
	return nil
}

func findConfigFile(binaryDir string) string {
	// Try binary directory first
	if binaryDir != "" {
		p := filepath.Join(binaryDir, "config.json")
		if _, err := os.Stat(p); err == nil {
			return p
		}
	}

	// Fall back to home directory
	home, err := os.UserHomeDir()
	if err != nil {
		return ""
	}
	p := filepath.Join(home, "claude-code-with-bedrock", "config.json")
	if _, err := os.Stat(p); err == nil {
		return p
	}
	return ""
}
