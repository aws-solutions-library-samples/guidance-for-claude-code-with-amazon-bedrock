package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"log"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"time"

	"ccwb-go/internal/config"
	"ccwb-go/internal/jwt"
	"ccwb-go/internal/otel"
	"ccwb-go/internal/version"
)

// emptyHeadersCacheTTLSeconds bounds how long THIS binary serves an empty-headers
// result from the file cache before it retries credential-process. It is short
// enough that retrying is cheap (a credential-process cache hit is ~20ms) yet
// long enough to keep telemetry export off the credential-process hot path
// during a sustained unauthenticated window. It is kept above the shell shim's
// 60s token_exp skew so the shim and binary agree on freshness.
//
// NOTE on end-to-end recovery: this TTL bounds when the *helper* refreshes, not
// when Claude Code asks again. Claude Code invokes otelHeadersHelper at startup
// and then on a debounce (default 29 min, CLAUDE_CODE_OTEL_HEADERS_HELPER_DEBOUNCE_MS).
// So after the user authenticates, attribution returns on the next helper
// invocation — effectively min(Claude Code's debounce, this TTL on a fresh
// invocation). With the default debounce the practical recovery is governed by
// that interval, not by 120s; lowering this const alone will NOT speed it up.
const emptyHeadersCacheTTLSeconds = 120

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

// attachBearer sets the Authorization header. Intentionally exp-AGNOSTIC:
// the Layer-1 cache-hit path never decodes the token, so token validation
// lives at the token source (see storage.GetMonitoringToken), NOT here.
// Do not add an exp check inside this function.
func attachBearer(headers map[string]string, token string) {
	if token != "" {
		headers["authorization"] = "Bearer " + token
	}
}

func main() {
	testMode := flag.Bool("test", false, "Run in test mode with verbose output")
	verboseFlag := flag.Bool("verbose", false, "Show verbose output")
	versionFlag := flag.Bool("version", false, "Show version")
	statusFlag := flag.Bool("status", false, "Print current otel-helper status as JSON and exit (proxy running? port? mode?)")
	proxyMode := flag.Bool("proxy", false, "Run as SigV4 signing proxy for CoWork OTLP logs")
	proxyPort := flag.Int("proxy-port", defaultProxyPort, "Port for the signing proxy (default 4318)")
	proxyRegion := flag.String("proxy-region", "", "AWS region for CloudWatch OTLP (default: AWS_REGION env)")
	flag.Parse()

	if *versionFlag {
		fmt.Printf("otel-helper %s\n", version.Version)
		os.Exit(0)
	}

	if *statusFlag {
		os.Exit(runStatus(*proxyPort))
	}

	verbose = *verboseFlag || *testMode
	debug = os.Getenv("DEBUG_MODE") != "" || verbose

	if *proxyMode {
		profile := os.Getenv("AWS_PROFILE")
		if profile == "" {
			profile = "ClaudeCode"
		}
		os.Exit(startProxy(proxyConfig{
			port:    *proxyPort,
			region:  *proxyRegion,
			profile: profile,
		}))
	}

	os.Exit(run(*testMode))
}

func run(testMode bool) int {
	profile := os.Getenv("AWS_PROFILE")
	if profile == "" {
		profile = "ClaudeCode"
	}

	// Layer 1: Serve attribution from the file cache. The cache stores
	// attribution headers only, never the token, so the Bearer is still
	// resolved below (env var, then credential-process). credential-process
	// is the correct fallback here — it owns token refresh, keyring storage,
	// and serve-past-expiry, none of which a direct monitoring.json read does.
	//
	// In test mode we still CONSULT the cache (so --test reflects what the
	// production path would emit) but render it via the test formatter rather
	// than printing the JSON contract. This matters for IDC, where there is no
	// JWT: the cache (written by credential-process from the IAM ARN) is the
	// ONLY source of attribution, so skipping it here made --test always show
	// empty headers even when attribution was working.
	if testMode {
		if headers, err := otel.ReadCachedHeaders(profile); err == nil && len(headers) > 0 {
			debugPrint("Using cached OTEL headers (test mode)")
			printTestOutput(userInfoFromHeaders(headers), headers)
			return 0
		}
		debugPrint("No cached OTEL headers; falling through to token-based extraction (test mode)")
	}
	if !testMode {
		headers, err := otel.ReadCachedHeaders(profile)
		if err == nil && headers != nil {
			debugPrint("Using cached OTEL headers (token still valid)")
			// Resolve Bearer fresh — the cache stores attribution headers only,
			// never the token itself. Try env var (free) then credential-process (~20ms).
			// An expired env-var token is skipped so we fall through to
			// credential-process refresh instead of attaching a stale Bearer.
			if t := os.Getenv("CLAUDE_CODE_MONITORING_TOKEN"); t != "" && !jwt.IsTokenExpired(t) {
				attachBearer(headers, t)
			} else if t, err := getTokenViaCredentialProcess(profile); err == nil && t != "" {
				attachBearer(headers, t)
			} else {
				// No token from env var or credential-process. Emit cached attribution
				// anyway (otelHeadersHelper contract), but log so an ALB 401 is
				// diagnosable instead of silent — the no-token path below logs the same way.
				debugPrint("Layer 1 cache hit but no Bearer token available " +
					"(env var empty, credential-process failed); emitting headers without authorization")
			}
			outputJSON(headers)
			return 0
		}
	}

	// Layer 2: Check environment variable. An expired env-var token is treated
	// as absent so we fall through to credential-process (which handles refresh)
	// instead of attaching a stale token that would yield a silent 401.
	token := os.Getenv("CLAUDE_CODE_MONITORING_TOKEN")
	if token != "" && jwt.IsTokenExpired(token) {
		debugPrint("Environment token CLAUDE_CODE_MONITORING_TOKEN is expired, falling through to credential-process")
		token = ""
	}
	if token != "" {
		debugPrint("Using token from environment variable CLAUDE_CODE_MONITORING_TOKEN")
	} else {
		// Layer 3: Get token via credential-process subprocess
		var err error
		token, err = getTokenViaCredentialProcess(profile)
		if err != nil || token == "" {
			// No token available. Claude Code's otelHeadersHelper contract
			// requires a valid JSON object on stdout; exiting non-zero (or with
			// empty stdout) makes it log "otelHeadersHelper did not return a
			// valid value" on every export cycle and drop the telemetry batch.
			// Emit empty headers instead so export proceeds unattributed.
			debugPrint("Could not obtain authentication token; emitting empty headers")
			return emitEmptyHeaders(profile, testMode)
		}
	}

	// Decode JWT and extract user info
	claims, err := jwt.DecodePayload(token)
	if err != nil {
		// Same contract as above: a malformed token must not crash the helper.
		debugPrint("Error decoding JWT: %v; emitting empty headers", err)
		return emitEmptyHeaders(profile, testMode)
	}

	// Resolve the cost-attribution tag key from config.json. Absent / empty
	// means "Project" (the historical default) — ExtractUserInfoWithTagKey
	// handles the fallback, but we also gracefully tolerate a missing config
	// file here so this binary keeps working in dev/test where config.json
	// isn't always wired up.
	costTagKey := "Project"
	if cfg, cfgErr := config.LoadProfile(profile); cfgErr == nil && cfg.CostAttributionTagKey != "" {
		costTagKey = cfg.CostAttributionTagKey
	}

	userInfo := otel.ExtractUserInfoWithTagKey(claims, costTagKey)
	headers := otel.FormatHeaders(userInfo)

	if testMode {
		// Include Bearer in test output so --test shows the full header set.
		attachBearer(headers, token)
		printTestOutput(userInfo, headers)
	} else {
		// Cache attribution headers only — Bearer token must never be persisted
		// to the plaintext cache file. Add it to output AFTER the cache write.
		tokenExp := int64(claims.GetFloat("exp"))
		if tokenExp > 0 {
			if err := otel.WriteCachedHeaders(profile, headers, tokenExp); err != nil {
				debugPrint("Failed to write cached headers: %v", err)
			}
		} else {
			debugPrint("JWT has no exp claim, skipping cache write")
		}
		attachBearer(headers, token)
		outputJSON(headers)
	}

	return 0
}

