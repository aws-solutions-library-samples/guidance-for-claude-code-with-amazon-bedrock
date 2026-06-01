//go:build testhelper

// Package main — Azure certificate-mode client-assertion smoke binary.
//
// NOT SHIPPED. The `testhelper` build tag keeps it out of every normal build:
// `go build ./...`, `make all`, `ccwb package --go`, and `ccwb package --go`
// all ignore this file. Build explicitly with:
//
//	go build -tags testhelper -o azure-assertion-smoke ./cmd/azure-assertion-smoke
//
// Purpose: exercise buildClientAssertion directly on any OS. The shipping
// credential-process only reaches that code path after a successful IdP browser
// flow, so regression testing the crypto without a live Azure tenant requires
// this standalone entry point.
//
// Keep it in-tree because it catches Go-stdlib RSA-PSS or PEM-parsing
// regressions in <1 second, without any Azure dependency.
//
// Usage: azure-assertion-smoke <cert.pem> <key.pem> <clientID> <tokenURL>
package main

import (
	"encoding/base64"
	"encoding/json"
	"fmt"
	"os"
	"strings"

	"ccwb-go/internal/oidc"
)

func main() {
	if len(os.Args) != 5 {
		fmt.Fprintln(os.Stderr, "Usage: azure-assertion-smoke <cert.pem> <key.pem> <clientID> <tokenURL>")
		os.Exit(2)
	}
	conf := &oidc.ConfidentialAuth{CertificatePath: os.Args[1], PrivateKeyPath: os.Args[2]}
	form := map[string]string{}
	if err := oidc.ApplyConfidentialForTest(conf, form, os.Args[4], os.Args[3]); err != nil {
		fmt.Fprintf(os.Stderr, "apply failed: %v\n", err)
		os.Exit(1)
	}
	assertion, ok := form["client_assertion"]
	if !ok {
		fmt.Fprintln(os.Stderr, "client_assertion missing from form")
		os.Exit(1)
	}
	parts := strings.Split(assertion, ".")
	if len(parts) != 3 {
		fmt.Fprintf(os.Stderr, "JWT has %d parts, want 3\n", len(parts))
		os.Exit(1)
	}
	headerBytes, _ := base64.RawURLEncoding.DecodeString(parts[0])
	payloadBytes, _ := base64.RawURLEncoding.DecodeString(parts[1])
	var header, payload map[string]interface{}
	_ = json.Unmarshal(headerBytes, &header)
	_ = json.Unmarshal(payloadBytes, &payload)
	pretty, _ := json.MarshalIndent(map[string]interface{}{
		"header":          header,
		"payload":         payload,
		"signature_bytes": len(parts[2]),
	}, "", "  ")
	fmt.Println(string(pretty))
	fmt.Println("assertion length:", len(assertion))
	fmt.Println("OK")
}
