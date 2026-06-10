package config

import (
	"path/filepath"
	"testing"
)

// TestHistoricalConfigFixtures verifies that config.json files from every
// historical point between upstream pre-Direct-IAM and our fork HEAD load
// cleanly through the Go credential-process config parser. This is the
// regression gate for customers doing `git pull` + `ccwb package --go`:
// if any old config.json shape breaks loading, their end users can't auth.
//
// Fixtures live under testdata/ and are named after the state they represent.
// Each fixture has ClaudeCode as the sole profile name.
func TestHistoricalConfigFixtures(t *testing.T) {
	tests := []struct {
		fixture      string
		wantRegion   string
		wantProvider string // "" means any provider_type is acceptable
		wantFedType  string
	}{
		// Pre-Direct-IAM fixture has no provider_type -> defaults to "auto";
		// runtime resolveProviderType() in main.go does the okta.com detection.
		{"upstream_pre_direct_iam.json", "us-east-1", "auto", "cognito"},
		{"upstream_post_direct_iam.json", "us-east-1", "okta", "direct"},
		{"upstream_current.json", "us-east-1", "okta", "direct"},
		{"old_format_no_profiles_key.json", "us-east-1", "", "cognito"},
		{"new_format_with_profiles_key.json", "us-east-1", "okta", "direct"},
	}

	for _, tc := range tests {
		t.Run(tc.fixture, func(t *testing.T) {
			path := filepath.Join("testdata", tc.fixture)
			cfg, err := LoadProfileFromPath(path, "ClaudeCode")
			if err != nil {
				t.Fatalf("LoadProfileFromPath(%s) failed: %v", tc.fixture, err)
			}
			if cfg.AWSRegion != tc.wantRegion {
				t.Errorf("AWSRegion = %q, want %q", cfg.AWSRegion, tc.wantRegion)
			}
			if tc.wantProvider != "" && cfg.ProviderType != tc.wantProvider {
				t.Errorf("ProviderType = %q, want %q", cfg.ProviderType, tc.wantProvider)
			}
			if cfg.FederationType != tc.wantFedType {
				t.Errorf("FederationType = %q, want %q", cfg.FederationType, tc.wantFedType)
			}
		})
	}
}

// TestHistoricalConfigFixtures_LegacyFieldMigration asserts the old
// okta_domain / okta_client_id fields map to provider_domain / client_id
// per config.go:102-107. This is the breaking change introduced upstream
// in commit c894546 (Direct IAM federation, Sep 2025) -- any customer on
// a pre-Sep-2025 config must still work end-to-end.
func TestHistoricalConfigFixtures_LegacyFieldMigration(t *testing.T) {
	cfg, err := LoadProfileFromPath("testdata/upstream_pre_direct_iam.json", "ClaudeCode")
	if err != nil {
		t.Fatalf("load failed: %v", err)
	}
	if cfg.ProviderDomain != "dev-12345.okta.com" {
		t.Errorf("ProviderDomain = %q, legacy okta_domain not migrated", cfg.ProviderDomain)
	}
	if cfg.ClientID != "0oa123abc456" {
		t.Errorf("ClientID = %q, legacy okta_client_id not migrated", cfg.ClientID)
	}
}

// TestHistoricalConfigFixtures_AzureFieldsOptional verifies that fixtures
// without the new Azure confidential-client fields load with zero values
// (nil) -- older bundles must remain compatible with the post-Step-1a binary.
func TestHistoricalConfigFixtures_AzureFieldsOptional(t *testing.T) {
	cfg, err := LoadProfileFromPath("testdata/upstream_post_direct_iam.json", "ClaudeCode")
	if err != nil {
		t.Fatalf("load failed: %v", err)
	}
	if cfg.AzureAuthMode != "" {
		t.Errorf("AzureAuthMode = %q, want empty (field absent in fixture)", cfg.AzureAuthMode)
	}
	if cfg.ClientCertificatePath != "" {
		t.Errorf("ClientCertificatePath = %q, want empty", cfg.ClientCertificatePath)
	}
}

// TestHistoricalConfigFixtures_DefaultCredentialStorage ensures an absent
// credential_storage field defaults to "session" (line 121-123) so older
// configs route through the file cache, not the keyring.
func TestHistoricalConfigFixtures_DefaultCredentialStorage(t *testing.T) {
	cfg, err := LoadProfileFromPath("testdata/upstream_pre_direct_iam.json", "ClaudeCode")
	if err != nil {
		t.Fatalf("load failed: %v", err)
	}
	if cfg.CredentialStorage != "session" {
		t.Errorf("CredentialStorage = %q, want session default", cfg.CredentialStorage)
	}
}

// TestGenericOIDCConfig verifies that Generic OIDC fields (used by CyberArk,
// PingFederate, Keycloak, ForgeRock, etc.) parse correctly from config.json.
func TestGenericOIDCConfig(t *testing.T) {
	cfg, err := LoadProfileFromPath("testdata/generic_oidc_cyberark.json", "ClaudeCode")
	if err != nil {
		t.Fatalf("load failed: %v", err)
	}
	if cfg.ProviderType != "generic" {
		t.Errorf("ProviderType = %q, want \"generic\"", cfg.ProviderType)
	}
	if cfg.OIDCIssuerURL != "https://abc1234.id.cyberark.cloud" {
		t.Errorf("OIDCIssuerURL = %q", cfg.OIDCIssuerURL)
	}
	if cfg.OIDCAuthorizationEndpoint != "https://abc1234.id.cyberark.cloud/OAuth2/Authorize/myapp" {
		t.Errorf("OIDCAuthorizationEndpoint = %q", cfg.OIDCAuthorizationEndpoint)
	}
	if cfg.OIDCTokenEndpoint != "https://abc1234.id.cyberark.cloud/OAuth2/Token/myapp" {
		t.Errorf("OIDCTokenEndpoint = %q", cfg.OIDCTokenEndpoint)
	}
	if cfg.OIDCJwksURI != "https://abc1234.id.cyberark.cloud/OAuth2/Keys/myapp" {
		t.Errorf("OIDCJwksURI = %q", cfg.OIDCJwksURI)
	}
	if cfg.OIDCThumbprint != "9e99a48a9960b14926bb7f3b02e22da2b0ab7280" {
		t.Errorf("OIDCThumbprint = %q", cfg.OIDCThumbprint)
	}
	if cfg.RedirectPort != 8401 {
		t.Errorf("RedirectPort = %d, want 8401", cfg.RedirectPort)
	}
	if cfg.CredentialStorage != "keyring" {
		t.Errorf("CredentialStorage = %q, want \"keyring\"", cfg.CredentialStorage)
	}
	if cfg.FederationType != "direct" {
		t.Errorf("FederationType = %q, want \"direct\"", cfg.FederationType)
	}
}
