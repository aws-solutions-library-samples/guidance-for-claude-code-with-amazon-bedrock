package main

// ABOUTME: Regression tests for resolveRedirectPort — the browser callback port
// ABOUTME: must never be 0 (http://localhost:0 → ERR_UNSAFE_PORT).

import (
	"testing"

	"ccwb-go/internal/config"
)

// TestResolveRedirectPort guards the ERR_UNSAFE_PORT regression: once the
// --get-monitoring-token path resolves the provider type early and can fall
// through to browser auth, an unset redirect port would open http://localhost:0.
// resolveRedirectPort must always yield a usable port.
func TestResolveRedirectPort(t *testing.T) {
	tests := []struct {
		name    string
		env     string
		cfgPort int
		want    int
	}{
		{name: "default when unset", env: "", cfgPort: 0, want: 8400},
		{name: "profile port used", env: "", cfgPort: 9001, want: 9001},
		{name: "env overrides profile", env: "9200", cfgPort: 9001, want: 9200},
		{name: "invalid env falls back to profile", env: "not-a-port", cfgPort: 9001, want: 9001},
		{name: "zero env falls back to default", env: "0", cfgPort: 0, want: 8400},
	}
	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			t.Setenv("REDIRECT_PORT", tc.env)
			cfg := &config.ProfileConfig{RedirectPort: tc.cfgPort}
			if got := resolveRedirectPort(cfg); got != tc.want {
				t.Errorf("resolveRedirectPort = %d, want %d", got, tc.want)
			}
			if got := resolveRedirectPort(cfg); got == 0 {
				t.Error("resolveRedirectPort returned 0 — would open http://localhost:0 (ERR_UNSAFE_PORT)")
			}
		})
	}
}
