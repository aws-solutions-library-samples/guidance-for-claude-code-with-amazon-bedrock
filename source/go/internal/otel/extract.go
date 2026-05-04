package otel

import (
	"crypto/sha256"
	"fmt"
	"strings"

	"github.com/bluedoors/ccwb-binaries/internal/jwt"
	"github.com/bluedoors/ccwb-binaries/internal/provider"
)

// UserInfo holds extracted user attributes from JWT claims.
type UserInfo struct {
	Email          string `json:"email"`
	UserID         string `json:"user_id"`
	Username       string `json:"username"`
	OrganizationID string `json:"organization_id"`
	Department     string `json:"department"`
	Team           string `json:"team"`
	CostCenter     string `json:"cost_center"`
	Manager        string `json:"manager"`
	Location       string `json:"location"`
	Role           string `json:"role"`
	Project        string `json:"project"`
	AccountUUID    string `json:"account_uuid"`
	Issuer         string `json:"issuer"`
	Subject        string `json:"subject"`
}

// ExtractUserInfo extracts user attributes from JWT claims with fallback chains.
// Kept as a default-key shim so callers that don't need the configurable
// cost-attribution key can stay unchanged; threads "Project" through to
// ExtractUserInfoWithTagKey.
func ExtractUserInfo(claims jwt.Claims) UserInfo {
	return ExtractUserInfoWithTagKey(claims, "Project")
}

// ExtractUserInfoWithTagKey is the same as ExtractUserInfo but reads the
// cost-attribution session tag under an arbitrary key name (e.g. "CostCenter").
// Callers that load config.json pass cfg.CostAttributionTagKey here, falling
// back to "Project" when that field is empty (older bundles predating the
// configurable key).
//
// Note: the AWS session-tag key is an IAM-level construct. The OTel header
// name (x-project) and collector dimension (project) remain unchanged and are
// independent of this key — they're our internal cost-attribution convention,
// not AWS state. A customer who sets CostAttributionTagKey="CostCenter" still
// sees the metric dimension labeled "project" in CloudWatch, with the value
// pulled from the CostCenter session tag.
func ExtractUserInfoWithTagKey(claims jwt.Claims, tagKey string) UserInfo {
	if tagKey == "" {
		tagKey = "Project"
	}
	info := UserInfo{}

	// Email
	info.Email = firstNonEmpty(
		claims.GetString("email"),
		claims.GetString("preferred_username"),
		claims.GetString("mail"),
	)
	if info.Email == "" {
		info.Email = "unknown@example.com"
	}

	// User ID - hash for privacy, format as UUID
	rawID := claims.GetString("sub")
	if rawID == "" {
		rawID = claims.GetString("user_id")
	}
	if rawID != "" {
		hash := sha256.Sum256([]byte(rawID))
		hex := fmt.Sprintf("%x", hash)
		// Take first 32 hex chars, format as 8-4-4-4-12
		h := hex[:32]
		info.UserID = fmt.Sprintf("%s-%s-%s-%s-%s", h[:8], h[8:12], h[12:16], h[16:20], h[20:32])
	}

	// Username
	info.Username = firstNonEmpty(
		claims.GetString("cognito:username"),
		claims.GetString("preferred_username"),
	)
	if info.Username == "" {
		info.Username = strings.SplitN(info.Email, "@", 2)[0]
	}

	// Organization - detect from issuer
	info.OrganizationID = "amazon-internal"
	if iss := claims.GetString("iss"); iss != "" {
		detected := provider.Detect(iss)
		if detected != "oidc" {
			info.OrganizationID = detected
		}
	}

	// Department
	info.Department = firstNonEmpty(
		claims.GetString("department"),
		claims.GetString("dept"),
		claims.GetString("division"),
	)
	if info.Department == "" {
		info.Department = "unspecified"
	}

	// Team
	info.Team = firstNonEmpty(
		claims.GetString("team"),
		claims.GetString("team_id"),
		claims.GetString("group"),
	)
	if info.Team == "" {
		info.Team = "default-team"
	}

	// Cost center
	info.CostCenter = firstNonEmpty(
		claims.GetString("cost_center"),
		claims.GetString("costCenter"),
		claims.GetString("cost_code"),
	)
	if info.CostCenter == "" {
		info.CostCenter = "general"
	}

	// Manager
	info.Manager = firstNonEmpty(
		claims.GetString("manager"),
		claims.GetString("manager_email"),
	)
	if info.Manager == "" {
		info.Manager = "unassigned"
	}

	// Location
	info.Location = firstNonEmpty(
		claims.GetString("location"),
		claims.GetString("office_location"),
		claims.GetString("office"),
	)
	if info.Location == "" {
		info.Location = "remote"
	}

	// Role
	info.Role = firstNonEmpty(
		claims.GetString("role"),
		claims.GetString("job_title"),
		claims.GetString("title"),
	)
	if info.Role == "" {
		info.Role = "user"
	}

	// Cost-attribution — from the AWS session-tag claim shipped by the IdP.
	// The claim key name comes from the profile config (default "Project",
	// override via cost_attribution_tag_key for customers using CostCenter /
	// BillingCode / etc). We still store the value in info.Project because
	// the downstream OTel header / dashboard dimension is "project" — that's
	// our internal convention, not AWS state. Intentionally left empty when
	// absent so FormatHeaders omits x-project and the collector falls back
	// to the resource attribute `project=default`.
	info.Project = ExtractPrincipalTag(claims, tagKey)

	// Technical fields
	info.AccountUUID = claims.GetString("aud")
	info.Issuer = claims.GetString("iss")
	info.Subject = claims.GetString("sub")

	return info
}

// ExtractPrincipalTag returns the value of an AWS session-tag claim. STS and
// the IdP-side recipes in assets/docs/COST_ATTRIBUTION.md both accept two
// shapes:
//
//   - Flat:   {"https://aws.amazon.com/tags/principal_tags/<Key>": "<value>"}
//   - Nested: {"https://aws.amazon.com/tags": {"principal_tags": {"<Key>": "<value>" | ["<value>", ...]}}}
//
// Returns empty string when the tag isn't present or the claim is malformed.
// Caller should treat empty as "no value" rather than an error.
func ExtractPrincipalTag(claims jwt.Claims, tagKey string) string {
	// Flat form — most common on Okta (the claim name *is* the URL).
	if s, ok := claims["https://aws.amazon.com/tags/principal_tags/"+tagKey].(string); ok && s != "" {
		return s
	}

	// Nested form — common on Auth0 Actions / Azure claim transforms / Cognito
	// Pre-Token-Generation Lambdas. Value at principal_tags.<Key> may be either
	// a plain string or a single-element array (AWS STS accepts both).
	root, ok := claims["https://aws.amazon.com/tags"].(map[string]interface{})
	if !ok {
		return ""
	}
	principalTags, ok := root["principal_tags"].(map[string]interface{})
	if !ok {
		return ""
	}
	switch v := principalTags[tagKey].(type) {
	case string:
		return v
	case []interface{}:
		if len(v) > 0 {
			if s, ok := v[0].(string); ok {
				return s
			}
		}
	}
	return ""
}

func firstNonEmpty(values ...string) string {
	for _, v := range values {
		if v != "" {
			return v
		}
	}
	return ""
}
