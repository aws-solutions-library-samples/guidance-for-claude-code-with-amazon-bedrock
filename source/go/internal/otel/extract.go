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
	AccountUUID    string `json:"account_uuid"`
	Issuer         string `json:"issuer"`
	Subject        string `json:"subject"`
}

// ExtractUserInfo extracts user attributes from JWT claims with fallback chains.
func ExtractUserInfo(claims jwt.Claims) UserInfo {
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

	// Technical fields
	info.AccountUUID = claims.GetString("aud")
	info.Issuer = claims.GetString("iss")
	info.Subject = claims.GetString("sub")

	return info
}

func firstNonEmpty(values ...string) string {
	for _, v := range values {
		if v != "" {
			return v
		}
	}
	return ""
}