// userInfoFromHeaders reconstructs a UserInfo from cached x-* headers so the
// test-mode formatter can display the attributes. It is the inverse of
// otel.FormatHeaders for the fields that round-trip through headers (the cache
// stores headers, not the full UserInfo, so JWT-only fields like account_uuid /
// issuer / subject are not represented and remain empty — that's expected, since
// a cache hit is the IDC path which has no JWT).
func userInfoFromHeaders(h map[string]string) otel.UserInfo {
	return otel.UserInfo{
		Email:          h["x-user-email"],
		UserID:         h["x-user-id"],
		Username:       h["x-user-name"],
		Department:     h["x-department"],
		Team:           h["x-team-id"],
		CostCenter:     h["x-cost-center"],
		OrganizationID: h["x-organization"],
		Location:       h["x-location"],
		Role:           h["x-role"],
		Manager:        h["x-manager"],
		Project:        h["x-project"],
	}
}

// emitEmptyHeaders satisfies Claude Code's otelHeadersHelper contract when no
// usable token is available: it prints a valid (empty) JSON object and returns
// success so telemetry export continues instead of failing every cycle.
//
// It also caches the empty result with a short TTL so subsequent turns serve
// from the file cache (Layer 1) rather than re-spawning credential-process on
// every export — the same per-turn latency this binary is designed to avoid.
// In test mode it only prints, leaving the cache untouched.
func emitEmptyHeaders(profile string, testMode bool) int {
	headers := map[string]string{}
	if testMode {
		printTestOutput(otel.UserInfo{}, headers)
		return 0
	}
	// Only cache the empty result when we can confirm we won't clobber valid
	// attribution. Reaching here means Layer 1 reported a miss, but a miss can
	// also be a transient read failure (a Windows AV lock or a torn read) over a
	// perfectly good populated entry; writing {} in that window would erase real
	// attribution for the whole TTL. EmptyHeadersWriteSafe re-checks the cache
	// and only authorizes the write when the file is absent or genuinely
	// empty/stale. When it isn't safe we still emit {} (the contract is what
	// matters this turn) but leave the existing entry intact so the next turn
	// serves the good attribution from Layer 1.
	if otel.EmptyHeadersWriteSafe(profile) {
		if err := otel.WriteCachedHeaders(profile, headers, time.Now().Unix()+emptyHeadersCacheTTLSeconds); err != nil {
			debugPrint("Failed to cache empty headers: %v", err)
		}
	} else {
		debugPrint("Skipping empty-headers cache write to preserve existing attribution")
	}
	outputJSON(headers)
	return 0
}

func getTokenViaCredentialProcess(profile string) (string, error) {
	cpPath := config.CredentialProcessPath()

	if _, err := os.Stat(cpPath); os.IsNotExist(err) {
		debugPrint("Credential process not found at %s", cpPath)
		return "", fmt.Errorf("credential-process not found")
	}

	debugPrint("Getting token via credential-process...")
	cmd := exec.Command(filepath.Clean(cpPath), "--profile", profile, "--get-monitoring-token") // nosemgrep: go.lang.security.audit.dangerous-exec-command.dangerous-exec-command
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
