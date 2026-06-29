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
	"sync"
	"syscall"
	"time"

	"github.com/aws/aws-sdk-go-v2/aws"
	awsconfig "github.com/aws/aws-sdk-go-v2/config"
	v4 "github.com/aws/aws-sdk-go-v2/aws/signer/v4"

	"ccwb-go/internal/config"
	"ccwb-go/internal/jwt"
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

	// cacheWarnInterval controls how often we log "no attribution headers"
	// while serving requests without user identity.
	cacheWarnInterval = 5 * time.Minute
)

// proxyConfig holds the configuration for the signing proxy.
// proxyConfig holds the configuration for the OTLP proxy.
type proxyConfig struct {
	port     int
	region   string
	profile  string
	upstream string // Custom upstream URL (overrides CloudWatch default; skips SigV4)
}

// startProxy runs the OTLP proxy. Blocks until SIGTERM/SIGINT.
// Returns 0 on clean shutdown, 1 on error.
//
// Two modes:
//   - SigV4 mode (default): Forwards to CloudWatch OTLP with SigV4 signing.
//     Used when otel-helper IS the collector (no separate otelcol).
//   - Passthrough mode (--proxy-upstream <url>): Forwards to an arbitrary URL
//     (e.g., central collector ALB or local otelcol) without SigV4.
//     Only injects identity headers from the JWT cache.
func startProxy(cfg proxyConfig) int {
	var upstream string
	var useSigV4 bool
	var region string

	if cfg.upstream != "" {
		// Passthrough mode: forward to custom upstream without SigV4
		upstream = cfg.upstream
		useSigV4 = false
		logger.Printf("Starting OTLP identity proxy on 127.0.0.1:%d \u2192 %s (passthrough, no SigV4)", cfg.port, upstream)
	} else {
		// SigV4 mode: forward to CloudWatch OTLP endpoint
		region = cfg.region
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
		upstream = fmt.Sprintf("https://monitoring.%s.amazonaws.com", region)
		useSigV4 = true
		logger.Printf("Starting OTLP signing proxy on 127.0.0.1:%d \u2192 %s", cfg.port, upstream)
	}

// Warm the attribution cache before serving. This ensures the first
	// CoWork telemetry requests already carry user.email headers instead of
	// waiting for the user to trigger credential-process via the CLI.
	if cfg.profile != "" {
		warmAttributionCache(cfg.profile)
	}

	var awsCfg aws.Config
	var signer *v4.Signer
	if useSigV4 {
		var err error
		awsCfg, err = awsconfig.LoadDefaultConfig(context.Background(),
			awsconfig.WithRegion(region),
		)
		if err != nil {
			logger.Printf("ERROR: failed to load AWS config: %v", err)
			return 1
		}
		signer = v4.NewSigner()
	}

	client := &http.Client{Timeout: upstreamTimeout}

	mux := http.NewServeMux()
	mux.HandleFunc("/health", func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
		fmt.Fprint(w, "ok")
	})

	if useSigV4 {
		mux.HandleFunc("/", makeProxyHandler(awsCfg, signer, client, upstream, region, cfg.profile))
	} else {
		mux.HandleFunc("/", makePassthroughHandler(client, upstream, cfg.profile))
	}

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

	if useSigV4 {
		logger.Printf("Proxy ready, forwarding to %s (service=%s, region=%s)", upstream, defaultService, region)
	} else {
		logger.Printf("Proxy ready, forwarding to %s (passthrough + identity injection)", upstream)
	}

	<-stop
	logger.Printf("Shutting down proxy...")
	ctx, cancel := context.WithTimeout(context.Background(), gracefulShutdownSec*time.Second)
	defer cancel()
	srv.Shutdown(ctx)
	return 0
}

