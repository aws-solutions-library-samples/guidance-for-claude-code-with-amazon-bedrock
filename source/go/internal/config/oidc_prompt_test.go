package config

import (
	"encoding/json"
	"testing"
)

func TestOIDCPromptDeserialization(t *testing.T) {
	t.Run("absent_field_yields_nil", func(t *testing.T) {
		data := []byte(`{"provider_domain":"example.com","client_id":"abc"}`)
		var cfg ProfileConfig
		if err := json.Unmarshal(data, &cfg); err != nil {
			t.Fatal(err)
		}
		if cfg.OIDCPrompt != nil {
			t.Fatalf("expected nil, got %q", *cfg.OIDCPrompt)
		}
	})

	t.Run("explicit_empty_string", func(t *testing.T) {
		data := []byte(`{"provider_domain":"example.com","client_id":"abc","oidc_prompt":""}`)
		var cfg ProfileConfig
		if err := json.Unmarshal(data, &cfg); err != nil {
			t.Fatal(err)
		}
		if cfg.OIDCPrompt == nil {
			t.Fatal("expected non-nil pointer for explicit empty string")
		}
		if *cfg.OIDCPrompt != "" {
			t.Fatalf("expected empty string, got %q", *cfg.OIDCPrompt)
		}
	})

	t.Run("explicit_value", func(t *testing.T) {
		data := []byte(`{"provider_domain":"example.com","client_id":"abc","oidc_prompt":"login"}`)
		var cfg ProfileConfig
		if err := json.Unmarshal(data, &cfg); err != nil {
			t.Fatal(err)
		}
		if cfg.OIDCPrompt == nil {
			t.Fatal("expected non-nil pointer")
		}
		if *cfg.OIDCPrompt != "login" {
			t.Fatalf("expected \"login\", got %q", *cfg.OIDCPrompt)
		}
	})

	t.Run("full_profile_load", func(t *testing.T) {
		prompt := "none"
		data := []byte(`{"profiles":{"test":{"provider_domain":"login.microsoftonline.com/tenant/v2.0","client_id":"abc","provider_type":"azure","oidc_prompt":"none"}}}`)
		cfg, err := parseProfile(data, "test")
		if err != nil {
			t.Fatal(err)
		}
		if cfg.OIDCPrompt == nil || *cfg.OIDCPrompt != prompt {
			t.Fatalf("expected %q from profile load, got %v", prompt, cfg.OIDCPrompt)
		}
	})
}
