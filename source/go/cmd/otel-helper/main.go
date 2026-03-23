package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"log"
	"os"
	"os/exec"
	"strings"

	"github.com/bluedoors/ccwb-binaries/internal/config"
	"github.com/bluedoors/ccwb-binaries/internal/jwt"
	"github.com/bluedoors/ccwb-binaries/internal/otel"
	"github.com/bluedoors/ccwb-binaries/internal/version"
)

var (
	logger  = log.New(os.Stderr, "", log.LstdFlags)
	debug   bool
	verbose bool
)

func debugPrint(format string, args ...interface{}) {
	if debug || verbose {
		logger.Printf(format, args...)
	}
}

func main() {
	testMode := flag.Bool("test", false, "Run in test mode with verbose output")
	verboseFlag := flag.Bool("verbose", false, "Show verbose output")
	versionFlag := flag.Bool("version", false, "Show version")
	flag.Parse()

	if *versionFlag {
		fmt.Printf("otel-helper %s\n", version.Version)
		os.Exit(0)
	}

	verbose = *verboseFlag || *testMode
	debug = os.Getenv("DEBUG_MODE") != "" || verbose

	os.Exit(run(*testMode))
}

func run(testMode bool) int {
	profile := os.Getenv("AWS_PROFILE")
	if profile == "" {
		profile = "ClaudeCode"
	}

	// Layer 1: Check file cache first (avoids credential-process entirely)
	if !testMode {
		headers, err := otel.ReadCachedHeaders(profile)
		if err == nil && headers != nil {
			debugPrint("Using cached OTEL headers (token still valid)")
			outputJSON(headers)
			return 0
		}
	}

	// Layer 2: Check environment variable
	token := os.Getenv("CLAUDE_CODE_MONITORING_TOKEN")
	if token != "" {
		debugPrint("Using token from environment variable CLAUDE_CODE_MONITORING_TOKEN")
	} else {
		// Layer 3: Get token via credential-process subprocess
		var err error
		token, err = getTokenViaCredentialProcess(profile)
		if err != nil || token == "" {
			debugPrint("Could not obtain authentication token")
			return 1
		}
	}

	// Decode JWT and extract user info
	claims, err := jwt.DecodePayload(token)
	if err != nil {
		debugPrint("Error decoding JWT: %v", err)
		return 1
	}

	userInfo := otel.ExtractUserInfo(claims)
	headers := otel.FormatHeaders(userInfo)

	if testMode {
		printTestOutput(userInfo, headers)
	} else {
		// Cache headers for future calls
		tokenExp := int64(claims.GetFloat("exp"))
		if tokenExp > 0 {
			if err := otel.WriteCachedHeaders(profile, headers, tokenExp); err != nil {
				debugPrint("Failed to write cached headers: %v", err)
			}
		} else {
			debugPrint("JWT has no exp claim, skipping cache write")
		}
		outputJSON(headers)
	}

	return 0
}

func getTokenViaCredentialProcess(profile string) (string, error) {
	cpPath := config.CredentialProcessPath()

	if _, err := os.Stat(cpPath); os.IsNotExist(err) {
		debugPrint("Credential process not found at %s", cpPath)
		return "", fmt.Errorf("credential-process not found")
	}

	debugPrint("Getting token via credential-process...")
	cmd := exec.Command(cpPath, "--profile", profile, "--get-monitoring-token")
	out, err := cmd.Output()
	if err != nil {
		debugPrint("Failed to get token via credential-process: %v", err)
		return "", err
	}

	token := strings.TrimSpace(string(out))
	if token == "" {
		return "", fmt.Errorf("empty token from credential-process")
	}

	debugPrint("Successfully retrieved token via credential-process")
	return token, nil
}

func outputJSON(v interface{}) {
	data, _ := json.Marshal(v)
	fmt.Println(string(data))
}

func printTestOutput(info otel.UserInfo, headers map[string]string) {
	fmt.Println("===== TEST MODE OUTPUT =====")
	fmt.Println()
	fmt.Println("Generated HTTP Headers:")
	for name, val := range headers {
		display := strings.ReplaceAll(name, "x-", "X-")
		display = strings.ReplaceAll(display, "-id", "-ID")
		fmt.Printf("  %s: %s\n", display, val)
	}

	fmt.Println()
	fmt.Println("===== Extracted Attributes =====")
	fmt.Println()

	attrs := map[string]string{
		"email":           info.Email,
		"user_id":         info.UserID,
		"username":        info.Username,
		"organization_id": info.OrganizationID,
		"department":      info.Department,
		"team":            info.Team,
		"cost_center":     info.CostCenter,
		"manager":         info.Manager,
		"location":        info.Location,
		"role":            info.Role,
	}
	for key, val := range attrs {
		display := val
		if len(display) > 30 {
			display = display[:30] + "..."
		}
		fmt.Printf("  %s: %s\n", strings.ReplaceAll(key, "_", "."), display)
	}

	fmt.Println()
	truncate := func(s string, n int) string {
		if len(s) > n {
			return s[:n] + "..."
		}
		return s
	}
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
