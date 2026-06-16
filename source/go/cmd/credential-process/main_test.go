package main

import (
	"encoding/json"
	"os"
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

// TestTokenExpired pins the exit-code-4 condition shared by getTag and
// getPersonaModel. The expiry check was previously inline in those (impure,
// clock-reading) callers and untested; tokenExpired makes it a pure function so
// the "token expired -> code 4" contract has direct coverage. A future inversion
// of the comparison, a dropped check, or a boundary flip (< vs <=) breaks here.
func TestTokenExpired(t *testing.T) {
	const now int64 = 1_000_000

	tests := []struct {
		name   string
		claims jwt.Claims
		want   bool
	}{
		{"exp in the past -> expired", jwt.Claims{"exp": float64(now - 1)}, true},
		{"exp in the future -> not expired", jwt.Claims{"exp": float64(now + 1)}, false},
		{"exp exactly now -> not expired (strict <)", jwt.Claims{"exp": float64(now)}, false},
		{"missing exp -> not expired", jwt.Claims{"sub": "u"}, false},
		{"zero exp -> not expired (treated as absent)", jwt.Claims{"exp": float64(0)}, false},
		{"negative exp -> not expired (treated as absent)", jwt.Claims{"exp": float64(-5)}, false},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if got := tokenExpired(tt.claims, now); got != tt.want {
				t.Errorf("tokenExpired = %v, want %v", got, tt.want)
			}
		})
	}
}

// TestPersonaModelExportsFromConfigJSON is the "use" leg of the FR-5.1
// install->use->teardown integration test (see
// source/tests/integration/test_persona_model_lifecycle.py). It reads a
// config.json written by the REAL `ccwb package` code path through the REAL
// config.LoadProfileFromPath loader, then drives resolvePersonaModelExports —
// proving the Go helper consumes exactly what package.py serialized (the
// cross-language config contract), with no hand-built fixture in between.
//
// The Python orchestrator passes, via env:
//
//	CCWB_IT_CONFIG    -- path to the packaged config.json
//	CCWB_IT_PROFILE   -- profile name within it
//	CCWB_IT_GROUP     -- a group whose persona has resolved AIP ARNs
//	CCWB_IT_EXPECT    -- newline-joined `export K=V` lines the helper must emit
//
// When the env vars are absent the test skips (so a plain `go test ./...` is a
// no-op); the Python side is the sole driver.
func TestPersonaModelExportsFromConfigJSON(t *testing.T) {
	cfgPath := os.Getenv("CCWB_IT_CONFIG")
	profileName := os.Getenv("CCWB_IT_PROFILE")
	group := os.Getenv("CCWB_IT_GROUP")
	expect := os.Getenv("CCWB_IT_EXPECT")
	if cfgPath == "" || profileName == "" || group == "" {
		t.Skip("integration env (CCWB_IT_*) not set; driven by test_persona_model_lifecycle.py")
	}

	cfg, err := config.LoadProfileFromPath(cfgPath, profileName)
	if err != nil {
		t.Fatalf("LoadProfileFromPath(%q, %q): %v", cfgPath, profileName, err)
	}
	if len(cfg.Personas) == 0 {
		t.Fatalf("packaged config.json has no personas — package.py did not serialize them")
	}

	// Synthesize the claims the cached token would carry for a user in `group`.
	claims := jwt.Claims{"groups": []interface{}{group}}
	lines, code := resolvePersonaModelExports(cfg, claims, "")
	if code != 0 {
		t.Fatalf("expected exit 0 (exports emitted) for group %q, got %d", group, code)
	}
	got := strings.Join(lines, "\n")
	if got != expect {
		t.Errorf("persona model exports mismatch for group %q:\n got:\n%s\nwant:\n%s", group, got, expect)
	}

	// Belt-and-suspenders: the emitted ARNs must be exactly the ones serialized
	// into config.json for the matched persona (no drift in the round-trip).
	for _, p := range cfg.Personas {
		if p.Group == group {
			raw, _ := json.Marshal(p.InferenceProfileArns)
			if len(p.InferenceProfileArns) == 0 {
				t.Errorf("persona %q (group %q) has no inference_profile_arns in config.json: %s", p.Name, group, raw)
			}
			for _, arn := range p.InferenceProfileArns {
				if !strings.Contains(got, arn) {
					t.Errorf("ARN %q from config.json not present in emitted exports:\n%s", arn, got)
				}
			}
		}
	}
}
