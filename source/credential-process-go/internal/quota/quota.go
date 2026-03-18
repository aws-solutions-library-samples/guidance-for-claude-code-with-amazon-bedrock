package quota

import (
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"time"
)

// Result represents a quota check response.
type Result struct {
	Allowed bool                   `json:"allowed"`
	Reason  string                 `json:"reason"`
	Message string                 `json:"message"`
	Usage   map[string]interface{} `json:"usage"`
	Policy  map[string]interface{} `json:"policy"`
}

// CheckQuota calls the quota API endpoint.
// endpoint: the quota API URL (appends /check)
// idToken: JWT bearer token
// failMode: "open" or "closed"
// timeout: seconds
func CheckQuota(endpoint, idToken, failMode string, timeout int, debug bool) *Result {
	if debug {
		fmt.Fprintln(os.Stderr, "Debug: Checking quota at", endpoint+"/check")
	}

	client := &http.Client{
		Timeout: time.Duration(timeout) * time.Second,
	}

	req, err := http.NewRequest("GET", endpoint+"/check", nil)
	if err != nil {
		if debug {
			fmt.Fprintf(os.Stderr, "Debug: Quota check request creation failed: %v\n", err)
		}
		return failResult(failMode, "error", fmt.Sprintf("Quota check failed: %v", err))
	}
	req.Header.Set("Authorization", "Bearer "+idToken)

	resp, err := client.Do(req)
	if err != nil {
		if debug {
			fmt.Fprintf(os.Stderr, "Debug: Quota check request failed: %v\n", err)
		}
		// Distinguish timeout from connection error by checking if the error
		// is a timeout (the http client wraps timeouts as url.Error with Timeout() true).
		reason := "connection_error"
		msg := fmt.Sprintf("Could not connect to quota service: %v", err)
		if os.IsTimeout(err) {
			reason = "timeout"
			msg = "Quota check timed out. Please try again."
		}
		return failResult(failMode, reason, msg)
	}
	defer resp.Body.Close()

	if resp.StatusCode == http.StatusOK {
		body, err := io.ReadAll(resp.Body)
		if err != nil {
			if debug {
				fmt.Fprintf(os.Stderr, "Debug: Quota check response read failed: %v\n", err)
			}
			return failResult(failMode, "error", fmt.Sprintf("Quota check failed: %v", err))
		}
		var result Result
		if err := json.Unmarshal(body, &result); err != nil {
			if debug {
				fmt.Fprintf(os.Stderr, "Debug: Quota check response parse failed: %v\n", err)
			}
			return failResult(failMode, "error", fmt.Sprintf("Quota check failed: %v", err))
		}
		if debug {
			fmt.Fprintf(os.Stderr, "Debug: Quota check result: allowed=%v, reason=%s\n", result.Allowed, result.Reason)
		}
		return &result
	}

	if resp.StatusCode == http.StatusUnauthorized {
		if debug {
			fmt.Fprintln(os.Stderr, "Debug: Quota check JWT validation failed (401)")
		}
		if failMode == "closed" {
			return &Result{
				Allowed: false,
				Reason:  "jwt_invalid",
				Message: "Quota check authentication failed - invalid or expired token",
			}
		}
		return &Result{Allowed: true, Reason: "jwt_invalid"}
	}

	// Other status codes
	if debug {
		fmt.Fprintf(os.Stderr, "Debug: Quota check returned status %d\n", resp.StatusCode)
	}
	return failResult(failMode, "api_error", fmt.Sprintf("Quota check failed with status %d", resp.StatusCode))
}

// failResult returns an allowed or blocked result depending on failMode.
func failResult(failMode, reason, message string) *Result {
	if failMode == "closed" {
		return &Result{
			Allowed: false,
			Reason:  reason,
			Message: message,
		}
	}
	return &Result{Allowed: true, Reason: reason}
}

// ExtractGroups extracts group memberships from JWT claims.
// Looks in: "groups", "cognito:groups", "custom:department" (prefixed with "department:")
func ExtractGroups(claims map[string]interface{}) []string {
	seen := make(map[string]bool)
	var groups []string

	addGroup := func(g string) {
		if g != "" && !seen[g] {
			seen[g] = true
			groups = append(groups, g)
		}
	}

	extractList := func(key string) {
		val, ok := claims[key]
		if !ok {
			return
		}
		switch v := val.(type) {
		case []interface{}:
			for _, item := range v {
				if s, ok := item.(string); ok {
					addGroup(s)
				}
			}
		case string:
			addGroup(v)
		}
	}

	extractList("groups")
	extractList("cognito:groups")

	if dept, ok := claims["custom:department"]; ok {
		if s, ok := dept.(string); ok && s != "" {
			addGroup("department:" + s)
		}
	}

	return groups
}

