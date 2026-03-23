package otel

// HeaderMapping maps UserInfo field names to HTTP header names.
var HeaderMapping = map[string]string{
	"email":           "x-user-email",
	"user_id":         "x-user-id",
	"username":        "x-user-name",
	"department":      "x-department",
	"team":            "x-team-id",
	"cost_center":     "x-cost-center",
	"organization_id": "x-organization",
	"location":        "x-location",
	"role":            "x-role",
	"manager":         "x-manager",
}

// FormatHeaders converts UserInfo to a map of HTTP header name -> value.
// Empty values are excluded.
func FormatHeaders(info UserInfo) map[string]string {
	attrs := map[string]string{
		"email":           info.Email,
		"user_id":         info.UserID,
		"username":        info.Username,
		"department":      info.Department,
		"team":            info.Team,
		"cost_center":     info.CostCenter,
		"organization_id": info.OrganizationID,
		"location":        info.Location,
		"role":            info.Role,
		"manager":         info.Manager,
	}

	headers := make(map[string]string)
	for attrKey, headerName := range HeaderMapping {
		if val, ok := attrs[attrKey]; ok && val != "" {
			headers[headerName] = val
		}
	}
	return headers
}
