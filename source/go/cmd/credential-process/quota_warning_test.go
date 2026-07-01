package main

import (
	"bytes"
	"os"
	"strings"
	"testing"

	"ccwb-go/internal/quota"
)

// TestPrintQuotaWarning_AtThreshold verifies warning is emitted at 80%+ usage.
func TestPrintQuotaWarning_AtThreshold(t *testing.T) {
	tests := []struct {
		name           string
		monthlyPercent float64
		dailyPercent   float64
		expectWarning  bool
	}{
		{"below_threshold", 50, 50, false},
		{"monthly_at_80", 80, 50, true},
		{"daily_at_80", 50, 80, true},
		{"both_over", 95, 120, true},
		{"daily_over_100", 30, 451.9, true},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			qr := &quota.Result{
				Allowed: true,
				Reason:  "within_limits",
				Usage: map[string]interface{}{
					"monthly_percent": tc.monthlyPercent,
					"daily_percent":   tc.dailyPercent,
					"monthly_tokens":  float64(9000000),
					"monthly_limit":   float64(40000000),
					"daily_tokens":    float64(9000000),
					"daily_limit":     float64(2000000),
				},
			}

			// Capture stderr
			oldStderr := os.Stderr
			r, w, _ := os.Pipe()
			os.Stderr = w

			printQuotaWarning(qr)

			w.Close()
			var buf bytes.Buffer
			buf.ReadFrom(r)
			os.Stderr = oldStderr

			output := buf.String()
			hasWarning := strings.Contains(output, "QUOTA WARNING")

			if tc.expectWarning && !hasWarning {
				t.Errorf("expected QUOTA WARNING in stderr, got: %q", output)
			}
			if !tc.expectWarning && hasWarning {
				t.Errorf("did not expect QUOTA WARNING, but got: %q", output)
			}
		})
	}
}

// TestPrintQuotaWarning_StdoutSacred verifies that printQuotaWarning NEVER writes to stdout.
// stdout must remain exclusively for credential JSON (credential-flow.md rule).
func TestPrintQuotaWarning_StdoutSacred(t *testing.T) {
	qr := &quota.Result{
		Allowed: true,
		Reason:  "within_limits",
		Usage: map[string]interface{}{
			"monthly_percent": float64(95),
			"daily_percent":   float64(451.9),
			"monthly_tokens":  float64(38000000),
			"monthly_limit":   float64(40000000),
			"daily_tokens":    float64(9000000),
			"daily_limit":     float64(2000000),
		},
	}

	// Capture stdout
	oldStdout := os.Stdout
	rOut, wOut, _ := os.Pipe()
	os.Stdout = wOut

	// Capture stderr (to suppress output)
	oldStderr := os.Stderr
	_, wErr, _ := os.Pipe()
	os.Stderr = wErr

	printQuotaWarning(qr)

	wOut.Close()
	wErr.Close()
	var stdoutBuf bytes.Buffer
	stdoutBuf.ReadFrom(rOut)
	os.Stdout = oldStdout
	os.Stderr = oldStderr

	if stdoutBuf.Len() > 0 {
		t.Errorf("printQuotaWarning wrote to stdout (violates credential-flow rule): %q", stdoutBuf.String())
	}
}

// TestPrintQuotaWarning_NilUsage verifies no panic on nil usage.
func TestPrintQuotaWarning_NilUsage(t *testing.T) {
	qr := &quota.Result{Allowed: true, Reason: "within_limits", Usage: nil}
	// Should not panic
	printQuotaWarning(qr)
}

// TestPrintQuotaWarning_EmptyUsage verifies no warning on empty usage map.
func TestPrintQuotaWarning_EmptyUsage(t *testing.T) {
	qr := &quota.Result{Allowed: true, Reason: "within_limits", Usage: map[string]interface{}{}}

	oldStderr := os.Stderr
	r, w, _ := os.Pipe()
	os.Stderr = w

	printQuotaWarning(qr)

	w.Close()
	var buf bytes.Buffer
	buf.ReadFrom(r)
	os.Stderr = oldStderr

	if strings.Contains(buf.String(), "QUOTA WARNING") {
		t.Error("empty usage should not produce warning")
	}
}