// ShouldWarn returns true if any usage percentage >= 80%.
func ShouldWarn(result *Result) bool {
	if result.Usage == nil {
		return false
	}
	for _, key := range []string{"monthly_percent", "daily_percent"} {
		if val, ok := result.Usage[key]; ok {
			if pct := toFloat64(val); pct >= 80 {
				return true
			}
		}
	}
	return false
}

// HandleBlocked prints blocked message to stderr and returns exit code 1.
func HandleBlocked(result *Result) {
	reason := result.Reason
	if reason == "" {
		reason = "unknown"
	}
	message := result.Message
	if message == "" {
		message = "Access blocked due to quota limits"
	}
	_ = reason // reason is available if needed for logging

	fmt.Fprintln(os.Stderr)
	fmt.Fprintln(os.Stderr, "============================================================")
	fmt.Fprintln(os.Stderr, "ACCESS BLOCKED - QUOTA EXCEEDED")
	fmt.Fprintln(os.Stderr, "============================================================")
	fmt.Fprintf(os.Stderr, "\n%s\n\n", message)

	if result.Usage != nil {
		fmt.Fprintln(os.Stderr, "Current Usage:")
		printUsageLine(result.Usage, "monthly")
		printUsageLine(result.Usage, "daily")
	}

	if result.Policy != nil {
		pType, _ := result.Policy["type"].(string)
		pID, _ := result.Policy["identifier"].(string)
		if pType == "" {
			pType = "unknown"
		}
		if pID == "" {
			pID = "unknown"
		}
		fmt.Fprintf(os.Stderr, "\nPolicy: %s:%s\n", pType, pID)
	}

	fmt.Fprintln(os.Stderr, "\nTo request an unblock, contact your administrator.")
	fmt.Fprintln(os.Stderr, "============================================================")
	fmt.Fprintln(os.Stderr)
}

// HandleWarning prints warning to stderr if usage >= 80%.
func HandleWarning(result *Result) {
	if !ShouldWarn(result) {
		return
	}

	fmt.Fprintln(os.Stderr)
	fmt.Fprintln(os.Stderr, "============================================================")
	fmt.Fprintln(os.Stderr, "QUOTA WARNING")
	fmt.Fprintln(os.Stderr, "============================================================")

	if result.Usage != nil {
		printUsageLine(result.Usage, "monthly")
		printUsageLine(result.Usage, "daily")
	}

	fmt.Fprintln(os.Stderr, "============================================================")
	fmt.Fprintln(os.Stderr)
}

// printUsageLine prints a formatted usage line (monthly or daily) to stderr.
func printUsageLine(usage map[string]interface{}, prefix string) {
	tokensKey := prefix + "_tokens"
	limitKey := prefix + "_limit"
	percentKey := prefix + "_percent"

	tokens, hasTokens := usage[tokensKey]
	limit, hasLimit := usage[limitKey]
	if !hasTokens || !hasLimit {
		return
	}

	tokensVal := toFloat64(tokens)
	limitVal := toFloat64(limit)
	pctVal := float64(0)
	if pct, ok := usage[percentKey]; ok {
		pctVal = toFloat64(pct)
	}

	label := "Monthly"
	if prefix == "daily" {
		label = "Daily"
	}
	fmt.Fprintf(os.Stderr, "  %s: %s / %s tokens (%.1f%%)\n",
		label, formatNumber(tokensVal), formatNumber(limitVal), pctVal)
}

// formatNumber formats a number with comma separators.
func formatNumber(n float64) string {
	intVal := int64(n)
	if intVal < 0 {
		return fmt.Sprintf("-%s", formatNumber(-n))
	}
	s := fmt.Sprintf("%d", intVal)
	if len(s) <= 3 {
		return s
	}
	// Insert commas
	result := make([]byte, 0, len(s)+(len(s)-1)/3)
	for i, c := range s {
		if i > 0 && (len(s)-i)%3 == 0 {
			result = append(result, ',')
		}
		result = append(result, byte(c))
	}
	return string(result)
}

// toFloat64 converts a JSON number (which may be float64 or json.Number) to float64.
func toFloat64(v interface{}) float64 {
	switch n := v.(type) {
	case float64:
		return n
	case int:
		return float64(n)
	case int64:
		return float64(n)
	case json.Number:
		f, _ := n.Float64()
		return f
	}
	return 0
}
