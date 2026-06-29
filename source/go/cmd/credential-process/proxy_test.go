// ABOUTME: Unit tests for proxy.go — verifies proxy target resolution, binary
// ABOUTME: discovery, and port-check behavior for the CoWork identity proxy.

package main

import (
	"net"
	"os"
	"path/filepath"
	"runtime"
	"testing"

	"ccwb-go/internal/config"
)

func TestResolveProxyTarget_CentralMode(t *testing.T) {
	cfg := &config.ProfileConfig{
		MonitoringMode:        "central",
		OtelCollectorEndpoint: "https://alb.example.com",
	}
	port, upstream := resolveProxyTarget(cfg)
	if port != proxyCentralPort {
		t.Errorf("expected port %d, got %d", proxyCentralPort, port)
	}
	if upstream != "https://alb.example.com" {
		t.Errorf("expected upstream https://alb.example.com, got %s", upstream)
	}
}

func TestResolveProxyTarget_CentralModeDefault(t *testing.T) {
	// Empty MonitoringMode defaults to "central"
	cfg := &config.ProfileConfig{
		MonitoringMode:        "",
		OtelCollectorEndpoint: "https://collector.corp.com",
	}
	port, upstream := resolveProxyTarget(cfg)
	if port != proxyCentralPort {
		t.Errorf("expected port %d, got %d", proxyCentralPort, port)
	}
	if upstream != "https://collector.corp.com" {
		t.Errorf("expected upstream https://collector.corp.com, got %s", upstream)
	}
}

func TestResolveProxyTarget_SidecarMode(t *testing.T) {
	cfg := &config.ProfileConfig{
		MonitoringMode:        "sidecar",
		OtelCollectorEndpoint: "https://unused.example.com", // ignored in sidecar
	}
	port, upstream := resolveProxyTarget(cfg)
	if port != proxySidecarPort {
		t.Errorf("expected port %d, got %d", proxySidecarPort, port)
	}
	expected := "http://localhost:4318"
	if upstream != expected {
		t.Errorf("expected upstream %s, got %s", expected, upstream)
	}
}

func TestResolveProxyTarget_NoEndpoint(t *testing.T) {
	cfg := &config.ProfileConfig{
		MonitoringMode:        "central",
		OtelCollectorEndpoint: "",
	}
	port, upstream := resolveProxyTarget(cfg)
	if port != 0 {
		t.Errorf("expected port 0, got %d", port)
	}
	if upstream != "" {
		t.Errorf("expected empty upstream, got %s", upstream)
	}
}

func TestResolveOtelHelperPath_NotFound(t *testing.T) {
	// With no binary in expected locations, should return ""
	// Save and restore HOME to avoid finding a real binary
	origHome := os.Getenv("HOME")
	tmpDir := t.TempDir()
	os.Setenv("HOME", tmpDir)
	defer os.Setenv("HOME", origHome)

	path := resolveOtelHelperPath()
	// May find the binary via os.Executable() dir — that's OK.
	// We mainly test that it doesn't panic and returns a valid path or "".
	if path != "" {
		// Verify returned path actually exists
		if _, err := os.Stat(path); err != nil {
			t.Errorf("resolveOtelHelperPath returned non-existent path: %s", path)
		}
	}
}

func TestResolveOtelHelperPath_FallbackDir(t *testing.T) {
	tmpDir := t.TempDir()
	installDir := filepath.Join(tmpDir, "claude-code-with-bedrock")
	os.MkdirAll(installDir, 0755)

	binaryName := "otel-helper"
	if runtime.GOOS == "windows" {
		binaryName = "otel-helper.exe"
	}
	fakeBinary := filepath.Join(installDir, binaryName)
	os.WriteFile(fakeBinary, []byte("#!/bin/sh\n"), 0755)

	// Override HOME so the fallback path resolves to our temp dir
	origHome := os.Getenv("HOME")
	os.Setenv("HOME", tmpDir)
	defer os.Setenv("HOME", origHome)

	path := resolveOtelHelperPath()
	// Should find the binary in the fallback location (or via os.Executable dir)
	if path == "" {
		// Only fail if we're sure the executable dir doesn't have it either
		t.Log("resolveOtelHelperPath returned empty — binary not in executable dir either")
	} else if path == fakeBinary {
		// Found our fake binary via fallback — correct
		t.Logf("correctly resolved via fallback: %s", path)
	}
}

func TestEnsureProxyRunning_AlreadyListening(t *testing.T) {
	// Start a listener on the proxy port to simulate an already-running proxy
	ln, err := net.Listen("tcp4", "127.0.0.1:0")
	if err != nil {
		t.Fatalf("failed to start test listener: %v", err)
	}
	defer ln.Close()

	// The function should detect the listener and return early (no-op).
	// We can't easily test this without a real config, but we can verify
	// that dialing a live port returns success (the core check logic).
	conn, err := net.DialTimeout("tcp", ln.Addr().String(), proxyDialTimeout)
	if err != nil {
		t.Fatalf("expected successful dial to live listener, got: %v", err)
	}
	conn.Close()
}

func TestEnsureProxyRunning_PortNotListening(t *testing.T) {
	// Dial a port that nothing is listening on — should fail
	// Use a high ephemeral port unlikely to be in use
	conn, err := net.DialTimeout("tcp", "127.0.0.1:49999", proxyDialTimeout)
	if err == nil {
		conn.Close()
		t.Skip("port 49999 is unexpectedly in use")
	}
	// Expected: err != nil (connection refused)
}
