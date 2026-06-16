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
			name:        "no match + no fallback -> hard-deny error (says none configured)",
			cfg:         &config.ProfileConfig{FederatedRoleARN: baseRole, Personas: personas},
			claims:      jwt.Claims{"groups": []interface{}{"contractors"}},
			wantErr:     true,
			errContains: "no fallback persona is configured",
		},
		{
			name: "no match + fallback names unknown persona -> distinct hard-deny error",
			cfg: &config.ProfileConfig{
				FederatedRoleARN: baseRole,
				Personas:         personas,
				FallbackPersona:  "does-not-exist",
			},
			claims:      jwt.Claims{"groups": []interface{}{"contractors"}},
			wantErr:     true,
			errContains: "does not name any declared persona",
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

// TestResolvePersonaModelExports exercises the pure core of --get-persona-model
// (FR-5.1): persona resolution from the groups claim -> ANTHROPIC_*_MODEL export
// lines pointing at the persona's per-tier inference-profile ARNs.
func TestResolvePersonaModelExports(t *testing.T) {
	const haikuARN = "arn:aws:bedrock:us-east-1:111122223333:application-inference-profile/sales-haiku"
	const sonnetARN = "arn:aws:bedrock:us-east-1:111122223333:application-inference-profile/eng-sonnet"
	const opusARN = "arn:aws:bedrock:us-east-1:111122223333:application-inference-profile/eng-opus"

	eng := config.PersonaConfig{
		Name: "engineering", Group: "eng-team",
		InferenceProfileArns: map[string]string{"sonnet": sonnetARN, "opus": opusARN},
	}
	sales := config.PersonaConfig{
		Name: "sales", Group: "sales-team",
		InferenceProfileArns: map[string]string{"haiku": haikuARN},
	}
	noArns := config.PersonaConfig{Name: "interns", Group: "intern-team"}
	personas := []config.PersonaConfig{eng, sales, noArns}

	tests := []struct {
		name      string
		cfg       *config.ProfileConfig
		claims    jwt.Claims
		tier      string
		wantCode  int
		wantLines []string
	}{
		{
			name:     "no personas configured -> code 2",
			cfg:      &config.ProfileConfig{},
			claims:   jwt.Claims{"groups": []interface{}{"eng-team"}},
			wantCode: 2,
		},
		{
			name:     "no group match, no fallback -> code 2",
			cfg:      &config.ProfileConfig{Personas: personas},
			claims:   jwt.Claims{"groups": []interface{}{"nobody"}},
			wantCode: 2,
		},
		{
			name:     "matched persona has no ARNs -> code 2",
			cfg:      &config.ProfileConfig{Personas: personas},
			claims:   jwt.Claims{"groups": []interface{}{"intern-team"}},
			wantCode: 2,
		},
		{
			name:     "sales (haiku only) -> haiku + primary ANTHROPIC_MODEL=haiku",
			cfg:      &config.ProfileConfig{Personas: personas},
			claims:   jwt.Claims{"groups": []interface{}{"sales-team"}},
			wantCode: 0,
			wantLines: []string{
				"export ANTHROPIC_DEFAULT_HAIKU_MODEL=" + haikuARN,
				"export ANTHROPIC_MODEL=" + haikuARN,
			},
		},
		{
			name:     "engineering (sonnet+opus) -> both tiers + primary=opus (most capable)",
			cfg:      &config.ProfileConfig{Personas: personas},
			claims:   jwt.Claims{"groups": []interface{}{"eng-team"}},
			wantCode: 0,
			wantLines: []string{
				"export ANTHROPIC_DEFAULT_SONNET_MODEL=" + sonnetARN,
				"export ANTHROPIC_DEFAULT_OPUS_MODEL=" + opusARN,
				"export ANTHROPIC_MODEL=" + opusARN,
			},
		},
		{
			name:      "single-tier request (sonnet) -> only that env var, no ANTHROPIC_MODEL",
			cfg:       &config.ProfileConfig{Personas: personas},
			claims:    jwt.Claims{"groups": []interface{}{"eng-team"}},
			tier:      "sonnet",
			wantCode:  0,
			wantLines: []string{"export ANTHROPIC_DEFAULT_SONNET_MODEL=" + sonnetARN},
		},
		{
			name:     "single-tier request for a tier the persona lacks -> code 2",
			cfg:      &config.ProfileConfig{Personas: personas},
			claims:   jwt.Claims{"groups": []interface{}{"sales-team"}},
			tier:     "opus",
			wantCode: 2,
		},
		{
			name: "fallback persona used when no group matches",
			cfg: &config.ProfileConfig{
				Personas:        personas,
				FallbackPersona: "sales",
			},
			claims:   jwt.Claims{"groups": []interface{}{"nobody"}},
			wantCode: 0,
			wantLines: []string{
				"export ANTHROPIC_DEFAULT_HAIKU_MODEL=" + haikuARN,
				"export ANTHROPIC_MODEL=" + haikuARN,
			},
		},
		{
			name:     "default groups claim fallback (GroupsClaimName empty)",
			cfg:      &config.ProfileConfig{Personas: personas},
			claims:   jwt.Claims{"groups": []interface{}{"sales-team"}},
			wantCode: 0,
			wantLines: []string{
				"export ANTHROPIC_DEFAULT_HAIKU_MODEL=" + haikuARN,
				"export ANTHROPIC_MODEL=" + haikuARN,
			},
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			lines, code := resolvePersonaModelExports(tt.cfg, tt.claims, tt.tier)
			if code != tt.wantCode {
				t.Errorf("code = %d, want %d (lines=%v)", code, tt.wantCode, lines)
			}
			if tt.wantLines == nil {
				if len(lines) != 0 {
					t.Errorf("expected no lines, got %v", lines)
				}
				return
			}
			if strings.Join(lines, "\n") != strings.Join(tt.wantLines, "\n") {
				t.Errorf("lines mismatch:\n got: %v\nwant: %v", lines, tt.wantLines)
			}
		})
	}
}
