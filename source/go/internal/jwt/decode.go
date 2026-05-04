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
