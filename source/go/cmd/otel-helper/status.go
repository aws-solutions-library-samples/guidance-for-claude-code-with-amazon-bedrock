// ABOUTME: --status flag implementation for otel-helper.
// ABOUTME: Prints current otel-helper state (proxy running? port? cached headers?)
// ABOUTME: without starting any services. Used for troubleshooting and ccwb doctor.

package main

import (
	"encoding/json"
	"fmt"
	"net"
	"os"
	"runtime"
	"time"

	"ccwb-go/internal/otel"
	"ccwb-go/internal/version"
)

// StatusOutput is the structured JSON output for --status.
type StatusOutput struct {
	Version  string          `json:"version"`
	Platform string          `json:"platform"`
	Profile  string          `json:"profile"`
	Proxy    ProxyStatus     `json:"proxy"`
	Cache    CacheStatus     `json:"cache"`
}

// ProxyStatus reports whether the otel-helper proxy is running.
type ProxyStatus struct {
	Listening bool   `json:"listening"`
	Port      int    `json:"port"`
	Mode      string `json:"mode,omitempty"` // "sigv4" | "passthrough" | "" (not running)
}

// CacheStatus reports the state of the otel-headers cache.
type CacheStatus struct {
	HasHeaders bool     `json:"has_headers"`
	Headers    []string `json:"header_keys,omitempty"` // e.g. ["x-user-email", "Authorization"]
}

// runStatus prints otel-helper status as JSON and returns exit code.
func runStatus(proxyPort int) int {
	profile := os.Getenv("AWS_PROFILE")
	if profile == "" {
		profile = "ClaudeCode"
	}

	output := StatusOutput{
		Version:  version.Version,
		Platform: runtime.GOOS + "/" + runtime.GOARCH,
		Profile:  profile,
		Proxy: ProxyStatus{
			Port: proxyPort,
		},
		Cache: CacheStatus{},
	}

	// Check if proxy is listening
	conn, err := net.DialTimeout("tcp", fmt.Sprintf("127.0.0.1:%d", proxyPort), 500*time.Millisecond)
	if err == nil {
		conn.Close()
		output.Proxy.Listening = true
		output.Proxy.Mode = "sigv4" // Default; passthrough mode detection would need process inspection
	}

	// Also check alternate port (4319 for sidecar)
	if proxyPort == defaultProxyPort {
		altConn, altErr := net.DialTimeout("tcp", "127.0.0.1:4319", 500*time.Millisecond)
		if altErr == nil {
			altConn.Close()
			if !output.Proxy.Listening {
				output.Proxy.Listening = true
				output.Proxy.Port = 4319
				output.Proxy.Mode = "sigv4"
			}
		}
	}

	// Check cached headers
	headers, err := otel.ReadCachedHeaders(profile)
	if err == nil && len(headers) > 0 {
		output.Cache.HasHeaders = true
		keys := make([]string, 0, len(headers))
		for k := range headers {
			keys = append(keys, k)
		}
		output.Cache.Headers = keys
	}

	enc := json.NewEncoder(os.Stdout)
	enc.SetIndent("", "  ")
	if err := enc.Encode(output); err != nil {
		fmt.Fprintf(os.Stderr, "Error encoding status output: %v\n", err)
		return 1
	}
	return 0
}
