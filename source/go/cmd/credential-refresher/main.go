// ABOUTME: Background credential refresher daemon for session-storage mode.
// ABOUTME: Keeps ~/.aws/credentials fresh so the AWS SDK reads creds directly
// ABOUTME: without spawning credential-process on every request.
package main

import (
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"os/signal"
	"path/filepath"
	"strconv"
	"syscall"
	"time"

	"ccwb-go/internal/config"
	"ccwb-go/internal/storage"
	"ccwb-go/internal/version"
)

const (
	defaultRefreshInterval = 300 // 5 minutes
	refreshBuffer          = 600 // Refresh when <10 min remaining
)

func main() {
	defaultProfile := os.Getenv("CCWB_PROFILE")
	if defaultProfile == "" {
		defaultProfile = "ClaudeCode"
	}

	profileFlag := flag.String("profile", defaultProfile, "Configuration profile")
	intervalFlag := flag.Int("interval", defaultRefreshInterval, "Check interval in seconds")
	oneShot := flag.Bool("once", false, "Check and refresh once, then exit")
	statusFlag := flag.Bool("status", false, "Show refresher status and exit")
	stopFlag := flag.Bool("stop", false, "Stop running refresher for this profile")
	versionFlag := flag.Bool("version", false, "Show version")
	flag.Parse()

	if *versionFlag {
		fmt.Printf("credential-refresher %s\n", version.Version)
		os.Exit(0)
	}

	profile := *profileFlag
	if profile == defaultProfile {
		if detected := config.AutoDetectProfile(); detected != "" {
			profile = detected
		}
	}

	if *statusFlag {
		os.Exit(showStatus(profile))
	}

	if *stopFlag {
		os.Exit(stopDaemon(profile))
	}

	cfg, err := config.LoadProfile(profile)
	if err != nil {
		fmt.Fprintf(os.Stderr, "Error loading profile: %v\n", err)
		os.Exit(1)
	}

	if cfg.CredentialStorage != "session" {
		fmt.Fprintf(os.Stderr, "Error: credential-refresher only works with credential_storage=session\n")
		fmt.Fprintf(os.Stderr, "Current storage mode: %s\n", cfg.CredentialStorage)
		os.Exit(1)
	}

	refresher := &Refresher{
		profile:  profile,
		interval: time.Duration(*intervalFlag) * time.Second,
	}

	if *oneShot {
		os.Exit(refresher.refreshOnce())
	}

	// Daemon mode
	if err := writePIDFile(profile); err != nil {
		fmt.Fprintf(os.Stderr, "Warning: could not write PID file: %v\n", err)
	}
	defer removePIDFile(profile)

	fmt.Fprintf(os.Stderr, "credential-refresher: started for profile '%s' (interval=%s)\n",
		profile, refresher.interval)

	os.Exit(refresher.run())
}

// Refresher manages periodic credential refresh.
type Refresher struct {
	profile  string
	interval time.Duration
}

// run starts the refresh loop, stopping on SIGTERM/SIGINT.
func (r *Refresher) run() int {
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	sigCh := make(chan os.Signal, 1)
	signal.Notify(sigCh, syscall.SIGTERM, syscall.SIGINT)

	// Initial check
	r.refreshOnce()

	ticker := time.NewTicker(r.interval)
	defer ticker.Stop()

	for {
		select {
		case <-ticker.C:
			r.refreshOnce()
		case sig := <-sigCh:
			fmt.Fprintf(os.Stderr, "credential-refresher: received %s, shutting down\n", sig)
			cancel()
			return 0
		case <-ctx.Done():
			return 0
		}
	}
}

// refreshOnce checks credential expiry and refreshes if needed.
// Returns 0 on success (creds valid or refreshed), 1 on error.
func (r *Refresher) refreshOnce() int {
	creds, err := storage.ReadFromCredentialsFile(r.profile)
	if err != nil {
		fmt.Fprintf(os.Stderr, "credential-refresher: error reading credentials: %v\n", err)
		return r.doRefresh()
	}

	if creds == nil || storage.IsExpiredDummy(creds) {
		fmt.Fprintf(os.Stderr, "credential-refresher: no valid credentials found, refreshing\n")
		return r.doRefresh()
	}

	remaining := storage.ParseExpirationSeconds(creds.Expiration)
	if remaining <= float64(refreshBuffer) {
		fmt.Fprintf(os.Stderr, "credential-refresher: credentials expiring soon (%.0fs remaining), refreshing\n", remaining)
		return r.doRefresh()
	}

	// Creds are valid
	return 0
}

