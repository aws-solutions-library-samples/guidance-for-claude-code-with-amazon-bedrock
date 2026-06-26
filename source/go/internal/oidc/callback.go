package oidc

import (
	"context"
	"fmt"
	"html"
	"net"
	"net/http"
	"time"
)

// CallbackResult holds the result from the OAuth2 callback.
type CallbackResult struct {
	Code  string
	Error string
}

// StartCallbackServer starts an HTTP server on 127.0.0.1:port that handles
// a single OAuth2 callback request. It returns a channel that receives the result.
// authURL is the IdP authorization URL — the landing page links to it.
func StartCallbackServer(port int, expectedState string, authURL string) (chan CallbackResult, *http.Server, error) {
	resultCh := make(chan CallbackResult, 1)

	mux := http.NewServeMux()

	// Landing page — explains what's happening and provides a login button.
	// This page is what the browser opens first (instead of jumping directly
	// to the IdP), giving CoWork users context about why a browser appeared.
	mux.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/" {
			http.NotFound(w, r)
			return
		}
		w.Header().Set("Content-Type", "text/html")
		w.WriteHeader(200)
		page := fmt.Sprintf(`<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Claude Desktop — Authentication Required</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background: #f8f9fa;
    display: flex;
    align-items: center;
    justify-content: center;
    min-height: 100vh;
    padding: 20px;
  }
  .card {
    background: white;
    border-radius: 12px;
    box-shadow: 0 4px 24px rgba(0,0,0,0.08);
    padding: 48px;
    max-width: 440px;
    width: 100%%;
    text-align: center;
  }
  .icon { font-size: 48px; margin-bottom: 16px; }
  h1 { font-size: 20px; color: #1a1a1a; margin-bottom: 12px; }
  p { font-size: 14px; color: #666; line-height: 1.6; margin-bottom: 24px; }
  .btn {
    display: inline-block;
    background: #d97706;
    color: white;
    padding: 12px 32px;
    border-radius: 8px;
    text-decoration: none;
    font-size: 15px;
    font-weight: 500;
    transition: background 0.2s;
  }
  .btn:hover { background: #b45309; }
  .note { font-size: 12px; color: #999; margin-top: 20px; }
</style>
</head>
<body>
<div class="card">
  <div class="icon">&#x1f510;</div>
  <h1>Authentication Required</h1>
  <p>Your Claude Desktop session has expired.<br>Please log in to continue.</p>
  <a class="btn" href="%s">Log in</a>
  <p class="note">After logging in, this window will close automatically<br>and Claude Desktop will resume.</p>
</div>
</body>
</html>`, html.EscapeString(authURL))
		w.Write([]byte(page)) //nolint:errcheck
	})

	mux.HandleFunc("/callback", func(w http.ResponseWriter, r *http.Request) {
		q := r.URL.Query()

		if errMsg := q.Get("error"); errMsg != "" {
			desc := q.Get("error_description")
			if desc == "" {
				desc = errMsg
			}
			sendErrorHTML(w, desc)
			resultCh <- CallbackResult{Error: desc}
			return
		}

		state := q.Get("state")
		code := q.Get("code")

		if state != expectedState || code == "" {
			sendErrorHTML(w, "Invalid response from identity provider")
			resultCh <- CallbackResult{Error: "Invalid state or missing code"}
			return
		}

		sendSuccessHTML(w)
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

func sendSuccessHTML(w http.ResponseWriter) {
	w.Header().Set("Content-Type", "text/html")
	w.WriteHeader(200)
	w.Write([]byte(`<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Authentication Complete</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background: #f8f9fa;
    display: flex;
    align-items: center;
    justify-content: center;
    min-height: 100vh;
    padding: 20px;
  }
  .card {
    background: white;
    border-radius: 12px;
    box-shadow: 0 4px 24px rgba(0,0,0,0.08);
    padding: 48px;
    max-width: 440px;
    width: 100%;
    text-align: center;
  }
  .icon { font-size: 48px; margin-bottom: 16px; }
  h1 { font-size: 20px; color: #1a1a1a; margin-bottom: 12px; }
  p { font-size: 14px; color: #666; line-height: 1.6; }
</style>
</head>
<body>
<div class="card">
  <div class="icon">&#x2705;</div>
  <h1>Authentication Complete</h1>
  <p>You can close this tab.<br>Claude Desktop will resume automatically.</p>
</div>
<script>setTimeout(function(){ window.close(); }, 3000);</script>
</body>
</html>`)) //nolint:errcheck
}

func sendErrorHTML(w http.ResponseWriter, message string) {
	w.Header().Set("Content-Type", "text/html")
	w.WriteHeader(400)
	page := fmt.Sprintf(`<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Authentication Failed</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background: #f8f9fa;
    display: flex;
    align-items: center;
    justify-content: center;
    min-height: 100vh;
    padding: 20px;
  }
  .card {
    background: white;
    border-radius: 12px;
    box-shadow: 0 4px 24px rgba(0,0,0,0.08);
    padding: 48px;
    max-width: 440px;
    width: 100%%;
    text-align: center;
  }
  .icon { font-size: 48px; margin-bottom: 16px; }
  h1 { font-size: 20px; color: #c53030; margin-bottom: 12px; }
  p { font-size: 14px; color: #666; line-height: 1.6; }
  .error { background: #fff5f5; border: 1px solid #fed7d7; border-radius: 6px; padding: 12px; margin-top: 16px; font-size: 13px; color: #c53030; }
</style>
</head>
<body>
<div class="card">
  <div class="icon">&#x274c;</div>
  <h1>Authentication Failed</h1>
  <p>Please close this tab and try again, or contact your administrator.</p>
  <div class="error">%s</div>
</div>
</body>
</html>`, html.EscapeString(message))
	w.Write([]byte(page)) //nolint:errcheck
}
