package config

import (
	"encoding/json"
	"testing"
)

// TestPersonaFieldsAbsentRoundTrip verifies that a legacy config.json with no
// persona fields decodes with empty/zero persona state and re-marshals without
// emitting any persona keys. This is the backward-compat gate: older bundles
// (and any non-persona deployment) must keep working with FederatedRoleARN.
func TestPersonaFieldsAbsentRoundTrip(t *testing.T) {
	raw := `{"provider_domain":"company.okta.com","client_id":"abc","federated_role_arn":"arn:aws:iam::111122223333:role/legacy"}`

	var p ProfileConfig
	if err := json.Unmarshal([]byte(raw), &p); err != nil {
		t.Fatalf("unmarshal failed: %v", err)
	}
	if p.Personas != nil {
		t.Fatalf("expected Personas nil for legacy input, got %#v", p.Personas)
	}
	if len(p.Personas) != 0 {
		t.Fatalf("expected zero personas, got %d", len(p.Personas))
	}
	if p.GroupsClaimName != "" {
		t.Fatalf("expected empty GroupsClaimName, got %q", p.GroupsClaimName)
	}
	if p.FallbackPersona != "" {
		t.Fatalf("expected empty FallbackPersona, got %q", p.FallbackPersona)
	}

	out, err := json.Marshal(p)
	if err != nil {
		t.Fatalf("marshal failed: %v", err)
	}
	got := string(out)
	for _, key := range []string{"personas", "groups_claim_name", "fallback_persona"} {
		if contains(got, key) {
			t.Fatalf("expected %q omitted when unset, got: %s", key, got)
		}
	}
}

// TestPersonaConfigPopulatedRoundTrip verifies that a fully populated persona
// list survives an unmarshal -> marshal -> unmarshal cycle unchanged, with the
// snake_case JSON tags that the Python Profile writer emits (config-sync.md
// parity). The two reference personas (engineering, sales) from design §3 are
// used so the fixture exercises both the unrestricted and restricted shapes.
func TestPersonaConfigPopulatedRoundTrip(t *testing.T) {
	raw := `{
        "provider_domain": "company.okta.com",
        "client_id": "abc",
        "federated_role_arn": "arn:aws:iam::111122223333:role/legacy",
        "groups_claim_name": "groups",
        "fallback_persona": "engineering",
        "personas": [
            {
                "name": "engineering",
                "display_name": "Engineering",
                "group": "eng-team",
                "allowed_models": ["anthropic.*"],
                "role_arn": "arn:aws:iam::111122223333:role/persona-Engineering",
                "monthly_token_limit": 300000000,
                "enforcement_mode": "block",
                "cost_tags": {"Team": "Engineering", "CostCenter": "CC-1001"}
            },
            {
                "name": "sales",
                "display_name": "Sales",
                "group": "sales-team",
                "allowed_models": ["anthropic.*haiku*"],
                "denied_models": ["anthropic.*sonnet*", "anthropic.*opus*"],
                "role_arn": "arn:aws:iam::111122223333:role/persona-Sales",
                "monthly_token_limit": 10000000,
                "enforcement_mode": "block",
                "cost_tags": {"Team": "Sales"}
            }
        ]
    }`

	var first ProfileConfig
	if err := json.Unmarshal([]byte(raw), &first); err != nil {
		t.Fatalf("first unmarshal failed: %v", err)
	}

	// Spot-check the decoded contract before testing the round-trip.
	if len(first.Personas) != 2 {
		t.Fatalf("expected 2 personas, got %d", len(first.Personas))
	}
	if first.GroupsClaimName != "groups" {
		t.Errorf("GroupsClaimName = %q, want \"groups\"", first.GroupsClaimName)
	}
	if first.FallbackPersona != "engineering" {
		t.Errorf("FallbackPersona = %q, want \"engineering\"", first.FallbackPersona)
	}

	eng := first.Personas[0]
	if eng.Name != "engineering" || eng.Group != "eng-team" {
		t.Errorf("engineering persona decoded wrong: %+v", eng)
	}
	if eng.MonthlyTokenLimit != 300000000 {
		t.Errorf("engineering MonthlyTokenLimit = %d, want 300000000", eng.MonthlyTokenLimit)
	}
	if eng.RoleARN != "arn:aws:iam::111122223333:role/persona-Engineering" {
		t.Errorf("engineering RoleARN = %q", eng.RoleARN)
	}
	if got := eng.CostTags["CostCenter"]; got != "CC-1001" {
		t.Errorf("engineering CostTags[CostCenter] = %q, want CC-1001", got)
	}

	sales := first.Personas[1]
	if len(sales.DeniedModels) != 2 {
		t.Errorf("sales DeniedModels = %v, want 2 entries", sales.DeniedModels)
	}

	// Round-trip: marshal then unmarshal again, compare via canonical JSON.
	out, err := json.Marshal(first)
	if err != nil {
		t.Fatalf("marshal failed: %v", err)
	}
	var second ProfileConfig
	if err := json.Unmarshal(out, &second); err != nil {
		t.Fatalf("second unmarshal failed: %v", err)
	}

	firstJSON, _ := json.Marshal(first.Personas)
	secondJSON, _ := json.Marshal(second.Personas)
	if string(firstJSON) != string(secondJSON) {
		t.Fatalf("persona round-trip mismatch:\n first:  %s\n second: %s", firstJSON, secondJSON)
	}
	if first.GroupsClaimName != second.GroupsClaimName || first.FallbackPersona != second.FallbackPersona {
		t.Fatalf("top-level persona fields drifted across round-trip")
	}
}

// TestPersonaConfigEmptySliceMarshalsOmitted documents that an explicitly empty
// (non-nil) slice is omitted by omitempty, matching the absent case — so a
// Python writer emitting [] and one omitting the key both yield the same wire
// shape, and neither produces "personas":null.
func TestPersonaConfigEmptySliceMarshalsOmitted(t *testing.T) {
	p := ProfileConfig{
		ProviderDomain: "company.okta.com",
		ClientID:       "abc",
		Personas:       []PersonaConfig{},
	}
	out, err := json.Marshal(p)
	if err != nil {
		t.Fatalf("marshal failed: %v", err)
	}
	if got := string(out); contains(got, "personas") {
		t.Fatalf("expected empty persona slice omitted, got: %s", got)
	}
}
