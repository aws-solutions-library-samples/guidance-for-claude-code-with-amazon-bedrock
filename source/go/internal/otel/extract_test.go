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
