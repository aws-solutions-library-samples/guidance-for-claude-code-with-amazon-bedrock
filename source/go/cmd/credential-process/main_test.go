package main

import (
	"strings"
	"testing"

	"ccwb-go/internal/config"
	"ccwb-go/internal/jwt"
)

// TestSelectRoleARN exercises the persona-vs-FederatedRoleARN decision that
// getAWSCredentials makes on the direct-STS path. Factoring it into a pure
// helper lets us assert role selection without performing the real STS call.
func TestSelectRoleARN(t *testing.T) {
	const baseRole = "arn:aws:iam::111122223333:role/base"
	const engRole = "arn:aws:iam::111122223333:role/persona-eng"
	const salesRole = "arn:aws:iam::111122223333:role/persona-sales"

	personas := []config.PersonaConfig{
		{Name: "engineering", Group: "eng-team", RoleARN: engRole},
		{Name: "sales", Group: "sales-team", RoleARN: salesRole},
	}

	tests := []struct {
		name        string
		cfg         *config.ProfileConfig
		claims      jwt.Claims
		wantARN     string
		wantErr     bool
		errContains string
	}{
		{
			name:    "no personas -> FederatedRoleARN (backward compat)",
			cfg:     &config.ProfileConfig{FederatedRoleARN: baseRole},
			claims:  jwt.Claims{"groups": []interface{}{"eng-team"}},
			wantARN: baseRole,
		},
		{
			name:    "nil personas with groups present -> still FederatedRoleARN",
			cfg:     &config.ProfileConfig{FederatedRoleARN: baseRole, Personas: nil},
			claims:  jwt.Claims{"groups": []interface{}{"anything"}},
			wantARN: baseRole,
		},
		{
			name:    "persona match -> persona RoleARN",
			cfg:     &config.ProfileConfig{FederatedRoleARN: baseRole, Personas: personas},
			claims:  jwt.Claims{"groups": []interface{}{"eng-team"}},
			wantARN: engRole,
		},
		{
			name:    "declared-order precedence when in multiple groups",
			cfg:     &config.ProfileConfig{FederatedRoleARN: baseRole, Personas: personas},
			claims:  jwt.Claims{"groups": []interface{}{"sales-team", "eng-team"}},
			wantARN: engRole, // engineering declared first
		},
		{
			name:        "no match + no fallback -> hard-deny error",
			cfg:         &config.ProfileConfig{FederatedRoleARN: baseRole, Personas: personas},
			claims:      jwt.Claims{"groups": []interface{}{"contractors"}},
			wantErr:     true,
			errContains: "no persona matched",
		},
		{
			name: "no match + fallback -> fallback RoleARN",
			cfg: &config.ProfileConfig{
				FederatedRoleARN: baseRole,
				Personas:         personas,
				FallbackPersona:  "sales",
			},
			claims:  jwt.Claims{"groups": []interface{}{"contractors"}},
			wantARN: salesRole,
		},
		{
			name: "match beats configured fallback",
			cfg: &config.ProfileConfig{
				FederatedRoleARN: baseRole,
				Personas:         personas,
				FallbackPersona:  "engineering",
			},
			claims:  jwt.Claims{"groups": []interface{}{"sales-team"}},
			wantARN: salesRole,
		},
		{
			name: "custom groups claim name is honored",
			cfg: &config.ProfileConfig{
				FederatedRoleARN: baseRole,
				Personas:         personas,
				GroupsClaimName:  "cognito:groups",
			},
			claims:  jwt.Claims{"cognito:groups": []interface{}{"sales-team"}},
			wantARN: salesRole,
		},
		{
			name:    "scalar group claim resolves",
			cfg:     &config.ProfileConfig{FederatedRoleARN: baseRole, Personas: personas},
			claims:  jwt.Claims{"groups": "eng-team"},
			wantARN: engRole,
		},
		{
			name:        "missing groups claim + no fallback -> error",
			cfg:         &config.ProfileConfig{FederatedRoleARN: baseRole, Personas: personas},
			claims:      jwt.Claims{},
			wantErr:     true,
			errContains: "no persona matched",
		},
		{
			name: "matched persona with empty RoleARN -> clear error",
			cfg: &config.ProfileConfig{
				FederatedRoleARN: baseRole,
				Personas:         []config.PersonaConfig{{Name: "engineering", Group: "eng-team"}},
			},
			claims:      jwt.Claims{"groups": []interface{}{"eng-team"}},
			wantErr:     true,
			errContains: "no role ARN",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got, err := selectRoleARN(tt.cfg, tt.claims)
			if tt.wantErr {
				if err == nil {
					t.Fatalf("expected an error, got role ARN %q", got)
				}
				if tt.errContains != "" && !strings.Contains(err.Error(), tt.errContains) {
					t.Errorf("error %q does not contain %q", err.Error(), tt.errContains)
				}
				return
			}
			if err != nil {
				t.Fatalf("unexpected error: %v", err)
			}
			if got != tt.wantARN {
				t.Errorf("selectRoleARN = %q, want %q", got, tt.wantARN)
			}
		})
	}
}

// TestSelectRoleARNDefaultsGroupsClaim verifies the claim name defaults to
// "groups" when GroupsClaimName is empty.
func TestSelectRoleARNDefaultsGroupsClaim(t *testing.T) {
	cfg := &config.ProfileConfig{
		FederatedRoleARN: "arn:aws:iam::111122223333:role/base",
		Personas:         []config.PersonaConfig{{Name: "eng", Group: "eng-team", RoleARN: "arn:aws:iam::111122223333:role/eng"}},
		// GroupsClaimName intentionally empty -> should fall back to "groups".
	}
	got, err := selectRoleARN(cfg, jwt.Claims{"groups": []interface{}{"eng-team"}})
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if got != "arn:aws:iam::111122223333:role/eng" {
		t.Errorf("expected eng role via default 'groups' claim, got %q", got)
	}
}
