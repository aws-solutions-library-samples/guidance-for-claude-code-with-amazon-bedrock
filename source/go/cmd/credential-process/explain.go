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
	Version    string          `json:"version"`
	Commit     string          `json:"commit"`
	Profile    string          `json:"profile"`
	Platform   PlatformInfo    `json:"platform"`
	Auth       AuthInfo        `json:"auth"`
	Provider   *ProviderInfo   `json:"provider,omitempty"`
	Monitoring MonitoringInfo  `json:"monitoring"`
	Quota      QuotaInfo       `json:"quota"`
	Storage    StorageInfo     `json:"storage"`
	Session    SessionInfo     `json:"session"`
	Env        EnvInfo         `json:"env"`
	Paths      PathsInfo       `json:"paths"`
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

// MonitoringInfo describes telemetry collection configuration.
type MonitoringInfo struct {
	Enabled          bool   `json:"enabled"`
	Mode             string `json:"mode"`                        // "central" | "sidecar" | "none"
	Endpoint         string `json:"endpoint,omitempty"`          // OTEL collector endpoint
	ConfigDelivery   string `json:"config_delivery"`             // "static" | "bootstrap"
	BootstrapEndpoint string `json:"bootstrap_endpoint,omitempty"` // Lambda URL (if bootstrap)
}

// StorageInfo describes credential storage configuration.
type StorageInfo struct {
	Mode string `json:"mode"` // "keyring" | "file" | "session"
}

// SessionInfo describes session parameters that affect credential behavior.
type SessionInfo struct {
	MaxDurationSec int    `json:"max_duration_sec,omitempty"` // STS session length
	RedirectPort   int    `json:"redirect_port"`              // OAuth callback port (default 8400)
	AzureAuthMode  string `json:"azure_auth_mode,omitempty"`  // "" | "secret" | "certificate"
	HelperContext  string `json:"helper_context,omitempty"`   // CLAUDE_HELPER_CONTEXT env value
}

// EnvInfo captures relevant environment variables that override behavior.
type EnvInfo struct {
	CCWBProfile       string `json:"ccwb_profile,omitempty"`        // CCWB_PROFILE override
	AWSProfile        string `json:"aws_profile,omitempty"`         // AWS_PROFILE
	RedirectPort      string `json:"redirect_port,omitempty"`       // REDIRECT_PORT override
	DebugEnabled      bool   `json:"debug_enabled"`                 // COGNITO_AUTH_DEBUG=1
	NoBrowserNotify   bool   `json:"no_browser_notification"`       // CCWB_NO_BROWSER_NOTIFICATION=1
	IsSSH             bool   `json:"is_ssh"`                        // SSH_CONNECTION detected
	IsHeadless        bool   `json:"is_headless"`                   // No DISPLAY/WAYLAND_DISPLAY
	BrowserOverride   string `json:"browser_override,omitempty"`    // $BROWSER env
	MonitoringToken   bool   `json:"has_monitoring_token"`          // CLAUDE_CODE_MONITORING_TOKEN set
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
		Commit:  version.Commit,
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

	// Resolve monitoring configuration
	output.Monitoring = resolveMonitoring(cfg)

	// Resolve session parameters
	output.Session = resolveSession(cfg)

	// Resolve environment detection
	output.Env = resolveEnv()

	return output
}

// resolveMonitoring returns the monitoring configuration from the profile.
func resolveMonitoring(cfg *config.ProfileConfig) MonitoringInfo {
	info := MonitoringInfo{
		Enabled:        cfg.MonitoringEnabled,
		Mode:           "none",
		ConfigDelivery: "static",
	}

	if !cfg.MonitoringEnabled {
		return info
	}

	// Monitoring mode
	if cfg.MonitoringMode != "" {
		info.Mode = cfg.MonitoringMode
	} else {
		info.Mode = "central" // default
	}

	// OTEL collector endpoint
	if cfg.OtelCollectorEndpoint != "" {
		info.Endpoint = cfg.OtelCollectorEndpoint
	}

	// Bootstrap server (dynamic config delivery)
	if cfg.ConfigDeliveryMode != "" {
		info.ConfigDelivery = cfg.ConfigDeliveryMode
	}
	if cfg.BootstrapEndpoint != "" {
		info.BootstrapEndpoint = cfg.BootstrapEndpoint
		if info.ConfigDelivery == "static" {
			info.ConfigDelivery = "bootstrap" // infer from presence of endpoint
		}
	}

	return info
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

// resolveSession returns session parameters from the config.
func resolveSession(cfg *config.ProfileConfig) SessionInfo {
	info := SessionInfo{
		RedirectPort: 8400, // default
	}
	if cfg.MaxSessionDuration > 0 {
		info.MaxDurationSec = cfg.MaxSessionDuration
	}
	if cfg.RedirectPort > 0 {
		info.RedirectPort = cfg.RedirectPort
	}
	// Env override for redirect port
	if envPort := os.Getenv("REDIRECT_PORT"); envPort != "" {
		info.RedirectPort = 0 // will be overridden at runtime
	}
	if cfg.AzureAuthMode != "" {
		info.AzureAuthMode = cfg.AzureAuthMode
	}
	// Claude Desktop helper context
	if ctx := os.Getenv("CLAUDE_HELPER_CONTEXT"); ctx != "" {
		info.HelperContext = ctx
	}
	return info
}

// resolveEnv captures environment variables that affect runtime behavior.
func resolveEnv() EnvInfo {
	info := EnvInfo{}

	// Profile overrides
	info.CCWBProfile = os.Getenv("CCWB_PROFILE")
	info.AWSProfile = os.Getenv("AWS_PROFILE")
	info.RedirectPort = os.Getenv("REDIRECT_PORT")

	// Debug mode
	debugVal := os.Getenv("COGNITO_AUTH_DEBUG")
	info.DebugEnabled = debugVal == "1" || debugVal == "true" || debugVal == "yes"

	// Browser notification suppression
	info.NoBrowserNotify = os.Getenv("CCWB_NO_BROWSER_NOTIFICATION") == "1"

	// SSH detection (affects browser-based auth)
	info.IsSSH = os.Getenv("SSH_CONNECTION") != "" || os.Getenv("SSH_TTY") != "" || os.Getenv("SSH_CLIENT") != ""

	// Headless detection (no display server)
	if runtime.GOOS == "linux" {
		info.IsHeadless = os.Getenv("DISPLAY") == "" && os.Getenv("WAYLAND_DISPLAY") == ""
	}

	// Browser override
	info.BrowserOverride = os.Getenv("BROWSER")

	// Monitoring token presence (not the value — sensitive)
	info.MonitoringToken = os.Getenv("CLAUDE_CODE_MONITORING_TOKEN") != ""

	return info
}
