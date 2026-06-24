package jwt

import (
	"encoding/base64"
	"encoding/json"
	"fmt"
	"strings"
)

// Claims is a map of JWT payload claims.
type Claims map[string]interface{}

// GetString returns a string claim value, or empty string if missing/wrong type.
func (c Claims) GetString(key string) string {
	v, ok := c[key]
	if !ok {
		return ""
	}
	s, ok := v.(string)
	if !ok {
		return ""
	}
	return s
}

// GetFloat returns a float64 claim value, or 0 if missing/wrong type.
func (c Claims) GetFloat(key string) float64 {
	v, ok := c[key]
	if !ok {
		return 0
	}
	f, ok := v.(float64)
	if !ok {
		return 0
	}
	return f
}

// GetStringSlice returns a claim as a []string. It handles the shapes a `groups`
// (or `roles`, `cognito:groups`, …) claim takes across IdPs:
//
//   - a JSON array of strings (`[]interface{}`) -> the string elements, in order
//     (non-string elements are skipped defensively);
//   - a scalar string -> a single-element slice (some IdPs emit one group as a
//     bare string rather than a 1-element array);
//   - a missing key or any other type -> nil.
//
// An array that is present but empty (or contains only non-string elements)
// returns a non-nil, zero-length slice, distinguishing "the claim was present
// but listed no groups" from "the claim was absent" (nil). Stdlib only — no new
// dependencies (cold-start budget, binary-distribution.md).
func (c Claims) GetStringSlice(key string) []string {
	v, ok := c[key]
	if !ok {
		return nil
	}
	switch val := v.(type) {
	case []interface{}:
		result := make([]string, 0, len(val))
		for _, elem := range val {
			if s, ok := elem.(string); ok {
				result = append(result, s)
			}
		}
		return result
	case string:
		return []string{val}
	default:
		return nil
	}
}

// DecodePayload decodes the payload (second segment) of a JWT without signature verification.
func DecodePayload(token string) (Claims, error) {
	parts := strings.SplitN(token, ".", 3)
	if len(parts) != 3 {
		return nil, fmt.Errorf("invalid JWT: expected 3 parts, got %d", len(parts))
	}

	payload := parts[1]

	// Add base64 padding
	switch len(payload) % 4 {
	case 2:
		payload += "=="
	case 3:
		payload += "="
	}

	decoded, err := base64.URLEncoding.DecodeString(payload)
	if err != nil {
		return nil, fmt.Errorf("base64 decode failed: %w", err)
	}

	var claims Claims
	if err := json.Unmarshal(decoded, &claims); err != nil {
		return nil, fmt.Errorf("JSON decode failed: %w", err)
	}

	return claims, nil
}
