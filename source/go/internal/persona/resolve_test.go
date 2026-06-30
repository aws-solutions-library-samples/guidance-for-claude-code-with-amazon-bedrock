package persona

import (
	"encoding/json"
	"os"
	"path/filepath"
	"testing"

	"ccwb-go/internal/config"
)

// sharedFixturesPath locates the cross-language parity oracle relative to this
// package: source/go/internal/persona -> source/tests/fixtures/...
const sharedFixturesPath = "../../../tests/fixtures/persona_resolution_cases.json"

// fixtureCase mirrors one object in persona_resolution_cases.json. The persona
// entries carry at least name/group; extra keys (display_name, description,
// enforcement_mode) are tolerated by encoding/json.
type fixtureCase struct {
	Name     string                 `json:"name"`
	Groups   []string               `json:"groups"`
	Personas []config.PersonaConfig `json:"personas"`
	Fallback *string                `json:"fallback"`
	Expected *string                `json:"expected"`
}

func loadFixtureCases(t *testing.T) []fixtureCase {
	t.Helper()
	data, err := os.ReadFile(filepath.Clean(sharedFixturesPath))
	if err != nil {
		t.Fatalf("reading shared fixtures: %v", err)
	}
	var cases []fixtureCase
	if err := json.Unmarshal(data, &cases); err != nil {
		t.Fatalf("parsing shared fixtures: %v", err)
	}
	if len(cases) < 5 {
		t.Fatalf("expected >=5 shared fixture cases, got %d", len(cases))
	}
	return cases
}

func resolvedName(p *config.PersonaConfig) *string {
	if p == nil {
		return nil
	}
	return &p.Name
}

func ptrEqual(a, b *string) bool {
	if a == nil || b == nil {
		return a == nil && b == nil
	}
	return *a == *b
}

func show(p *string) string {
	if p == nil {
		return "<nil>"
	}
	return *p
}

// TestResolveAgainstSharedFixtures is the parity test: the Go resolver must
// produce exactly the persona name each shared fixture expects (the same file
// drives the Python resolver in tests/test_persona_resolution.py).
func TestResolveAgainstSharedFixtures(t *testing.T) {
	for _, tc := range loadFixtureCases(t) {
		t.Run(tc.Name, func(t *testing.T) {
			fallback := ""
			if tc.Fallback != nil {
				fallback = *tc.Fallback
			}
			got, err := Resolve(tc.Groups, tc.Personas, fallback)
			if err != nil {
				t.Fatalf("unexpected error: %v", err)
			}
			if !ptrEqual(resolvedName(got), tc.Expected) {
				t.Errorf("Resolve = %s, want %s", show(resolvedName(got)), show(tc.Expected))
			}
		})
	}
}

// TestResolveTable covers the algorithm directly, independent of the fixture file.
func TestResolveTable(t *testing.T) {
	personas := []config.PersonaConfig{
		{Name: "engineering", Group: "eng-team"},
		{Name: "sales", Group: "sales-team"},
	}

	tests := []struct {
		name     string
		groups   []string
		personas []config.PersonaConfig
		fallback string
		want     *string
	}{
		{"single match", []string{"eng-team"}, personas, "", strptr("engineering")},
		{"no match no fallback", []string{"contractors"}, personas, "", nil},
		{"no match with fallback", []string{"contractors"}, personas, "sales", strptr("sales")},
		{"multi match first declared", []string{"sales-team", "eng-team"}, personas, "", strptr("engineering")},
		{"empty personas", []string{"eng-team"}, nil, "", nil},
		{"empty personas with fallback", []string{"eng-team"}, nil, "engineering", nil},
		{"unknown fallback", []string{"contractors"}, personas, "ghost", nil},
		{"match beats fallback", []string{"sales-team"}, personas, "engineering", strptr("sales")},
		{"empty groups with fallback", []string{}, personas, "engineering", strptr("engineering")},
		{"case sensitive group", []string{"Eng-Team"}, personas, "", nil},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got, err := Resolve(tt.groups, tt.personas, tt.fallback)
			if err != nil {
				t.Fatalf("unexpected error: %v", err)
			}
			if !ptrEqual(resolvedName(got), tt.want) {
				t.Errorf("Resolve = %s, want %s", show(resolvedName(got)), show(tt.want))
			}
		})
	}
}

// TestResolveReturnsPointerIntoSlice verifies the returned persona is the actual
// element (so callers read its RoleARN), not a copy of a zero value.
func TestResolveReturnsPointerIntoSlice(t *testing.T) {
	personas := []config.PersonaConfig{
		{Name: "engineering", Group: "eng-team", RoleARN: "arn:aws:iam::111122223333:role/eng"},
	}
	got, err := Resolve([]string{"eng-team"}, personas, "")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if got == nil {
		t.Fatal("expected a persona, got nil")
	}
	if got.RoleARN != "arn:aws:iam::111122223333:role/eng" {
		t.Errorf("RoleARN = %q, want the persona's role ARN", got.RoleARN)
	}
}

func strptr(s string) *string { return &s }
