package main

// ABOUTME: Generates Bedrock bearer tokens for Claude Desktop's inferenceCredentialHelper.
// ABOUTME: Converts AWS STS credentials (from OIDC/IDC federation) into a presigned
// ABOUTME: Bedrock bearer token that Claude Desktop can use directly.

import (
	"encoding/base64"
	"fmt"
	"net/url"
	"sort"
	"strings"
	"time"
)

const (
	bedrockHost    = "bedrock.amazonaws.com"
	bedrockService = "bedrock"
	authPrefix     = "bedrock-api-key-"
	tokenVersion   = "&Version=1"
	tokenExpirySec = 43200 // 12 hours

	// emptySHA256Hash is the SHA-256 digest of an empty payload. SigV4 presigned
	// requests have no body, but the canonical request must hash it explicitly —
	// "UNSIGNED-PAYLOAD" is only valid for services (like S3) that permit an
	// unknown/streamed body, and Bedrock rejects signatures built that way.
	emptySHA256Hash = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
)

// generateBedrockToken creates a presigned Bedrock bearer token from AWS credentials.
// Implements the same logic as aws-bedrock-token-generator-python:
//  1. Build a SigV4 presigned URL to bedrock.amazonaws.com with Action=CallWithBearerToken
//  2. Strip https://, append &Version=1
//  3. Base64 encode
//  4. Prefix with "bedrock-api-key-"
func generateBedrockToken(accessKeyID, secretAccessKey, sessionToken, region string) (string, error) {
	if accessKeyID == "" || secretAccessKey == "" || region == "" {
		return "", fmt.Errorf("credentials and region are required")
	}

	now := time.Now().UTC()

	// Build query parameters
	params := url.Values{}
	params.Set("Action", "CallWithBearerToken")
	params.Set("X-Amz-Algorithm", "AWS4-HMAC-SHA256")
	params.Set("X-Amz-Credential", fmt.Sprintf("%s/%s/%s/%s/aws4_request",
		accessKeyID, now.Format("20060102"), region, bedrockService))
	params.Set("X-Amz-Date", now.Format("20060102T150405Z"))
	params.Set("X-Amz-Expires", fmt.Sprintf("%d", tokenExpirySec))
	params.Set("X-Amz-SignedHeaders", "host")
	if sessionToken != "" {
		params.Set("X-Amz-Security-Token", sessionToken)
	}

	// Canonical query string (sorted, for signing — exclude signature itself)
	sortedKeys := make([]string, 0, len(params))
	for k := range params {
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
		canonicalQuery.WriteString(url.QueryEscape(params.Get(k)))
	}

	// Canonical request
	canonicalRequest := fmt.Sprintf("POST\n/\n%s\nhost:%s\n\nhost\n%s",
		canonicalQuery.String(), bedrockHost, emptySHA256Hash)

	// String to sign
	stringToSign := fmt.Sprintf("AWS4-HMAC-SHA256\n%s\n%s/%s/%s/aws4_request\n%s",
		now.Format("20060102T150405Z"),
		now.Format("20060102"),
		region,
		bedrockService,
		sha256Hex(canonicalRequest))

	// Calculate signature
	signingKey := deriveSigningKey(secretAccessKey, now.Format("20060102"), region, bedrockService)
	signature := hmacSHA256Hex(signingKey, stringToSign)

	// Build final presigned URL (without https:// prefix, as per Python reference)
	params.Set("X-Amz-Signature", signature)
	presignedURL := fmt.Sprintf("%s/?%s%s", bedrockHost, params.Encode(), tokenVersion)

	// Base64 encode and prefix
	encoded := base64.StdEncoding.EncodeToString([]byte(presignedURL))
	return authPrefix + encoded, nil
}
