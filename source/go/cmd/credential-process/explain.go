// ABOUTME: --explain flag implementation for credential-process.
// ABOUTME: Prints resolved configuration as JSON without performing auth.
// ABOUTME: Used for troubleshooting (what mode was detected?) and E2E test oracles.

package main

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"runtime"

	"ccwb-go/internal/config"
	"ccwb-go/internal/provider"
	"ccwb-go/internal/version"
)

// ExplainOutput is the structured JSON output for --explain.
type ExplainOutput struct {
	Version  string        `json:"version"`
	Profile  string        `json:"profile"`
	Platform PlatformInfo  `json:"platform"`
	Auth     AuthInfo      `json:"auth"`
	Provider *ProviderInfo `json:"provider,omitempty"`
	Quota    QuotaInfo     `json:"quota"`
	Storage  StorageInfo   `json:"storage"`
	Paths    PathsInfo     `json:"paths"`
}

// PlatformInfo describes the runtime environment.
type PlatformInfo struct {
	OS   string `json:"os"`
	Arch string `json:"arch"`
}

// AuthInfo describes the resolved authentication mode.
type AuthInfo struct {
	Mode         string `json:"mode"`          // "oidc" | "idc" | "passthrough"
	Reason       string `json:"reason"`        // human-readable explanation of why this mode was chosen
	FederationType string `json:"federation_type,omitempty"` // "cognito" | "direct_sts" | ""
}

// ProviderInfo describes the OIDC identity provider (only for OIDC mode).
type ProviderInfo struct {
	Type   string `json:"type"`             // "okta" | "azure" | "cognito" | "auth0" | "google" | "generic"
	Domain string `json:"domain"`
	Prompt string `json:"prompt,omitempty"` // OIDC prompt parameter
}

// QuotaInfo describes quota enforcement configuration.
type QuotaInfo struct {
	Enabled    bool   `json:"enabled"`
	Endpoint   string `json:"endpoint,omitempty"`
	FailMode   string `json:"fail_mode,omitempty"`   // "open" | "closed"
	AuthMethod string `json:"auth_method,omitempty"` // "bearer" | "sigv4"
}

// StorageInfo describes credential storage configuration.
type StorageInfo struct {
	Mode string `json:"mode"` // "keyring" | "file" | "session"
}

// PathsInfo shows resolved file paths for troubleshooting.
type PathsInfo struct {
	ConfigDir  string `json:"config_dir"`
	ConfigFile string `json:"config_file"`
	InstallDir string `json:"install_dir,omitempty"`
}

// runExplain prints the resolved configuration as JSON and exits 0.
// It never performs authentication or network calls.
func runExplain(profile string, cfg *config.ProfileConfig) {
	output := buildExplainOutput(profile, cfg)

	enc := json.NewEncoder(os.Stdout)
	enc.SetIndent("", "  ")
	if err := enc.Encode(output); err != nil {
		fmt.Fprintf(os.Stderr, "Error encoding explain output: %v\n", err)
		os.Exit(1)
	}
	os.Exit(0)
}

// buildExplainOutput constructs the explain output without side effects.
func buildExplainOutput(profile string, cfg *config.ProfileConfig) ExplainOutput {
	output := ExplainOutput{
		Version: version.Version,
		Profile: profile,
		Platform: PlatformInfo{
			OS:   runtime.GOOS,
			Arch: runtime.GOARCH,
		},
		Storage: StorageInfo{
			Mode: resolveStorageMode(cfg),
		},
		Paths: resolvePaths(profile),
	}

	// Determine auth mode
	switch {
	case cfg.IsIDC():
		output.Auth = AuthInfo{
			Mode:   "idc",
			Reason: "auth_type=idc or IDC fields present (idc_start_url)",
		}
		output.Quota = QuotaInfo{
			Enabled:    cfg.QuotaAPIEndpoint != "",
			Endpoint:   cfg.QuotaAPIEndpoint,
			FailMode:   resolveQuotaFailMode(cfg),
			AuthMethod: "sigv4",
		}
	case !cfg.IsSsoEnabled():
		output.Auth = AuthInfo{
			Mode:   "passthrough",
			Reason: "sso_enabled=false and no IDC fields — using ambient AWS credential chain",
		}
		output.Quota = QuotaInfo{
			Enabled:    cfg.QuotaAPIEndpoint != "",
			Endpoint:   cfg.QuotaAPIEndpoint,
			FailMode:   resolveQuotaFailMode(cfg),
			AuthMethod: "sigv4",
		}
	default:
		provType := resolveProviderTypeQuiet(cfg)
		output.Auth = AuthInfo{
			Mode:           "oidc",
			Reason:         "sso_enabled=true (default) with provider_domain configured",
			FederationType: resolveFederationType(cfg),
		}
		prompt := ""
		if cfg.OIDCPrompt != nil {
			prompt = *cfg.OIDCPrompt
		}
		output.Provider = &ProviderInfo{
			Type:   provType,
			Domain: cfg.ProviderDomain,
			Prompt: prompt,
		}
		output.Quota = QuotaInfo{
			Enabled:    cfg.QuotaAPIEndpoint != "",
			Endpoint:   cfg.QuotaAPIEndpoint,
			FailMode:   resolveQuotaFailMode(cfg),
			AuthMethod: "bearer",
		}
	}

	return output
}

// resolveProviderTypeQuiet detects the provider without printing errors.
func resolveProviderTypeQuiet(cfg *config.ProfileConfig) string {
	if provider.IsKnown(cfg.ProviderType) {
		return cfg.ProviderType
	}
	detected := provider.Detect(cfg.ProviderDomain)
	if detected == "oidc" {
		return "unknown"
	}
	return detected
}

// resolveFederationType returns "cognito" or "direct_sts" based on config.
func resolveFederationType(cfg *config.ProfileConfig) string {
	if cfg.IdentityPoolID != "" || cfg.IdentityPoolName != "" {
		return "cognito"
	}
	if cfg.FederatedRoleARN != "" {
		return "direct_sts"
	}
	// Legacy: check for cognito markers
	if cfg.CognitoUserPoolID != "" {
		return "cognito"
	}
	return ""
}

// resolveStorageMode returns the credential storage mode.
func resolveStorageMode(cfg *config.ProfileConfig) string {
	if cfg.CredentialStorage != "" {
		return cfg.CredentialStorage
	}
	return "keyring" // default
}

// resolveQuotaFailMode returns the quota fail mode (default: open).
func resolveQuotaFailMode(cfg *config.ProfileConfig) string {
	if cfg.QuotaFailMode != "" {
		return cfg.QuotaFailMode
	}
	return "open"
}

// resolvePaths returns the file paths credential-process uses.
func resolvePaths(profile string) PathsInfo {
	info := PathsInfo{}

	// Check for install dir (where binaries live)
	exe, err := os.Executable()
	if err == nil {
		info.InstallDir = filepath.Dir(exe)
		info.ConfigFile = filepath.Join(filepath.Dir(exe), "config.json")
		info.ConfigDir = filepath.Dir(exe)
	}

	// Fallback to ~/claude-code-with-bedrock/
	if info.ConfigFile == "" {
		if home, err := os.UserHomeDir(); err == nil {
			info.ConfigDir = filepath.Join(home, "claude-code-with-bedrock")
			info.ConfigFile = filepath.Join(home, "claude-code-with-bedrock", "config.json")
		}
	}
	return info
}
