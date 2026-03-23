package otel

import "testing"

func TestFormatHeaders_AllFields(t *testing.T) {
	info := UserInfo{
		Email:          "user@example.com",
		UserID:         "abc12345-1234-1234-1234-123456789012",
		Username:       "jdoe",
		OrganizationID: "okta",
		Department:     "eng",
		Team:           "platform",
		CostCenter:     "CC-100",
		Manager:        "boss@example.com",
		Location:       "NYC",
		Role:           "developer",
	}

	headers := FormatHeaders(info)

	expected := map[string]string{
		"x-user-email":  "user@example.com",
		"x-user-id":     "abc12345-1234-1234-1234-123456789012",
		"x-user-name":   "jdoe",
		"x-organization": "okta",
		"x-department":   "eng",
		"x-team-id":      "platform",
		"x-cost-center":  "CC-100",
		"x-manager":      "boss@example.com",
		"x-location":     "NYC",
		"x-role":         "developer",
	}

	for k, v := range expected {
		if headers[k] != v {
			t.Errorf("header %s = %q, want %q", k, headers[k], v)
		}
	}
}

func TestFormatHeaders_EmptyFieldsExcluded(t *testing.T) {
	info := UserInfo{
		Email: "user@example.com",
		// All other fields empty
	}

	headers := FormatHeaders(info)

	if _, ok := headers["x-user-email"]; !ok {
		t.Error("expected x-user-email to be present")
	}
	if _, ok := headers["x-user-id"]; ok {
		t.Error("expected x-user-id to be absent for empty UserID")
	}
}
