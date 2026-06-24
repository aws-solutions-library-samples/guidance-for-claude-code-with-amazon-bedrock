package otel

import (
	"testing"

	"ccwb-go/internal/config"
	"ccwb-go/internal/jwt"
)

func testPersonas() []config.PersonaConfig {
	return []config.PersonaConfig{
		{Name: "engineering", Group: "eng-team"},
		{Name: "sales", Group: "sales-team"},
	}
}

func TestExtractUserInfoWithPersona_Match(t *testing.T) {
	claims := jwt.Claims{
		"email":  "alice@example.com",
		"groups": []interface{}{"eng-team"},
	}
	info := ExtractUserInfoWithPersona(claims, "Project", testPersonas(), "groups", "")
	if info.Persona != "engineering" {
		t.Errorf("expected Persona=engineering, got %q", info.Persona)
	}
	// Attribution chain must be intact.
	if info.Email != "alice@example.com" {
		t.Errorf("expected email preserved, got %q", info.Email)
	}
}

func TestExtractUserInfoWithPersona_DeclaredOrder(t *testing.T) {
	claims := jwt.Claims{"groups": []interface{}{"sales-team", "eng-team"}}
	info := ExtractUserInfoWithPersona(claims, "Project", testPersonas(), "groups", "")
	if info.Persona != "engineering" {
		t.Errorf("expected first-declared engineering, got %q", info.Persona)
	}
}

func TestExtractUserInfoWithPersona_NoMatchLeavesEmpty(t *testing.T) {
	claims := jwt.Claims{"groups": []interface{}{"contractors"}}
	info := ExtractUserInfoWithPersona(claims, "Project", testPersonas(), "groups", "")
	if info.Persona != "" {
		t.Errorf("expected empty Persona on no match, got %q", info.Persona)
	}
}

func TestExtractUserInfoWithPersona_Fallback(t *testing.T) {
	claims := jwt.Claims{"groups": []interface{}{"contractors"}}
	info := ExtractUserInfoWithPersona(claims, "Project", testPersonas(), "groups", "sales")
	if info.Persona != "sales" {
		t.Errorf("expected fallback sales, got %q", info.Persona)
	}
}

func TestExtractUserInfoWithPersona_CustomClaimName(t *testing.T) {
	claims := jwt.Claims{"cognito:groups": []interface{}{"sales-team"}}
	info := ExtractUserInfoWithPersona(claims, "Project", testPersonas(), "cognito:groups", "")
	if info.Persona != "sales" {
		t.Errorf("expected sales via cognito:groups, got %q", info.Persona)
	}
}

func TestExtractUserInfoWithPersona_EmptyClaimNameDefaultsToGroups(t *testing.T) {
	claims := jwt.Claims{"groups": []interface{}{"eng-team"}}
	info := ExtractUserInfoWithPersona(claims, "Project", testPersonas(), "", "")
	if info.Persona != "engineering" {
		t.Errorf("expected default 'groups' claim to resolve engineering, got %q", info.Persona)
	}
}

func TestExtractUserInfoWithPersona_NoPersonasConfigured(t *testing.T) {
	claims := jwt.Claims{
		"email":  "alice@example.com",
		"groups": []interface{}{"eng-team"},
	}
	info := ExtractUserInfoWithPersona(claims, "Project", nil, "groups", "")
	if info.Persona != "" {
		t.Errorf("expected empty Persona when no personas configured, got %q", info.Persona)
	}
	// Email still always present.
	if info.Email != "alice@example.com" {
		t.Errorf("expected email preserved, got %q", info.Email)
	}
}

func TestFormatHeaders_PersonaPresent(t *testing.T) {
	info := UserInfo{Email: "alice@example.com", Persona: "engineering"}
	headers := FormatHeaders(info)
	if got := headers["x-persona"]; got != "engineering" {
		t.Errorf("expected x-persona=engineering, got %q", got)
	}
	// Attribution chain: x-user-email always present.
	if headers["x-user-email"] == "" {
		t.Error("expected x-user-email to always be present")
	}
}

func TestFormatHeaders_PersonaEmptyExcluded(t *testing.T) {
	info := UserInfo{Email: "alice@example.com", Persona: ""}
	headers := FormatHeaders(info)
	if _, ok := headers["x-persona"]; ok {
		t.Error("expected x-persona to be omitted when Persona is empty")
	}
	// x-user-email must still be present even with no persona.
	if headers["x-user-email"] != "alice@example.com" {
		t.Errorf("expected x-user-email present, got %q", headers["x-user-email"])
	}
}

func TestHeaderMapping_HasPersona(t *testing.T) {
	if HeaderMapping["persona"] != "x-persona" {
		t.Errorf("expected HeaderMapping[persona]=x-persona, got %q", HeaderMapping["persona"])
	}
}
