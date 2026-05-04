package otel

import (
	"strings"
	"testing"

	"github.com/bluedoors/ccwb-binaries/internal/jwt"
)

func TestExtractUserInfo_AllFields(t *testing.T) {
	claims := jwt.Claims{
		"email":              "user@example.com",
		"sub":                "user-id-123",
		"cognito:username":   "jdoe",
		"iss":                "https://dev-12345.okta.com",
		"department":         "engineering",
		"team":               "platform",
		"cost_center":        "CC-100",
		"manager":            "boss@example.com",
		"location":           "NYC",
		"role":               "developer",
		"aud":                "client-id-abc",
	}

	info := ExtractUserInfo(claims)

	if info.Email != "user@example.com" {
		t.Errorf("Email = %q, want user@example.com", info.Email)
	}
	if info.Username != "jdoe" {
		t.Errorf("Username = %q, want jdoe", info.Username)
	}
	if info.OrganizationID != "okta" {
		t.Errorf("OrganizationID = %q, want okta", info.OrganizationID)
	}
	if info.Department != "engineering" {
		t.Errorf("Department = %q, want engineering", info.Department)
	}
	if info.Team != "platform" {
		t.Errorf("Team = %q, want platform", info.Team)
	}
	if info.CostCenter != "CC-100" {
		t.Errorf("CostCenter = %q, want CC-100", info.CostCenter)
	}
	if info.Manager != "boss@example.com" {
		t.Errorf("Manager = %q, want boss@example.com", info.Manager)
	}
	if info.Location != "NYC" {
		t.Errorf("Location = %q, want NYC", info.Location)
	}
	if info.Role != "developer" {
		t.Errorf("Role = %q, want developer", info.Role)
	}

	// UUID format: 8-4-4-4-12
	parts := strings.Split(info.UserID, "-")
	if len(parts) != 5 || len(parts[0]) != 8 || len(parts[1]) != 4 || len(parts[2]) != 4 || len(parts[3]) != 4 || len(parts[4]) != 12 {
		t.Errorf("UserID format incorrect: %q", info.UserID)
	}
}

func TestExtractUserInfo_Defaults(t *testing.T) {
	claims := jwt.Claims{}

	info := ExtractUserInfo(claims)

	if info.Email != "unknown@example.com" {
		t.Errorf("Email = %q, want unknown@example.com", info.Email)
	}
	if info.Department != "unspecified" {
		t.Errorf("Department = %q, want unspecified", info.Department)
	}
	if info.Team != "default-team" {
		t.Errorf("Team = %q, want default-team", info.Team)
	}
	if info.CostCenter != "general" {
		t.Errorf("CostCenter = %q, want general", info.CostCenter)
	}
	if info.Manager != "unassigned" {
		t.Errorf("Manager = %q, want unassigned", info.Manager)
	}
	if info.Location != "remote" {
		t.Errorf("Location = %q, want remote", info.Location)
	}
	if info.Role != "user" {
		t.Errorf("Role = %q, want user", info.Role)
	}
	if info.OrganizationID != "amazon-internal" {
		t.Errorf("OrganizationID = %q, want amazon-internal", info.OrganizationID)
	}
}

func TestExtractUserInfo_EmailFallback(t *testing.T) {
	claims := jwt.Claims{
		"preferred_username": "jdoe@corp.com",
	}
	info := ExtractUserInfo(claims)
	if info.Email != "jdoe@corp.com" {
		t.Errorf("Email = %q, want jdoe@corp.com", info.Email)
	}
}

func TestExtractUserInfo_MailFallback(t *testing.T) {
	claims := jwt.Claims{
		"mail": "jdoe@corp.com",
	}
	info := ExtractUserInfo(claims)
	if info.Email != "jdoe@corp.com" {
		t.Errorf("Email = %q, want jdoe@corp.com", info.Email)
	}
}

func TestExtractUserInfo_UsernameFallbackToEmail(t *testing.T) {
	claims := jwt.Claims{
		"email": "jane.doe@company.com",
	}
	info := ExtractUserInfo(claims)
	if info.Username != "jane.doe" {
		t.Errorf("Username = %q, want jane.doe", info.Username)
	}
}

