// ABOUTME: OTEL collector sidecar management — starts the local otelcol process
// ABOUTME: when installed. Parity with otel-helper.sh / otel-helper.ps1 / Python helper.
package main

import (
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strconv"
	"strings"
)

// ensureCollectorRunning starts the local OTEL collector sidecar if this is a
// sidecar-mode install (otelcol binary + collector-config.yaml present in the
// install dir) and it isn't already running. It never fails the caller: any
// error just means telemetry export will fail until the next invocation
// retries.
//
// The collector runs under a dedicated "<profile>-collector" AWS profile so
// its SDK resolves credentials via credential_process — the main profile's
// static ~/.aws/credentials would shadow credential_process and can't
// auto-refresh (same rationale as otel-helper.sh).
//
// stdout and stderr go to SEPARATE files (collector.log / collector.err):
// Windows does not support redirecting both streams into the same file.
func ensureCollectorRunning(profile string) {
	home, err := os.UserHomeDir()
	if err != nil {
		return
	}
	installDir := filepath.Join(home, "claude-code-with-bedrock")
	binName := "otelcol"
	if runtime.GOOS == "windows" {
		binName = "otelcol.exe"
	}
	otelcol := filepath.Join(installDir, binName)
	configPath := filepath.Join(installDir, "collector-config.yaml")
	pidFile := filepath.Join(installDir, "collector.pid")

	if _, err := os.Stat(otelcol); err != nil {
		return // not a sidecar-mode install
	}
	if _, err := os.Stat(configPath); err != nil {
		return
	}

	if pidData, err := os.ReadFile(pidFile); err == nil {
		if pid, perr := strconv.Atoi(strings.TrimSpace(string(pidData))); perr == nil && pid > 0 && isProcessAlive(pid) {
			return // already running
		}
	}

	cacheDir := filepath.Join(home, ".claude-code-session")
	if err := os.MkdirAll(cacheDir, 0o700); err != nil {
		return
	}

	outFile, err := os.OpenFile(filepath.Join(cacheDir, "collector.log"), os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0o600)
	if err != nil {
		return
	}
	defer outFile.Close()
	errFile, err := os.OpenFile(filepath.Join(cacheDir, "collector.err"), os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0o600)
	if err != nil {
		return
	}
	defer errFile.Close()

	cmd := exec.Command(otelcol, "--config", configPath) // nosemgrep: go.lang.security.audit.dangerous-exec-command.dangerous-exec-command
	cmd.Stdout = outFile
	cmd.Stderr = errFile
	// AWS_SDK_LOAD_CONFIG: collector components built on aws-sdk-go v1 (the
	// awsemf exporter's awsutil layer) do not read ~/.aws/config — where the
	// "<profile>-collector" profile and its credential_process live — unless
	// this is set. SDK v2 components (sigv4auth) read it regardless, which is
	// why AMP export worked while EMF export failed without it.
	env := envWithout(envWithout(os.Environ(), "AWS_PROFILE"), "AWS_SDK_LOAD_CONFIG")
	cmd.Env = append(env, "AWS_PROFILE="+profile+"-collector", "AWS_SDK_LOAD_CONFIG=1")
	cmd.SysProcAttr = detachedSysProcAttr()
	if err := cmd.Start(); err != nil {
		debugPrint("Failed to start collector sidecar: %v", err)
		return
	}
	if err := os.WriteFile(pidFile, []byte(strconv.Itoa(cmd.Process.Pid)), 0o600); err != nil {
		debugPrint("Failed to write collector PID file: %v", err)
	}
	debugPrint("Started collector sidecar (PID %d)", cmd.Process.Pid)
	// Detach — the helper must not block on the long-running collector.
	_ = cmd.Process.Release()
}

// envWithout returns env minus any entries for the given variable name.
func envWithout(env []string, name string) []string {
	prefix := name + "="
	out := make([]string, 0, len(env))
	for _, e := range env {
		if !strings.HasPrefix(e, prefix) {
			out = append(out, e)
		}
	}
	return out
}
