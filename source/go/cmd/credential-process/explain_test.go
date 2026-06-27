// ABOUTME: Tests for credential-process --explain flag.
// ABOUTME: Verifies JSON output structure and mode detection for OIDC, IDC, passthrough.

package main

import (
	"encoding/json"
	"testing"

	"ccwb-go/internal/config"
)

func TestExplainOutputOIDC(t *testing.T) {
	cfg := &config.ProfileConfig{
		ProviderDomain:    "company.okta.com",
		ClientID:          "0oatest123",
		ProviderType:      "okta",
		AWSRegion:         "us-west-2",
		CredentialStorage: "keyring",
		IdentityPoolName:  "claude-code-pool",
		QuotaAPIEndpoint:  "https://quota.example.com/check",
	}

	output := buildExplainOutput("TestProfile", cfg)

	if output.Auth.Mode != "oidc" {
		t.Errorf("expected auth mode 'oidc', got '%s'", output.Auth.Mode)
	}
	if output.Provider == nil {
		t.Fatal("expected provider info for OIDC mode")
	}
	if output.Provider.Type != "okta" {
		t.Errorf("expected provider type 'okta', got '%s'", output.Provider.Type)
	}
	if output.Provider.Domain != "company.okta.com" {
		t.Errorf("expected provider domain 'company.okta.com', got '%s'", output.Provider.Domain)
	}
	if output.Quota.AuthMethod != "bearer" {
		t.Errorf("expected quota auth method 'bearer', got '%s'", output.Quota.AuthMethod)
	}
	if output.Auth.FederationType != "cognito" {
		t.Errorf("expected federation type 'cognito', got '%s'", output.Auth.FederationType)
	}
	if !output.Quota.Enabled {
		t.Error("expected quota to be enabled when endpoint is set")
	}
}

func TestExplainOutputIDC(t *testing.T) {
	cfg := &config.ProfileConfig{
		AuthType:             "idc",
		IDCStartURL:          "https://d-123456.awsapps.com/start",
		IDCAccountID:         "123456789012",
		IDCPermissionSetName: "AdministratorAccess",
		AWSRegion:            "us-east-1",
		QuotaAPIEndpoint:     "https://quota.example.com/check",
	}

	output := buildExplainOutput("IDCProfile", cfg)

	if output.Auth.Mode != "idc" {
		t.Errorf("expected auth mode 'idc', got '%s'", output.Auth.Mode)
	}
	if output.Provider != nil {
		t.Error("expected no provider info for IDC mode")
	}
	if output.Quota.AuthMethod != "sigv4" {
		t.Errorf("expected quota auth method 'sigv4', got '%s'", output.Quota.AuthMethod)
	}
	if output.Profile != "IDCProfile" {
		t.Errorf("expected profile 'IDCProfile', got '%s'", output.Profile)
	}
}

func TestExplainOutputPassthrough(t *testing.T) {
	ssoDisabled := false
	cfg := &config.ProfileConfig{
		SsoEnabled: &ssoDisabled,
		AWSRegion:  "eu-west-1",
	}

	output := buildExplainOutput("PassthroughProfile", cfg)

	if output.Auth.Mode != "passthrough" {
		t.Errorf("expected auth mode 'passthrough', got '%s'", output.Auth.Mode)
	}
	if output.Provider != nil {
		t.Error("expected no provider info for passthrough mode")
	}
	if output.Storage.Mode != "keyring" {
		t.Errorf("expected default storage mode 'keyring', got '%s'", output.Storage.Mode)
	}
}

func TestExplainOutputDirectSTS(t *testing.T) {
	cfg := &config.ProfileConfig{
		ProviderDomain:   "login.microsoftonline.com",
		ProviderType:     "azure",
		AWSRegion:        "us-east-1",
		FederatedRoleARN: "arn:aws:iam::123456789012:role/test",
	}

	output := buildExplainOutput("AzureProfile", cfg)

	if output.Auth.FederationType != "direct_sts" {
		t.Errorf("expected federation type 'direct_sts', got '%s'", output.Auth.FederationType)
	}
	if output.Provider.Type != "azure" {
		t.Errorf("expected provider type 'azure', got '%s'", output.Provider.Type)
	}
}

func TestExplainOutputJSONRoundTrip(t *testing.T) {
	cfg := &config.ProfileConfig{
		ProviderDomain:    "auth.example.com",
		ProviderType:      "generic",
		AWSRegion:         "ap-southeast-2",
		CredentialStorage: "file",
		FederatedRoleARN:  "arn:aws:iam::123456789012:role/test",
	}

	output := buildExplainOutput("RoundTrip", cfg)

	data, err := json.Marshal(output)
	if err != nil {
		t.Fatalf("failed to marshal explain output: %v", err)
	}

	var decoded ExplainOutput
	if err := json.Unmarshal(data, &decoded); err != nil {
		t.Fatalf("failed to unmarshal explain output: %v", err)
	}
	if decoded.Auth.Mode != "oidc" {
		t.Errorf("expected auth mode 'oidc' after round-trip, got '%s'", decoded.Auth.Mode)
	}
	if decoded.Storage.Mode != "file" {
		t.Errorf("expected storage mode 'file', got '%s'", decoded.Storage.Mode)
	}
	if decoded.Platform.OS == "" {
		t.Error("expected platform OS to be set")
	}
}

func TestExplainQuotaDisabled(t *testing.T) {
	cfg := &config.ProfileConfig{
		ProviderDomain: "company.okta.com",
		ProviderType:   "okta",
		// No QuotaAPIEndpoint
	}

	output := buildExplainOutput("NoQuota", cfg)

	if output.Quota.Enabled {
		t.Error("expected quota to be disabled when no endpoint configured")
	}
	if output.Quota.Endpoint != "" {
		t.Errorf("expected empty endpoint, got '%s'", output.Quota.Endpoint)
	}
}
