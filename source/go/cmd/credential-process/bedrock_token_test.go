package main

import (
	"encoding/base64"
	"net/url"
	"sort"
	"strings"
	"testing"
)

// TestGenerateBedrockToken_SignsEmptyPayload guards against regressing to the
// "UNSIGNED-PAYLOAD" sentinel. AWS's reference token generator
// (aws-bedrock-token-generator-python, via botocore's SigV4QueryAuth) signs
// the SHA-256 of an empty POST body -- "UNSIGNED-PAYLOAD" is only valid for
// services like S3 that permit an unknown/streamed body, and Bedrock rejects
// signatures built that way. This recomputes the signature independently
// using the correct empty-payload hash and confirms it matches the token.
func TestGenerateBedrockToken_SignsEmptyPayload(t *testing.T) {
	const secretAccessKey = "secretkeyexample"

	token, err := generateBedrockToken("AKIAEXAMPLE", secretAccessKey, "sessiontokenexample", "us-east-1")
	if err != nil {
		t.Fatalf("generateBedrockToken() error = %v", err)
	}
	if !strings.HasPrefix(token, authPrefix) {
		t.Fatalf("token missing prefix %q: %s", authPrefix, token)
	}

	decoded, err := base64.StdEncoding.DecodeString(strings.TrimPrefix(token, authPrefix))
	if err != nil {
		t.Fatalf("failed to decode token: %v", err)
	}
	presignedURL := strings.TrimSuffix(string(decoded), tokenVersion)

	parts := strings.SplitN(presignedURL, "?", 2)
	if len(parts) != 2 || parts[0] != bedrockHost+"/" {
		t.Fatalf("unexpected presigned URL host/path: %s", presignedURL)
	}

	query, err := url.ParseQuery(parts[1])
	if err != nil {
		t.Fatalf("failed to parse query: %v", err)
	}

	amzDate := query.Get("X-Amz-Date")
	credential := query.Get("X-Amz-Credential")
	signature := query.Get("X-Amz-Signature")
	if amzDate == "" || credential == "" || signature == "" {
		t.Fatalf("missing required SigV4 query params: %s", presignedURL)
	}

	credParts := strings.Split(credential, "/")
	if len(credParts) != 5 {
		t.Fatalf("unexpected credential scope: %s", credential)
	}
	dateStamp, region, service := credParts[1], credParts[2], credParts[3]

	// Recompute the canonical query string the same way generateBedrockToken
	// does, excluding the signature itself (it isn't part of what gets signed).
	query.Del("X-Amz-Signature")
	sortedKeys := make([]string, 0, len(query))
	for k := range query {
		sortedKeys = append(sortedKeys, k)
	}
	sort.Strings(sortedKeys)
	var canonicalQuery strings.Builder
	for i, k := range sortedKeys {
		if i > 0 {
			canonicalQuery.WriteByte('&')
		}
		canonicalQuery.WriteString(url.QueryEscape(k))
		canonicalQuery.WriteByte('=')
		canonicalQuery.WriteString(url.QueryEscape(query.Get(k)))
	}

	canonicalRequest := "POST\n/\n" + canonicalQuery.String() + "\nhost:" + bedrockHost + "\n\nhost\n" + emptySHA256Hash
	stringToSign := "AWS4-HMAC-SHA256\n" + amzDate + "\n" + dateStamp + "/" + region + "/" + service +
		"/aws4_request\n" + sha256Hex(canonicalRequest)
	signingKey := deriveSigningKey(secretAccessKey, dateStamp, region, service)
	expectedSignature := hmacSHA256Hex(signingKey, stringToSign)

	if signature != expectedSignature {
		t.Fatalf("signature mismatch: token was not signed with the empty-payload SHA-256 hash\ngot:  %s\nwant: %s",
			signature, expectedSignature)
	}
}
