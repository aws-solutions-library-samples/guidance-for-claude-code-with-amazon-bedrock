package oidc

import (
	"context"
	"fmt"
	"net"
	"net/http"
	"net/url"
	"time"
)

// CallbackResult holds the result from the OAuth2 callback.
type CallbackResult struct {
	Code  string
	Error string
}

// StartCallbackServer starts an HTTP server on 127.0.0.1:port that handles
// a single OAuth2 callback request. It returns a channel that receives the result.
func StartCallbackServer(port int, expectedState string) (chan CallbackResult, *http.Server, error) {
	resultCh := make(chan CallbackResult, 1)

	mux := http.NewServeMux()
	mux.HandleFunc("/callback", func(w http.ResponseWriter, r *http.Request) {
		q := r.URL.Query()

		if errMsg := q.Get("error"); errMsg != "" {
			desc := q.Get("error_description")
			if desc == "" {
				desc = errMsg
			}
			sendHTML(w, 400, "Authentication failed")
			resultCh <- CallbackResult{Error: desc}
			return
		}

		state := q.Get("state")
		code := q.Get("code")

		if state != expectedState || code == "" {
			sendHTML(w, 400, "Invalid response")
			resultCh <- CallbackResult{Error: "Invalid state or missing code"}
			return
		}

		sendHTML(w, 200, "Authentication successful! You can close this window.")
		resultCh <- CallbackResult{Code: code}
	})

	srv := &http.Server{
		Addr:    fmt.Sprintf("127.0.0.1:%d", port),
		Handler: mux,
	}

	ln, err := net.Listen("tcp", srv.Addr)
	if err != nil {
		return nil, nil, fmt.Errorf("cannot listen on %s: %w", srv.Addr, err)
	}

	go func() {
		_ = srv.Serve(ln)
	}()

	return resultCh, srv, nil
}

// WaitForCallback waits for the callback result with a timeout.
func WaitForCallback(resultCh chan CallbackResult, srv *http.Server, timeout time.Duration) (*CallbackResult, error) {
	select {
	case result := <-resultCh:
		// Give the browser a moment to receive the response
		time.Sleep(100 * time.Millisecond)
		ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
		defer cancel()
		_ = srv.Shutdown(ctx)
		return &result, nil
	case <-time.After(timeout):
		ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
		defer cancel()
		_ = srv.Shutdown(ctx)
		return nil, fmt.Errorf("authentication timeout - no authorization code received within %v", timeout)
	}
}

func sendHTML(w http.ResponseWriter, code int, message string) {
	w.Header().Set("Content-Type", "text/html")
	w.WriteHeader(code)
	html := fmt.Sprintf(`<html>
<head><title>Authentication</title></head>
<body style="font-family: sans-serif; text-align: center; padding: 50px;">
    <h1>%s</h1>
    <p>Return to your terminal to continue.</p>
</body>
</html>`, url.QueryEscape(message))
	// Use the un-escaped message in HTML - it's our own string, not user input
	html = fmt.Sprintf(`<html>
<head><title>Authentication</title></head>
<body style="font-family: sans-serif; text-align: center; padding: 50px;">
    <h1>%s</h1>
    <p>Return to your terminal to continue.</p>
</body>
</html>`, message)
	w.Write([]byte(html))
}
