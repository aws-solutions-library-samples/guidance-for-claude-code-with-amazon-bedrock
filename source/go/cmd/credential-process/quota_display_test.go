package main

import (
	"testing"
)

func TestHumanizeNumber(t *testing.T) {
	tests := []struct {
		input    int64
		expected string
	}{
		{0, "0"},
		{100, "100"},
		{1000, "1,000"},
		{1234567, "1,234,567"},
		{225000000, "225,000,000"},
		{8250000, "8,250,000"},
		{180000000, "180,000,000"},
	}
	for _, tc := range tests {
		got := humanizeNumber(tc.input)
		if got != tc.expected {
			t.Errorf("humanizeNumber(%d) = %q, want %q", tc.input, got, tc.expected)
		}
	}
}

func TestFormatTokens(t *testing.T) {
	got := formatTokens(225000000)
	if got != "225,000,000" {
		t.Errorf("formatTokens(225000000) = %q, want \"225,000,000\"", got)
	}
}
