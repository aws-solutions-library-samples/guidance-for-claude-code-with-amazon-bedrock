package quota

import (
	"context"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"

	awsconfig "github.com/aws/aws-sdk-go-v2/config"
	v4 "github.com/aws/aws-sdk-go-v2/aws/signer/v4"
)

// Result represents the quota check API response.
type Result struct {
	Allowed bool                   `json:"allowed"`
	Reason  string                 `json:"reason"`
	Message string                 `json:"message"`
	Usage   map[string]interface{} `json:"usage"`
	Policy  map[string]interface{} `json:"policy"`
}

// Check calls the quota API endpoint with the given JWT token.
func Check(endpoint, idToken string, timeout int, failMode string) *Result {
	if idToken == "" {
		// No JWT token — try IAM auth (IDC path)
		return CheckWithIAM(endpoint, timeout, failMode)
	}
	client := &http.Client{Timeout: time.Duration(timeout) * time.Second}

	req, err := http.NewRequest("GET", endpoint+"/check", nil)
	if err != nil {
		return failResult(failMode, "error", fmt.Sprintf("creating request: %v", err))
	}
	req.Header.Set("Authorization", "Bearer "+idToken)

	resp, err := client.Do(req)
	if err != nil {
		return failResult(failMode, "connection_error", fmt.Sprintf("Could not connect to quota service: %v", err))
	}
	defer resp.Body.Close()

	body, _ := io.ReadAll(resp.Body)

	switch resp.StatusCode {
	case 200:
		var result Result
		if err := json.Unmarshal(body, &result); err != nil {
			return failResult(failMode, "parse_error", "Could not parse quota response")
		}
		return &result
	case 401:
		return failResult(failMode, "jwt_invalid", "Quota check authentication failed - invalid or expired token")
	default:
		return failResult(failMode, "api_error", fmt.Sprintf("Quota check failed with status %d", resp.StatusCode))
	}
}

func failResult(failMode, reason, message string) *Result {
	if failMode == "closed" {
		return &Result{Allowed: false, Reason: reason, Message: message}
	}
	return &Result{Allowed: true, Reason: reason}
}

// CheckWithIAM calls the quota API using AWS SigV4 authentication.
// Used by IAM Identity Center (IDC) users who don't have a JWT token.
// The API Gateway validates the IAM credentials and the Lambda extracts
// the user email from the IAM caller ARN session name.
func CheckWithIAM(endpoint string, timeout int, failMode string) *Result {
	ctx := context.Background()

	cfg, err := awsconfig.LoadDefaultConfig(ctx)
	if err != nil {
		return failResult(failMode, "iam_config_error", fmt.Sprintf("Could not load AWS config: %v", err))
	}

	creds, err := cfg.Credentials.Retrieve(ctx)
	if err != nil {
		return failResult(failMode, "iam_creds_error", fmt.Sprintf("Could not retrieve AWS credentials: %v", err))
	}

	url := endpoint + "/check"
	req, err := http.NewRequestWithContext(ctx, "GET", url, nil)
	if err != nil {
		return failResult(failMode, "error", fmt.Sprintf("creating request: %v", err))
	}

	// Sign the request with SigV4 for execute-api service
	signer := v4.NewSigner()
	hash := "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855" // SHA256 of empty body
	err = signer.SignHTTP(ctx, creds, req, hash, "execute-api", cfg.Region, time.Now())
	if err != nil {
		return failResult(failMode, "sigv4_error", fmt.Sprintf("Could not sign request: %v", err))
	}

	client := &http.Client{Timeout: time.Duration(timeout) * time.Second}
	resp, err := client.Do(req)
	if err != nil {
		return failResult(failMode, "connection_error", fmt.Sprintf("Could not connect to quota service: %v", err))
	}
	defer resp.Body.Close()

	body, _ := io.ReadAll(resp.Body)

	switch resp.StatusCode {
	case 200:
		var result Result
		if err := json.Unmarshal(body, &result); err != nil {
			return failResult(failMode, "parse_error", "Could not parse quota response")
		}
		return &result
	case 403:
		return failResult(failMode, "iam_forbidden", "Quota check IAM authentication failed - check execute-api:Invoke permission")
	default:
		return failResult(failMode, "api_error", fmt.Sprintf("Quota check failed with status %d", resp.StatusCode))
	}
}

// PrintStatus prints a human-readable quota status report to stdout.
// For OIDC: extracts email from JWT token.
// For IDC: email comes from the API response (resolved server-side from ARN).
func PrintStatus(result *Result, endpoint, token string) {
	var identity string
	if token != "" {
		identity = emailFromJWT(token)
	}
	// If no email from JWT, check if the API response includes it
	if identity == "" || identity == "unknown" {
		if result.Usage != nil {
			if email, ok := result.Usage["email"].(string); ok && email != "" {
				identity = email
			}
		}
	}
	if identity == "" || identity == "unknown" {
		identity = "unknown (IAM identity)"
	}

	sep := "============================================================"
	fmt.Println(sep)
	fmt.Printf("Quota Status — %s\n", identity)
	fmt.Println(sep)

	switch {
	case result.Reason == "no_policy" || result.Reason == "no_email":
		fmt.Println("Status:  UNLIMITED (no quota policy configured)")
	case !result.Allowed:
		fmt.Println("Status:  BLOCKED")
	default:
		fmt.Println("Status:  ALLOWED")
	}

	if result.Usage != nil {
		fmt.Println()
		fmt.Println("Usage:")
		if mt, ok := result.Usage["monthly_tokens"]; ok {
			ml, _ := result.Usage["monthly_limit"]
			mtf := toFloat(mt)
			mlf := toFloat(ml)
			pct := 0.0
			if mlf > 0 {
				pct = mtf / mlf * 100
			}
			fmt.Printf("  Monthly: %13.0f / %13.0f tokens  (%5.1f%%)  %s\n", mtf, mlf, pct, bar(pct))
		}
		if dt, ok := result.Usage["daily_tokens"]; ok {
			dl, _ := result.Usage["daily_limit"]
			dtf := toFloat(dt)
			dlf := toFloat(dl)
			pct := 0.0
			if dlf > 0 {
				pct = dtf / dlf * 100
			}
			fmt.Printf("  Daily:   %13.0f / %13.0f tokens  (%5.1f%%)  %s\n", dtf, dlf, pct, bar(pct))
		}
	}

	if result.Message != "" && !result.Allowed {
		fmt.Printf("\nNote:    %s\n", result.Message)
	}

	fmt.Println(sep)
}

func bar(pct float64) string {
	width := 20
	capped := pct
	if capped > 100 {
		capped = 100
	}
	filled := int(capped / 100 * float64(width))
	b := make([]byte, width)
	for i := range b {
		if i < filled {
			b[i] = '#'
		} else {
			b[i] = '-'
		}
	}
	return "[" + string(b) + "]"
}

func toFloat(v interface{}) float64 {
	switch n := v.(type) {
	case float64:
		return n
	case int:
		return float64(n)
	case json.Number:
		f, _ := n.Float64()
		return f
	default:
		return 0
	}
}

func emailFromJWT(token string) string {
	parts := strings.Split(token, ".")
	if len(parts) < 2 {
		return "unknown"
	}
	payload := parts[1]
	decoded, err := base64.RawURLEncoding.DecodeString(payload)
	if err != nil {
		return "unknown"
	}
	var claims map[string]interface{}
	if err := json.Unmarshal(decoded, &claims); err != nil {
		return "unknown"
	}
	if email, ok := claims["email"].(string); ok && email != "" {
		return email
	}
	return "unknown"
}
