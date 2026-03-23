package quota

import (
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"time"
)

// Result represents the quota check API response.
type Result struct {
	Allowed bool              `json:"allowed"`
	Reason  string            `json:"reason"`
	Message string            `json:"message"`
	Usage   map[string]interface{} `json:"usage"`
	Policy  map[string]interface{} `json:"policy"`
}

// Check calls the quota API endpoint with the given JWT token.
func Check(endpoint, idToken string, timeout int, failMode string) *Result {
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
