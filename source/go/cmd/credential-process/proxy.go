// ABOUTME: Auto-spawns the otel-helper OTLP proxy for Cowork per-user identity injection.
// ABOUTME: Called by credential-process after successful credential issuance. The proxy
// ABOUTME: reads the JWT identity cache and injects x-user-email headers on Cowork OTLP
// ABOUTME: requests before forwarding to the upstream (central ALB or local otelcol).

package main

import (
	"fmt"
	"net"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strconv"
	"strings"
	"time"

	"ccwb-go/internal/config"
)

const (
	// Central mode: proxy listens on 4318, forwards to remote ALB.
	proxyCentralPort = 4318
	// Sidecar mode: proxy listens on 4319, forwards to local otelcol on 4318.
	proxySidecarPort = 4319
	// Local otelcol port (sidecar mode).
	otelcolPort = 4318

	proxyDialTimeout = 200 * time.Millisecond
)

// ensureProxyRunning spawns the otel-helper OTLP proxy for per-user identity
// injection if it's not already listening.
//
// Behavior depends on monitoring mode:
//
// Central mode:
//   - Proxy listens on port 4318
//   - Forwards to remote collector ALB (from config.OtelCollectorEndpoint)
//   - Chain: Cowork → proxy:4318 (identity) → ALB → ECS → CloudWatch
//
// Sidecar mode:
//   - Proxy listens on port 4319 (otelcol already on 4318)
//   - Forwards to localhost:4318 (local otelcol)
//   - Chain: Cowork → proxy:4319 (identity) → otelcol:4318 (SigV4) → CloudWatch
//
// No-op when:
//   - The proxy is already listening on its designated port
//   - No collector endpoint is configured AND not in sidecar mode
//   - The otel-helper binary is not found on disk
func ensureProxyRunning(profile string) {
	// Load config to determine mode and upstream
	cfg, err := config.LoadProfile(profile)
	if err != nil {
		debugPrint("ensureProxyRunning: cannot load config: %v", err)
		return
	}

	// Determine port and upstream based on monitoring mode
	port, upstream := resolveProxyTarget(cfg)
	if upstream == "" {
		debugPrint("ensureProxyRunning: no upstream target (no endpoint configured, not sidecar)")
		return
	}

	// Quick port check — if something is listening, assume proxy is alive.
	// Note: TOCTOU race exists (port could be claimed between check and spawn)
	// but risk is negligible — proxy is the only expected listener, and the
	// self-healing cadence (~1h) handles transient failures automatically.
	conn, err := net.DialTimeout("tcp", fmt.Sprintf("127.0.0.1:%d", port), proxyDialTimeout)
	if err == nil {
		conn.Close()
		return
	}

	// Find the otel-helper binary (same directory as credential-process)
	helperPath := resolveOtelHelperPath()
	if helperPath == "" {
		debugPrint("ensureProxyRunning: otel-helper binary not found")
		return
	}

	// Spawn the proxy detached
	// --proxy: boolean flag to enter proxy mode
	// --proxy-upstream: URL to forward to (passthrough mode, no SigV4)
	// --proxy-port: listen port
	// Both central (ALB) and sidecar (otelcol) use passthrough mode —
	// SigV4 signing is handled downstream (ALB auth in central, otelcol in sidecar).
	args := []string{"--proxy", "--proxy-upstream", upstream, "--proxy-port", strconv.Itoa(port)}

	// Pass the profile so the proxy reads the correct identity cache
	env := os.Environ()
	hasProfile := false
	for _, e := range env {
		if strings.HasPrefix(e, "AWS_PROFILE=") {
			hasProfile = true
			break
		}
	}
	if !hasProfile {
		env = append(env, "AWS_PROFILE="+profile)
	}

	cmd := exec.Command(helperPath, args...)
	cmd.Env = env
	cmd.Stdout = nil
	cmd.Stderr = nil

	// Detach from parent process (platform-specific)
	detachProcess(cmd)

	if err := cmd.Start(); err != nil {
		fmt.Fprintf(os.Stderr, "warning: failed to start OTLP identity proxy: %v\n", err)
		debugPrint("ensureProxyRunning: failed to start proxy: %v", err)
		return
	}

	// Release the child so it doesn't become a zombie
	cmd.Process.Release()
	debugPrint("ensureProxyRunning: spawned otel-helper proxy (PID %d) port %d → %s", cmd.Process.Pid, port, upstream)
}

// resolveProxyTarget determines the proxy listen port and upstream URL.
//
// Returns (port, upstream). If upstream is empty, proxy should not be started.
func resolveProxyTarget(cfg *config.ProfileConfig) (int, string) {
	mode := cfg.MonitoringMode
	if mode == "" {
		mode = "central"
	}

	if mode == "sidecar" {
		// Sidecar: proxy on 4319 → forward to local otelcol on 4318
		return proxySidecarPort, fmt.Sprintf("http://localhost:%d", otelcolPort)
	}

	// Central: proxy on 4318 → forward to remote collector ALB
	endpoint := cfg.OtelCollectorEndpoint
	if endpoint == "" {
		return 0, ""
	}
	return proxyCentralPort, endpoint
}

// resolveOtelHelperPath finds the otel-helper binary.
// It looks in the same directory as the running credential-process binary,
// then falls back to ~/claude-code-with-bedrock/.
func resolveOtelHelperPath() string {
	binaryName := "otel-helper"
	if runtime.GOOS == "windows" {
		binaryName = "otel-helper.exe"
	}

	// Same directory as credential-process
	if exePath, err := os.Executable(); err == nil {
		candidate := filepath.Join(filepath.Dir(exePath), binaryName)
		if _, err := os.Stat(candidate); err == nil {
			return candidate
		}
	}

	// Fallback: ~/claude-code-with-bedrock/
	if home, err := os.UserHomeDir(); err == nil {
		candidate := filepath.Join(home, "claude-code-with-bedrock", binaryName)
		if _, err := os.Stat(candidate); err == nil {
			return candidate
		}
	}

	return ""
}
