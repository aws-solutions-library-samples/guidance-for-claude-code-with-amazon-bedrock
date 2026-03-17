package otel

import (
	"crypto/sha256"
	"fmt"
	"net/url"
	"strings"

	"github.com/golang-jwt/jwt/v5"
)

// UserInfo holds extracted user attributes from JWT claims.
type UserInfo struct {
	Email          string
	UserID         string
	Username       string
	OrganizationID string
	Department     string
	Team           string
	CostCenter     string
	Manager        string
	Location       string
	Role           string
	AccountUUID    string
	Issuer         string
	Subject        string
}

// DecodeJWTPayload decodes a JWT token without verification and returns the claims.
func DecodeJWTPayload(token string) (map[string]interface{}, error) {
	parser := jwt.NewParser(jwt.WithoutClaimsValidation())
	claims := jwt.MapClaims{}
	_, _, err := parser.ParseUnverified(token, claims)
	if err != nil {
		return nil, fmt.Errorf("failed to decode JWT: %w", err)
	}
	return claims, nil
}

// ExtractUserInfo extracts user attributes from JWT claims with fallback chains.
func ExtractUserInfo(payload map[string]interface{}) UserInfo {
	info := UserInfo{}

	// email: email / preferred_username / mail -> "unknown@example.com"
	info.Email = firstString(payload, "email", "preferred_username", "mail")
	if info.Email == "" {
		info.Email = "unknown@example.com"
	}

	// user_id: SHA256 hash of sub formatted as UUID-like string
	sub := getString(payload, "sub")
	if sub == "" {
		sub = getString(payload, "user_id")
	}
	if sub != "" {
		hash := fmt.Sprintf("%x", sha256.Sum256([]byte(sub)))
		h := hash[:32]
		info.UserID = fmt.Sprintf("%s-%s-%s-%s-%s", h[:8], h[8:12], h[12:16], h[16:20], h[20:32])
	}

	// username: cognito:username / preferred_username / email prefix
	info.Username = firstString(payload, "cognito:username", "preferred_username")
	if info.Username == "" {
		parts := strings.SplitN(info.Email, "@", 2)
		info.Username = parts[0]
	}

	// organization: detected from iss domain
	info.OrganizationID = "amazon-internal"
	if issuer := getString(payload, "iss"); issuer != "" {
		info.OrganizationID = detectOrg(issuer)
	}

	// department/team/cost_center/manager/location/role with defaults
	info.Department = firstStringOr(payload, "unspecified", "department", "dept", "division")
	info.Team = firstStringOr(payload, "default-team", "team", "team_id", "group")
	info.CostCenter = firstStringOr(payload, "general", "cost_center", "costCenter", "cost_code")
	info.Manager = firstStringOr(payload, "unassigned", "manager", "manager_email")
	info.Location = firstStringOr(payload, "remote", "location", "office_location", "office")
	info.Role = firstStringOr(payload, "user", "role", "job_title", "title")

	info.AccountUUID = getString(payload, "aud")
	info.Issuer = getString(payload, "iss")
	info.Subject = getString(payload, "sub")

	return info
}

// FormatAsHeaders maps UserInfo to HTTP header key-value pairs for the OTEL collector.
func FormatAsHeaders(info UserInfo) map[string]string {
	mapping := []struct {
		key   string
		value string
	}{
		{"x-user-email", info.Email},
		{"x-user-id", info.UserID},
		{"x-user-name", info.Username},
		{"x-department", info.Department},
		{"x-team-id", info.Team},
		{"x-cost-center", info.CostCenter},
		{"x-organization", info.OrganizationID},
		{"x-location", info.Location},
		{"x-role", info.Role},
		{"x-manager", info.Manager},
	}

	headers := make(map[string]string)
	for _, m := range mapping {
		if m.value != "" {
			headers[m.key] = m.value
		}
	}
	return headers
}

// detectOrg determines the organization from the JWT issuer URL.
func detectOrg(issuer string) string {
	urlToParse := issuer
	if !strings.HasPrefix(issuer, "http://") && !strings.HasPrefix(issuer, "https://") {
		urlToParse = "https://" + issuer
	}

	parsed, err := url.Parse(urlToParse)
	if err != nil || parsed.Hostname() == "" {
		return "amazon-internal"
	}

	hostname := strings.ToLower(parsed.Hostname())

	if strings.HasSuffix(hostname, ".okta.com") || hostname == "okta.com" {
		return "okta"
	}
	if strings.HasSuffix(hostname, ".auth0.com") || hostname == "auth0.com" {
		return "auth0"
	}
	if strings.HasSuffix(hostname, ".microsoftonline.com") || hostname == "microsoftonline.com" {
		return "azure"
	}

	return "amazon-internal"
}

// getString returns a string value from the claims map, or "".
func getString(payload map[string]interface{}, key string) string {
	if v, ok := payload[key]; ok {
		if s, ok := v.(string); ok {
			return s
		}
	}
	return ""
}

// firstString returns the first non-empty string value found for the given keys.
func firstString(payload map[string]interface{}, keys ...string) string {
	for _, k := range keys {
		if v := getString(payload, k); v != "" {
			return v
		}
	}
	return ""
}

// firstStringOr returns the first non-empty string value found for the given keys,
// or the default value if none found.
func firstStringOr(payload map[string]interface{}, defaultVal string, keys ...string) string {
	if v := firstString(payload, keys...); v != "" {
		return v
	}
	return defaultVal
}
