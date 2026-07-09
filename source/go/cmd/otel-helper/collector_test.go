// ABOUTME: Tests for collector sidecar management — separate stdout/stderr
// ABOUTME: log files, PID reuse, and the central-mode no-op path.
package main

import (
	"os"
	"path/filepath"
	"runtime"
	"strconv"
	"strings"
	"testing"
	"time"
)

func TestEnvWithout(t *testing.T) {
	in := []string{"A=1", "AWS_PROFILE=x", "B=2", "AWS_PROFILE=y"}
	got := envWithout(in, "AWS_PROFILE")
	if len(got) != 2 || got[0] != "A=1" || got[1] != "B=2" {
		t.Errorf("envWithout = %v, want [A=1 B=2]", got)
	}
	// Must not match prefix-named variables like AWS_PROFILE_EXTRA.
	got = envWithout([]string{"AWS_PROFILE_EXTRA=z"}, "AWS_PROFILE")
	if len(got) != 1 {
		t.Errorf("envWithout removed AWS_PROFILE_EXTRA, want it kept")
	}
}

// TestEnsureCollectorRunning_NoSidecarInstall_NoOp: central-mode installs have
// no otelcol binary; the helper must not create PID or log files.
func TestEnsureCollectorRunning_NoSidecarInstall_NoOp(t *testing.T) {
	tmp := t.TempDir()
	t.Setenv("HOME", tmp)
	t.Setenv("USERPROFILE", tmp)

	ensureCollectorRunning("ClaudeCode")

	if _, err := os.Stat(filepath.Join(tmp, "claude-code-with-bedrock", "collector.pid")); !os.IsNotExist(err) {
		t.Errorf("pid file must not be created without a sidecar install (stat err = %v)", err)
	}
}

// TestEnsureCollectorRunning_StartsWithSeparateLogFiles is the regression test
// for the Windows sidecar bugs: (1) the Go helper previously never started the
// collector at all (only the .sh/.ps1 wrappers did, and on Windows the .cmd
// runs this binary first, so the collector never launched), and (2) stdout and
// stderr must go to SEPARATE files — Windows cannot redirect both streams into
// one file.
func TestEnsureCollectorRunning_StartsWithSeparateLogFiles(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("uses a shell-script stand-in for otelcol")
	}
	tmp := t.TempDir()
	t.Setenv("HOME", tmp)
	t.Setenv("USERPROFILE", tmp)
	installDir := filepath.Join(tmp, "claude-code-with-bedrock")
	if err := os.MkdirAll(installDir, 0o755); err != nil {
		t.Fatal(err)
	}
	// Stand-in collector: proves which AWS profile it was launched under,
	// writes distinct stdout/stderr content, then stays alive briefly.
	script := "#!/bin/sh\necho \"profile=$AWS_PROFILE\"\necho stderr-marker >&2\nsleep 10\n"
	if err := os.WriteFile(filepath.Join(installDir, "otelcol"), []byte(script), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(installDir, "collector-config.yaml"), []byte("receivers:\n"), 0o644); err != nil {
		t.Fatal(err)
	}

	ensureCollectorRunning("TestProfile")

	pidData, err := os.ReadFile(filepath.Join(installDir, "collector.pid"))
	if err != nil {
		t.Fatalf("collector.pid not written: %v", err)
	}
	pid, err := strconv.Atoi(strings.TrimSpace(string(pidData)))
	if err != nil || pid <= 0 {
		t.Fatalf("collector.pid content %q is not a PID", pidData)
	}
	defer func() {
		if p, ferr := os.FindProcess(pid); ferr == nil {
			_ = p.Kill()
		}
	}()

	if !isProcessAlive(pid) {
		t.Error("collector process should be alive after launch")
	}

	cacheDir := filepath.Join(tmp, ".claude-code-session")
	waitForContent(t, filepath.Join(cacheDir, "collector.log"), "profile=TestProfile-collector")
	waitForContent(t, filepath.Join(cacheDir, "collector.err"), "stderr-marker")

	// A second invocation with a live PID must not respawn.
	ensureCollectorRunning("TestProfile")
	pidData2, err := os.ReadFile(filepath.Join(installDir, "collector.pid"))
	if err != nil {
		t.Fatal(err)
	}
	if string(pidData2) != string(pidData) {
		t.Errorf("collector respawned despite live PID: %s -> %s", pidData, pidData2)
	}
}

// waitForContent polls for a file to exist and contain the given substring.
func waitForContent(t *testing.T, path, want string) {
	t.Helper()
	deadline := time.Now().Add(3 * time.Second)
	for time.Now().Before(deadline) {
		if data, err := os.ReadFile(path); err == nil && strings.Contains(string(data), want) {
			return
		}
		time.Sleep(20 * time.Millisecond)
	}
	data, err := os.ReadFile(path)
	t.Fatalf("file %s never contained %q (content=%q, err=%v)", path, want, data, err)
}
