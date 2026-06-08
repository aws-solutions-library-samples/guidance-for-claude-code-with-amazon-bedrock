package config

import (
	"encoding/json"
	"testing"
)

// TestIsSsoEnabled covers the three states a config.json can present:
// SsoEnabled missing (legacy bundle -> default true), explicitly true,
// explicitly false. Regression test for the SSO-disabled passthrough fix.
func TestIsSsoEnabled(t *testing.T) {
	t.Run("nil_pointer_defaults_to_true", func(t *testing.T) {
		p := &ProfileConfig{}
		if !p.IsSsoEnabled() {
			t.Fatalf("expected legacy profile (no SsoEnabled field) to default to true")
		}
	})

	t.Run("nil_receiver_defaults_to_true", func(t *testing.T) {
		var p *ProfileConfig
		if !p.IsSsoEnabled() {
			t.Fatalf("expected nil receiver to default to true (defensive)")
		}
	})

	t.Run("explicit_true", func(t *testing.T) {
		v := true
		p := &ProfileConfig{SsoEnabled: &v}
		if !p.IsSsoEnabled() {
			t.Fatalf("expected sso_enabled=true to return true")
		}
	})

	t.Run("explicit_false", func(t *testing.T) {
		v := false
		p := &ProfileConfig{SsoEnabled: &v}
		if p.IsSsoEnabled() {
			t.Fatalf("expected sso_enabled=false to return false")
		}
	})
}

// TestSsoEnabledJSONRoundTrip verifies that the pointer-based SsoEnabled
// field round-trips correctly through JSON, including the absence case
// (legacy bundles must not produce a stray "sso_enabled":null key).
func TestSsoEnabledJSONRoundTrip(t *testing.T) {
	t.Run("absent_in_input_stays_nil", func(t *testing.T) {
		raw := `{"provider_domain":"company.okta.com","client_id":"abc"}`
		var p ProfileConfig
		if err := json.Unmarshal([]byte(raw), &p); err != nil {
			t.Fatalf("unmarshal failed: %v", err)
		}
		if p.SsoEnabled != nil {
			t.Fatalf("expected SsoEnabled nil for legacy input, got %v", *p.SsoEnabled)
		}
		if !p.IsSsoEnabled() {
			t.Fatalf("legacy profile must default to enabled")
		}
	})

	t.Run("explicit_false_decodes", func(t *testing.T) {
		raw := `{"provider_domain":"none","client_id":"none","sso_enabled":false}`
		var p ProfileConfig
		if err := json.Unmarshal([]byte(raw), &p); err != nil {
			t.Fatalf("unmarshal failed: %v", err)
		}
		if p.SsoEnabled == nil {
			t.Fatalf("expected SsoEnabled pointer to be non-nil")
		}
		if *p.SsoEnabled {
			t.Fatalf("expected SsoEnabled to decode to false")
		}
		if p.IsSsoEnabled() {
			t.Fatalf("IsSsoEnabled() must return false when explicitly disabled")
		}
	})

	t.Run("absent_serializes_omitted", func(t *testing.T) {
		// omitempty must keep the legacy on-disk shape clean (no "sso_enabled":null)
		p := ProfileConfig{ProviderDomain: "company.okta.com", ClientID: "abc"}
		out, err := json.Marshal(p)
		if err != nil {
			t.Fatalf("marshal failed: %v", err)
		}
		if got := string(out); contains(got, "sso_enabled") {
			t.Fatalf("expected sso_enabled omitted when nil, got: %s", got)
		}
	})
}

func contains(s, substr string) bool {
	return len(s) >= len(substr) && (s == substr || (len(substr) > 0 && indexOf(s, substr) >= 0))
}

func indexOf(s, sub string) int {
	for i := 0; i+len(sub) <= len(s); i++ {
		if s[i:i+len(sub)] == sub {
			return i
		}
	}
	return -1
}
