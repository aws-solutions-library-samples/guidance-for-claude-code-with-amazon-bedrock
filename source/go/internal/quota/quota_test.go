package quota

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestCheck_Allowed(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		json.NewEncoder(w).Encode(Result{
			Allowed: true,
			Reason:  "within_limits",
			Usage: map[string]interface{}{
				"monthly_tokens":  float64(100000000),
				"monthly_limit":   float64(225000000),
				"monthly_percent": float64(44.4),
				"daily_tokens":    float64(5000000),
				"daily_limit":     float64(8250000),
				"daily_percent":   float64(60.6),
			},
		})
	}))
	defer srv.Close()

	result := Check(srv.URL, "test-token", 5, "open")
	if !result.Allowed {
		t.Errorf("expected allowed=true, got false")
	}
	if result.Usage == nil {
		t.Fatal("expected usage data, got nil")
	}
	if result.Usage["monthly_percent"].(float64) != 44.4 {
		t.Errorf("expected monthly_percent=44.4, got %v", result.Usage["monthly_percent"])
	}
}

func TestCheck_Blocked(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		json.NewEncoder(w).Encode(Result{
			Allowed: false,
			Reason:  "monthly_exceeded",
			Message: "Monthly quota exceeded: 225,000,000 / 225,000,000 tokens (100.0%).",
			Usage: map[string]interface{}{
				"monthly_tokens":  float64(225000000),
				"monthly_limit":   float64(225000000),
				"monthly_percent": float64(100.0),
			},
			Policy: map[string]interface{}{
				"type":       "default",
				"identifier": "default",
			},
		})
	}))
	defer srv.Close()

	result := Check(srv.URL, "test-token", 5, "open")
	if result.Allowed {
		t.Errorf("expected allowed=false, got true")
	}
	if result.Message == "" {
		t.Errorf("expected message, got empty")
	}
}

func TestCheck_Warning_Threshold(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		json.NewEncoder(w).Encode(Result{
			Allowed: true,
			Reason:  "within_limits",
			Usage: map[string]interface{}{
				"monthly_tokens":  float64(180000000),
				"monthly_limit":   float64(225000000),
				"monthly_percent": float64(80.0),
				"daily_tokens":    float64(6600000),
				"daily_limit":     float64(8250000),
				"daily_percent":   float64(80.0),
			},
		})
	}))
	defer srv.Close()

	result := Check(srv.URL, "test-token", 5, "open")
	if !result.Allowed {
		t.Errorf("expected allowed=true (warning, not blocked)")
	}
	// Verify usage data is present for warning display
	monthlyPercent, _ := result.Usage["monthly_percent"].(float64)
	if monthlyPercent < 80 {
		t.Errorf("expected monthly_percent >= 80 for warning, got %v", monthlyPercent)
	}
}

func TestCheck_FailMode_Open(t *testing.T) {
	// Server that returns 500
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(500)
	}))
	defer srv.Close()

	result := Check(srv.URL, "test-token", 5, "open")
	if !result.Allowed {
		t.Errorf("fail-open should allow access on API error")
	}
}

func TestCheck_FailMode_Closed(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(500)
	}))
	defer srv.Close()

	result := Check(srv.URL, "test-token", 5, "closed")
	if result.Allowed {
		t.Errorf("fail-closed should deny access on API error")
	}
}