// warmAttributionCache ensures the header cache is populated before the proxy
// starts serving. It reads the existing cache; if empty or stale, it runs
// credential-process to obtain a monitoring token, decodes the JWT, extracts
// user info, and writes the cache. This is best-effort — if it fails, the
// proxy still starts (requests will just lack attribution until the CLI runs).
func warmAttributionCache(profile string) {
	// Check if cache already has valid headers
	if cached, err := otel.ReadCachedHeaders(profile); err == nil && cached != nil {
		if _, hasEmail := cached["x-user-email"]; hasEmail {
			logger.Printf("Attribution cache warm: x-user-email present")
			return
		}
	}

	logger.Printf("Attribution cache empty — attempting to warm via credential-process...")

	// Try to get a monitoring token via credential-process
	token, err := getTokenViaCredentialProcess(profile)
	if err != nil || token == "" {
		logger.Printf("WARNING: Could not warm attribution cache: %v", err)
		logger.Printf("Dashboard metrics will lack user.email until the user authenticates via CLI.")
		return
	}

	// Decode JWT and extract user info
	claims, err := jwt.DecodePayload(token)
	if err != nil {
		logger.Printf("WARNING: Could not decode monitoring token: %v", err)
		return
	}

	// Use the same cost-attribution tag key as the credential-process binary
	costTagKey := "Project"
	if cfgData, cfgErr := config.LoadProfile(profile); cfgErr == nil && cfgData.CostAttributionTagKey != "" {
		costTagKey = cfgData.CostAttributionTagKey
	}

	userInfo := otel.ExtractUserInfoWithTagKey(claims, costTagKey)
	headers := otel.FormatHeaders(userInfo)

	// Write to cache so subsequent requests pick it up
	tokenExp := int64(claims.GetFloat("exp"))
	if tokenExp > 0 {
		if err := otel.WriteCachedHeaders(profile, headers, tokenExp); err != nil {
			logger.Printf("WARNING: Could not write attribution cache: %v", err)
		} else {
			logger.Printf("Attribution cache warmed successfully (user.email=%s)", headers["x-user-email"])
		}
	}
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
	// Rate-limited warning for missing attribution headers
	var (
		warnOnce sync.Once
		lastWarn time.Time
		warnMu   sync.Mutex
	)

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
		headersInjected := false
		if profile != "" {
			if cached, cacheErr := otel.ReadCachedHeaders(profile); cacheErr == nil && cached != nil {
				for k, v := range cached {
					// Skip the authorization header from cache — we use SigV4 instead
					if k != "authorization" {
						upstreamReq.Header.Set(k, v)
					}
				}
				headersInjected = true
			}
		}

		// Log a rate-limited warning if no attribution headers were injected.
		// First occurrence logs unconditionally; subsequent ones throttle.
		if !headersInjected && profile != "" {
			warnOnce.Do(func() {
				logger.Printf("WARNING: No attribution headers available — telemetry will lack user.email")
			})
			warnMu.Lock()
			if time.Since(lastWarn) > cacheWarnInterval {
				lastWarn = time.Now()
				debugPrint("Attribution cache miss for profile %q (user.email will be absent in metrics)", profile)
			}
			warnMu.Unlock()
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

// makePassthroughHandler returns an HTTP handler that:
// 1. Reads the request body verbatim (no parsing)
// 2. Injects attribution headers from the JWT cache
// 3. Forwards to the upstream endpoint WITHOUT SigV4 signing
//
// Used for central collector mode (forwarding to ALB) and sidecar mode
// (forwarding to local otelcol) where SigV4 is handled downstream.
func makePassthroughHandler(
	client *http.Client,
	upstream string,
	profile string,
) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
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

		// Copy content-type from original request
		if ct := r.Header.Get("Content-Type"); ct != "" {
			upstreamReq.Header.Set("Content-Type", ct)
		}

		// Copy through client-provided auth headers (e.g., X-Cowork-Token from MDM otlpHeaders)
		for _, key := range []string{"X-Cowork-Token", "Authorization"} {
			if v := r.Header.Get(key); v != "" {
				upstreamReq.Header.Set(key, v)
			}
		}

		// 3. Inject attribution headers from JWT cache (per-user identity)
		if profile != "" {
			if cached, cacheErr := otel.ReadCachedHeaders(profile); cacheErr == nil && cached != nil {
				for k, v := range cached {
					upstreamReq.Header.Set(k, v)
				}
			}
		}

		// 4. Forward to upstream (no SigV4 signing)
		resp, err := client.Do(upstreamReq)
		if err != nil {
			debugPrint("Passthrough upstream request failed: %v", err)
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