func TestExtractUserInfo_DepartmentFallbacks(t *testing.T) {
	// dept fallback
	claims := jwt.Claims{"dept": "sales"}
	info := ExtractUserInfo(claims)
	if info.Department != "sales" {
		t.Errorf("Department = %q, want sales", info.Department)
	}

	// division fallback
	claims = jwt.Claims{"division": "R&D"}
	info = ExtractUserInfo(claims)
	if info.Department != "R&D" {
		t.Errorf("Department = %q, want R&D", info.Department)
	}
}

func TestExtractUserInfo_CognitoIssuer(t *testing.T) {
	claims := jwt.Claims{
		"iss": "https://cognito-idp.us-east-1.amazonaws.com/us-east-1_ABC123",
	}
	info := ExtractUserInfo(claims)
	if info.OrganizationID != "cognito" {
		t.Errorf("OrganizationID = %q, want cognito", info.OrganizationID)
	}
}

func TestExtractUserInfo_AzureIssuer(t *testing.T) {
	claims := jwt.Claims{
		"iss": "https://login.microsoftonline.com/tenant-id/v2.0",
	}
	info := ExtractUserInfo(claims)
	if info.OrganizationID != "azure" {
		t.Errorf("OrganizationID = %q, want azure", info.OrganizationID)
	}
}

func TestExtractUserInfo_ConsistentHash(t *testing.T) {
	claims1 := jwt.Claims{"sub": "user-123"}
	claims2 := jwt.Claims{"sub": "user-123"}

	info1 := ExtractUserInfo(claims1)
	info2 := ExtractUserInfo(claims2)

	if info1.UserID != info2.UserID {
		t.Errorf("Same sub should produce same UserID: %q vs %q", info1.UserID, info2.UserID)
	}

	claims3 := jwt.Claims{"sub": "different-user"}
	info3 := ExtractUserInfo(claims3)
	if info1.UserID == info3.UserID {
		t.Error("Different subs should produce different UserIDs")
	}
}

func TestExtractPrincipalTag_Flat(t *testing.T) {
	claims := jwt.Claims{
		"https://aws.amazon.com/tags/principal_tags/Project": "Alpha",
	}
	if got := ExtractPrincipalTag(claims, "Project"); got != "Alpha" {
		t.Errorf("flat form: got %q, want Alpha", got)
	}
}

func TestExtractPrincipalTag_NestedString(t *testing.T) {
	claims := jwt.Claims{
		"https://aws.amazon.com/tags": map[string]interface{}{
			"principal_tags": map[string]interface{}{
				"Project": "Beta",
			},
			"transitive_tag_keys": []interface{}{"Project"},
		},
	}
	if got := ExtractPrincipalTag(claims, "Project"); got != "Beta" {
		t.Errorf("nested-string: got %q, want Beta", got)
	}
}

func TestExtractPrincipalTag_NestedArray(t *testing.T) {
	claims := jwt.Claims{
		"https://aws.amazon.com/tags": map[string]interface{}{
			"principal_tags": map[string]interface{}{
				"Project": []interface{}{"Gamma"},
			},
		},
	}
	if got := ExtractPrincipalTag(claims, "Project"); got != "Gamma" {
		t.Errorf("nested-array: got %q, want Gamma", got)
	}
}

func TestExtractPrincipalTag_Absent(t *testing.T) {
	claims := jwt.Claims{"email": "user@example.com"}
	if got := ExtractPrincipalTag(claims, "Project"); got != "" {
		t.Errorf("absent: got %q, want empty string", got)
	}
}

func TestExtractPrincipalTag_Malformed(t *testing.T) {
	cases := []jwt.Claims{
		{"https://aws.amazon.com/tags": "not-an-object"},
		{"https://aws.amazon.com/tags": map[string]interface{}{"principal_tags": "not-an-object"}},
		{"https://aws.amazon.com/tags": map[string]interface{}{"principal_tags": map[string]interface{}{"Project": 42}}},
		{"https://aws.amazon.com/tags": map[string]interface{}{"principal_tags": map[string]interface{}{"Project": []interface{}{}}}},
		{"https://aws.amazon.com/tags": map[string]interface{}{"principal_tags": map[string]interface{}{"Project": []interface{}{42}}}},
		{"https://aws.amazon.com/tags/principal_tags/Project": 99},
	}
	for i, c := range cases {
		if got := ExtractPrincipalTag(c, "Project"); got != "" {
			t.Errorf("malformed case %d: got %q, want empty string", i, got)
		}
	}
}