// doRefresh invokes the credential-process binary to obtain fresh credentials.
// This is the simplest approach: reuse the existing credential-process with
// --refresh-if-needed semantics but force a full auth if needed.
func (r *Refresher) doRefresh() int {
	cpPath := credentialProcessPath()
	if _, err := os.Stat(cpPath); os.IsNotExist(err) {
		fmt.Fprintf(os.Stderr, "credential-refresher: credential-process not found at %s\n", cpPath)
		return 1
	}

	// Execute credential-process. It handles the full OIDC flow,
	// writes to ~/.aws/credentials (in session mode), and outputs JSON.
	cmd := newCommand(cpPath, "--profile", r.profile)
	cmd.Stderr = os.Stderr
	output, err := cmd.Output()
	if err != nil {
		fmt.Fprintf(os.Stderr, "credential-refresher: credential-process failed: %v\n", err)
		return 1
	}

	// Verify the output is valid JSON with credentials
	var creds struct {
		AccessKeyID string `json:"AccessKeyId"`
		Expiration  string `json:"Expiration"`
	}
	if err := json.Unmarshal(output, &creds); err != nil || creds.AccessKeyID == "" {
		fmt.Fprintf(os.Stderr, "credential-refresher: invalid output from credential-process\n")
		return 1
	}

	fmt.Fprintf(os.Stderr, "credential-refresher: credentials refreshed (expires: %s)\n", creds.Expiration)
	return 0
}

// credentialProcessPath returns the expected path to the credential-process binary.
func credentialProcessPath() string {
	// Same directory as this binary
	exePath, err := os.Executable()
	if err == nil {
		dir := filepath.Dir(exePath)
		candidate := filepath.Join(dir, "credential-process")
		if _, err := os.Stat(candidate); err == nil {
			return candidate
		}
		// Windows
		candidate = filepath.Join(dir, "credential-process.exe")
		if _, err := os.Stat(candidate); err == nil {
			return candidate
		}
	}

	// Fall back to ~/claude-code-with-bedrock/
	return config.CredentialProcessPath()
}

// PID file management

func pidFilePath(profile string) string {
	home, _ := os.UserHomeDir()
	return filepath.Join(home, ".claude-code-session", fmt.Sprintf("refresher-%s.pid", profile))
}

func writePIDFile(profile string) error {
	dir := filepath.Dir(pidFilePath(profile))
	if err := os.MkdirAll(dir, 0700); err != nil {
		return err
	}
	return os.WriteFile(pidFilePath(profile), []byte(strconv.Itoa(os.Getpid())), 0600)
}

func removePIDFile(profile string) {
	os.Remove(pidFilePath(profile))
}

func readPID(profile string) (int, error) {
	data, err := os.ReadFile(pidFilePath(profile))
	if err != nil {
		return 0, err
	}
	return strconv.Atoi(string(data))
}

func isProcessRunning(pid int) bool {
	proc, err := os.FindProcess(pid)
	if err != nil {
		return false
	}
	// On Unix, FindProcess always succeeds. Send signal 0 to check existence.
	err = proc.Signal(syscall.Signal(0))
	return err == nil
}

func showStatus(profile string) int {
	pid, err := readPID(profile)
	if err != nil {
		fmt.Printf("No refresher running for profile '%s'\n", profile)
		return 1
	}
	if !isProcessRunning(pid) {
		fmt.Printf("Stale PID file for profile '%s' (pid %d not running)\n", profile, pid)
		removePIDFile(profile)
		return 1
	}
	fmt.Printf("Refresher running for profile '%s' (pid %d)\n", profile, pid)

	// Also show credential status
	creds, _ := storage.ReadFromCredentialsFile(profile)
	if creds != nil && !storage.IsExpiredDummy(creds) {
		remaining := storage.ParseExpirationSeconds(creds.Expiration)
		fmt.Printf("Credentials valid for %.0f seconds (expires: %s)\n", remaining, creds.Expiration)
	} else {
		fmt.Printf("Credentials: expired or missing\n")
	}
	return 0
}

func stopDaemon(profile string) int {
	pid, err := readPID(profile)
	if err != nil {
		fmt.Printf("No refresher running for profile '%s'\n", profile)
		return 0
	}
	if !isProcessRunning(pid) {
		fmt.Printf("Stale PID file removed for profile '%s'\n", profile)
		removePIDFile(profile)
		return 0
	}

	proc, err := os.FindProcess(pid)
	if err != nil {
		return 1
	}
	if err := proc.Signal(syscall.SIGTERM); err != nil {
		fmt.Fprintf(os.Stderr, "Error stopping refresher (pid %d): %v\n", pid, err)
		return 1
	}
	fmt.Printf("Stopped refresher for profile '%s' (pid %d)\n", profile, pid)
	removePIDFile(profile)
	return 0
}
