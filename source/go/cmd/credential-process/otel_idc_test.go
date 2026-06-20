package main

import "testing"

func TestExtractEmailFromARN(t *testing.T) {
	tests := []struct {
		name     string
		arn      string
		expected string
	}{
		{
			name:     "standard assumed-role with email",
			arn:      "arn:aws:sts::123456789012:assumed-role/BedrockRole/alice@company.com",
			expected: "alice@company.com",
		},
		{
			name:     "assumed-role without email (session ID)",
			arn:      "arn:aws:sts::123456789012:assumed-role/BedrockRole/session-12345",
			expected: "",
		},
		{
			name:     "IAM user ARN (not assumed-role)",
			arn:      "arn:aws:iam::123456789012:user/admin",
			expected: "",
		},
		{
			name:     "empty ARN",
			arn:      "",
			expected: "",
		},
		{
			name:     "email with plus addressing",
			arn:      "arn:aws:sts::123456789012:assumed-role/Role/user+tag@company.com",
			expected: "user+tag@company.com",
		},
		{
			name:     "email with subdomain",
			arn:      "arn:aws:sts::123456789012:assumed-role/Role/alice@eng.company.com",
			expected: "alice@eng.company.com",
		},
		{
			name:     "role with slashes in path",
			arn:      "arn:aws:sts::123456789012:assumed-role/path/to/Role/bob@acme.org",
			expected: "bob@acme.org",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			result := extractEmailFromARN(tt.arn)
			if result != tt.expected {
				t.Errorf("extractEmailFromARN(%q) = %q, want %q", tt.arn, result, tt.expected)
			}
		})
	}
}

func TestExtractEmailFromARN_NonEmailIDC(t *testing.T) {
	tests := []struct {
		name     string
		arn      string
		expected string
	}{
		{
			name:     "non-email IDC username with AWSReservedSSO role",
			arn:      "arn:aws:sts::123456789012:assumed-role/AWSReservedSSO_BedrockDeveloper_abc123/akshaya.claude",
			expected: "akshaya.claude",
		},
		{
			name:     "non-email with generic role (NOT IDC) must NOT resolve",
			arn:      "arn:aws:sts::123456789012:assumed-role/LambdaExecutionRole/session123",
			expected: "",
		},
		{
			name:     "email IDC username still works",
			arn:      "arn:aws:sts::123456789012:assumed-role/AWSReservedSSO_BedrockDev_xyz/user@company.com",
			expected: "user@company.com",
		},
		{
			name:     "email with non-SSO role still works",
			arn:      "arn:aws:sts::123456789012:assumed-role/CustomRole/admin@corp.com",
			expected: "admin@corp.com",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			result := extractEmailFromARN(tt.arn)
			if result != tt.expected {
				t.Errorf("extractEmailFromARN(%q) = %q, want %q", tt.arn, result, tt.expected)
			}
		})
	}
}
