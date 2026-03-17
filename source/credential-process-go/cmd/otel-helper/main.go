package main

import (
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"time"

	"credential-process-go/internal/otel"
)

var version = "1.0.0-beta" // overridden by -ldflags

func main() {
	os.Exit(run())
}

func run() int {
	showVersion := flag.Bool("version", false, "Show version")
	flag.BoolVar(showVersion, "v", false, "Show version (shorthand)")
	testMode := flag.Bool("test", false, "Run in test mode with verbose output")
	verbose := flag.Bool("verbose", false, "Show verbose output")
	flag.Parse()

	if *showVersion {
		fmt.Printf("otel-helper %s\n", version)
		return 0
	}

	debug := *verbose || *testMode ||
		strings.ToLower(os.Getenv("DEBUG_MODE")) == "true" ||
		strings.ToLower(os.Getenv("DEBUG_MODE")) == "1"

	// Get token from environment first
	token := os.Getenv("CLAUDE_CODE_MONITORING_TOKEN")
	if token != "" {
		debugLog(debug, "Using token from environment variable CLAUDE_CODE_MONITORING_TOKEN")
	} else {
		debugLog(debug, "Getting token via credential-process...")
		var err error
		token, err = getTokenViaCredentialProcess(debug)
		if err != nil {
			debugLog(debug, fmt.Sprintf("Failed to get token: %v", err))
			return 1
		}
		if token == "" {
			debugLog(debug, "Could not obtain authentication token")
			return 1
		}
	}

	// Decode and process
	payload, err := otel.DecodeJWTPayload(token)
	if err != nil {
		debugLog(debug, fmt.Sprintf("Error decoding JWT: %v", err))
		return 1
	}

	userInfo := otel.ExtractUserInfo(payload)
	headers := otel.FormatAsHeaders(userInfo)

	if *testMode {
		printTestOutput(userInfo, headers)
	} else {
		data, err := json.Marshal(headers)
		if err != nil {
			debugLog(debug, fmt.Sprintf("Error marshaling headers: %v", err))
			return 1
		}
		fmt.Println(string(data))
	}

	return 0
}

func getTokenViaCredentialProcess(debug bool) (string, error) {
	// Determine credential-process path
	ext := ""
	if runtime.GOOS == "windows" {
		ext = ".exe"
	}
	credentialProcess := filepath.Join(os.Getenv("HOME"), "claude-code-with-bedrock", "credential-process"+ext)
	if runtime.GOOS == "windows" {
		credentialProcess = filepath.Join(os.Getenv("USERPROFILE"), "claude-code-with-bedrock", "credential-process"+ext)
	}

	if _, err := os.Stat(credentialProcess); os.IsNotExist(err) {
		return "", fmt.Errorf("credential process not found at %s", credentialProcess)
	}

	profile := os.Getenv("AWS_PROFILE")
	if profile == "" {
		profile = "ClaudeCode"
	}

	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()

	cmd := exec.CommandContext(ctx, credentialProcess, "--profile", profile, "--get-monitoring-token")
	debugLog(debug, fmt.Sprintf("Running: %s --profile %s --get-monitoring-token", credentialProcess, profile))

	output, err := cmd.Output()
	if err != nil {
		return "", fmt.Errorf("credential process failed: %w", err)
	}

	token := strings.TrimSpace(string(output))
	if token == "" {
		return "", fmt.Errorf("credential process returned empty token")
	}

	debugLog(debug, "Successfully retrieved token via credential-process")
	return token, nil
}

func printTestOutput(info otel.UserInfo, headers map[string]string) {
	fmt.Println("===== TEST MODE OUTPUT =====")
	fmt.Println()
	fmt.Println("Generated HTTP Headers:")
	for name, value := range headers {
		displayName := strings.ReplaceAll(name, "x-", "X-")
		displayName = strings.ReplaceAll(displayName, "-id", "-ID")
		fmt.Printf("  %s: %s\n", displayName, value)
	}

	fmt.Println()
	fmt.Println("===== Extracted Attributes =====")
	fmt.Println()
	fmt.Printf("  user.email: %s\n", info.Email)
	fmt.Printf("  user.id: %s\n", truncate(info.UserID, 30))
	fmt.Printf("  user.name: %s\n", info.Username)
	fmt.Printf("  organization.id: %s\n", info.OrganizationID)
	fmt.Println("  service.name: claude-code")
	fmt.Printf("  user.account_uuid: %s\n", info.AccountUUID)
	fmt.Printf("  oidc.issuer: %s\n", truncate(info.Issuer, 30))
	fmt.Printf("  oidc.subject: %s\n", truncate(info.Subject, 30))
	fmt.Printf("  department: %s\n", info.Department)
	fmt.Printf("  team.id: %s\n", info.Team)
	fmt.Printf("  cost_center: %s\n", info.CostCenter)
	fmt.Printf("  manager: %s\n", info.Manager)
	fmt.Printf("  location: %s\n", info.Location)
	fmt.Printf("  role: %s\n", info.Role)
	fmt.Println()
	fmt.Println("========================")
}

func truncate(s string, maxLen int) string {
	if len(s) > maxLen {
		return s[:maxLen] + "..."
	}
	return s
}

func debugLog(debug bool, msg string) {
	if debug {
		fmt.Fprintf(os.Stderr, "Debug: %s\n", msg)
	}
}
