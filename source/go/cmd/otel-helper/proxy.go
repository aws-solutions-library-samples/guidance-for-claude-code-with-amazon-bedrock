// ABOUTME: SigV4 signing reverse proxy for CoWork sidecar telemetry.
// ABOUTME: Accepts OTLP logs on localhost, adds SigV4 auth + attribution headers,
// ABOUTME: and forwards to the CloudWatch OTLP endpoint. Enables CoWork telemetry
// ABOUTME: in sidecar mode without requiring a central collector.

package main

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"io"
	"net"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/aws/aws-sdk-go-v2/aws"
	awsconfig "github.com/aws/aws-sdk-go-v2/config"
	v4 "github.com/aws/aws-sdk-go-v2/aws/signer/v4"

	"ccwb-go/internal/otel"
)

const (
	defaultProxyPort    = 4318
	defaultService      = "monitoring"
	proxyReadTimeout    = 30 * time.Second
	proxyWriteTimeout   = 30 * time.Second
	proxyIdleTimeout    = 60 * time.Second
	upstreamTimeout     = 30 * time.Second
	gracefulShutdownSec = 5
)

// proxyConfig holds the configuration for the signing proxy.
type proxyConfig struct {
	port    int
	region  string
	profile string
}

// startProxy runs the SigV4 signing proxy. Blocks until SIGTERM/SIGINT.
// Returns 0 on clean shutdown, 1 on error.
func startProxy(cfg proxyConfig) int {
	region := cfg.region
	if region == "" {
		region = os.Getenv("AWS_REGION")
	}
	if region == "" {
		region = os.Getenv("AWS_DEFAULT_REGION")
	}
	if region == "" {
		logger.Printf("ERROR: --proxy-region or AWS_REGION must be set")
		return 1
	}

	upstream := fmt.Sprintf("https://monitoring.%s.amazonaws.com", region)
	logger.Printf("Starting OTLP signing proxy on 127.0.0.1:%d → %s", cfg.port, upstream)

	// Load AWS credentials via the standard chain (respects AWS_PROFILE, credential_process, etc.)
	awsCfg, err := awsconfig.LoadDefaultConfig(context.Background(),
		awsconfig.WithRegion(region),
	)
	if err != nil {
		logger.Printf("ERROR: failed to load AWS config: %v", err)
		return 1
	}

	signer := v4.NewSigner()
	client := &http.Client{Timeout: upstreamTimeout}

	mux := http.NewServeMux()
	mux.HandleFunc("/health", func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
		fmt.Fprint(w, "ok")
	})
	mux.HandleFunc("/", makeProxyHandler(awsCfg, signer, client, upstream, region, cfg.profile))

	srv := &http.Server{
		Addr:         fmt.Sprintf("127.0.0.1:%d", cfg.port),
		Handler:      mux,
		ReadTimeout:  proxyReadTimeout,
		WriteTimeout: proxyWriteTimeout,
		IdleTimeout:  proxyIdleTimeout,
	}

	// Listen explicitly on IPv4 loopback only (security: no external access)
	ln, err := net.Listen("tcp4", srv.Addr)
	if err != nil {
		logger.Printf("ERROR: failed to bind %s: %v", srv.Addr, err)
		return 1
	}

	// Graceful shutdown on SIGTERM/SIGINT
	stop := make(chan os.Signal, 1)
	signal.Notify(stop, syscall.SIGTERM, syscall.SIGINT)

	go func() {
		if err := srv.Serve(ln); err != nil && err != http.ErrServerClosed {
			logger.Printf("ERROR: proxy server: %v", err)
		}
	}()

	logger.Printf("Proxy ready, forwarding to %s (service=%s, region=%s)", upstream, defaultService, region)

	<-stop
	logger.Printf("Shutting down proxy...")
	ctx, cancel := context.WithTimeout(context.Background(), gracefulShutdownSec*time.Second)
	defer cancel()
	srv.Shutdown(ctx)
	return 0
}

// makeProxyHandler returns an HTTP handler that:
// 1. Reads the request body verbatim (no parsing)
// 2. Injects attribution headers from the JWT cache
// 3. SigV4-signs the request for CloudWatch OTLP
// 4. Forwards to the upstream endpoint
func makeProxyHandler(
	awsCfg aws.Config,
	signer *v4.Signer,
	client *http.Client,
	upstream string,
	region string,
	profile string,
) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		// Only accept POST (OTLP export is always POST)
		if r.Method != http.MethodPost {
			http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
			return
		}

		// 1. Read body verbatim
		body, err := io.ReadAll(r.Body)
		if err != nil {
			http.Error(w, "failed to read request body", http.StatusBadRequest)
			return
		}
		defer r.Body.Close()

		// 2. Build upstream request
		targetURL := upstream + r.URL.Path
		if r.URL.RawQuery != "" {
			targetURL += "?" + r.URL.RawQuery
		}
		upstreamReq, err := http.NewRequestWithContext(r.Context(), http.MethodPost, targetURL, bytes.NewReader(body))
		if err != nil {
			http.Error(w, "failed to create upstream request", http.StatusInternalServerError)
			return
		}

		// Copy content-type from original request (protobuf or json)
		if ct := r.Header.Get("Content-Type"); ct != "" {
			upstreamReq.Header.Set("Content-Type", ct)
		}

		// 3. Inject attribution headers from JWT cache (best-effort, non-blocking)
		if profile != "" {
			if cached, cacheErr := otel.ReadCachedHeaders(profile); cacheErr == nil && cached != nil {
				for k, v := range cached {
					// Skip the authorization header from cache — we use SigV4 instead
					if k != "authorization" {
						upstreamReq.Header.Set(k, v)
					}
				}
			}
		}

		// 4. SigV4-sign the request
		creds, err := awsCfg.Credentials.Retrieve(r.Context())
		if err != nil {
			debugPrint("Failed to retrieve AWS credentials: %v", err)
			http.Error(w, "failed to retrieve AWS credentials", http.StatusInternalServerError)
			return
		}

		payloadHash := sha256Hex(body)
		err = signer.SignHTTP(r.Context(), creds, upstreamReq, payloadHash, defaultService, region, time.Now())
		if err != nil {
			debugPrint("Failed to SigV4-sign request: %v", err)
			http.Error(w, "failed to sign request", http.StatusInternalServerError)
			return
		}

		// 5. Forward to upstream
		resp, err := client.Do(upstreamReq)
		if err != nil {
			debugPrint("Upstream request failed: %v", err)
			http.Error(w, "upstream request failed", http.StatusBadGateway)
			return
		}
		defer resp.Body.Close()

		// Copy response back to client
		for k, vv := range resp.Header {
			for _, v := range vv {
				w.Header().Add(k, v)
			}
		}
		w.WriteHeader(resp.StatusCode)
		io.Copy(w, resp.Body)
	}
}

// sha256Hex returns the hex-encoded SHA-256 hash of the data.
func sha256Hex(data []byte) string {
	h := sha256.Sum256(data)
	return hex.EncodeToString(h[:])
}