func TestExtractPrincipalTag_FlatWinsOverNested(t *testing.T) {
	// If an IdP emits both shapes, flat (the Okta convention) is preferred.
	claims := jwt.Claims{
		"https://aws.amazon.com/tags/principal_tags/Project": "flat-wins",
		"https://aws.amazon.com/tags": map[string]interface{}{
			"principal_tags": map[string]interface{}{
				"Project": "nested-loses",
			},
		},
	}
	if got := ExtractPrincipalTag(claims, "Project"); got != "flat-wins" {
		t.Errorf("flat-vs-nested: got %q, want flat-wins", got)
	}
}

func TestExtractUserInfo_ProjectFromFlatClaim(t *testing.T) {
	claims := jwt.Claims{
		"email": "user@example.com",
		"https://aws.amazon.com/tags/principal_tags/Project": "Delta",
	}
	info := ExtractUserInfo(claims)
	if info.Project != "Delta" {
		t.Errorf("Project = %q, want Delta", info.Project)
	}
}

func TestExtractUserInfo_ProjectFromNestedClaim(t *testing.T) {
	claims := jwt.Claims{
		"email": "user@example.com",
		"https://aws.amazon.com/tags": map[string]interface{}{
			"principal_tags": map[string]interface{}{
				"Project": []interface{}{"Epsilon"},
			},
		},
	}
	info := ExtractUserInfo(claims)
	if info.Project != "Epsilon" {
		t.Errorf("Project = %q, want Epsilon", info.Project)
	}
}

func TestExtractUserInfo_ProjectEmptyWhenAbsent(t *testing.T) {
	// Customers who haven't configured the IdP claim get empty string,
	// which is the signal to FormatHeaders to omit x-project entirely.
	claims := jwt.Claims{"email": "user@example.com"}
	info := ExtractUserInfo(claims)
	if info.Project != "" {
		t.Errorf("Project = %q, want empty string", info.Project)
	}
}

func TestExtractUserInfoWithTagKey_CostCenter(t *testing.T) {
	// Customer renames the cost-attribution tag to CostCenter. The JWT
	// carries the value under the CostCenter claim URL; the default key
	// "Project" would miss it. ExtractUserInfoWithTagKey honors the override.
	claims := jwt.Claims{
		"email": "user@example.com",
		"https://aws.amazon.com/tags/principal_tags/CostCenter": "CC-123",
	}
	info := ExtractUserInfoWithTagKey(claims, "CostCenter")
	if info.Project != "CC-123" {
		t.Errorf("Project (from CostCenter claim) = %q, want CC-123", info.Project)
	}
}

func TestExtractUserInfoWithTagKey_EmptyFallsBackToProject(t *testing.T) {
	// Older bundles that predate the configurable key leave
	// CostAttributionTagKey empty; the function must treat "" as "Project".
	claims := jwt.Claims{
		"email": "user@example.com",
		"https://aws.amazon.com/tags/principal_tags/Project": "Zeta",
	}
	info := ExtractUserInfoWithTagKey(claims, "")
	if info.Project != "Zeta" {
		t.Errorf("Project = %q, want Zeta (empty tagKey should fall back)", info.Project)
	}
}

func TestExtractUserInfoWithTagKey_CustomKeyIgnoresDefaultClaim(t *testing.T) {
	// When the customer sets a custom key, we should NOT accidentally
	// pick up a stale "Project" claim from an old IdP config.
	claims := jwt.Claims{
		"email": "user@example.com",
		"https://aws.amazon.com/tags/principal_tags/Project": "should-be-ignored",
	}
	info := ExtractUserInfoWithTagKey(claims, "BillingCode")
	if info.Project != "" {
		t.Errorf("Project = %q, want empty (custom key misses should NOT fall back to Project)", info.Project)
	}
}
