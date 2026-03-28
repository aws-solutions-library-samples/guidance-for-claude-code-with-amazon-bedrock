package auth

import (
	"fmt"
	"io"
	"log"
	"net"
	"net/http"
)

// AuthResult holds the result from the OAuth callback.
type AuthResult struct {
	Code  string
	Error string
}

const successHTML = `<!DOCTYPE html>
<html>
<head>
    <title>Authentication Successful</title>
    <style>
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            display: flex;
            justify-content: center;
            align-items: center;
            min-height: 100vh;
            margin: 0;
            background-color: #f5f5f5;
        }
        .container {
            text-align: center;
            padding: 2rem;
            background: white;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }
        h1 { color: #2e7d32; }
        p { color: #666; }
    </style>
</head>
<body>
    <div class="container">
        <h1>Authentication successful! You can close this window.</h1>
        <p>Return to your terminal to continue.</p>
    </div>
</body>
</html>`

// startCallbackServer starts an HTTP server on the given port and returns
// a channel that will receive the AuthResult when the callback is handled.
func startCallbackServer(port int, expectedState string) (resultCh chan AuthResult, server *http.Server) {
	resultCh = make(chan AuthResult, 1)

	mux := http.NewServeMux()
	mux.HandleFunc("/callback", func(w http.ResponseWriter, r *http.Request) {
		query := r.URL.Query()

		if errMsg := query.Get("error"); errMsg != "" {
			errDesc := query.Get("error_description")
			if errDesc != "" {
				errMsg = errMsg + ": " + errDesc
			}
			http.Error(w, errMsg, http.StatusBadRequest)
			resultCh <- AuthResult{Error: errMsg}
			return
		}

		state := query.Get("state")
		if state != expectedState {
			http.Error(w, "Invalid state parameter", http.StatusBadRequest)
			resultCh <- AuthResult{Error: "invalid state parameter"}
			return
		}

		code := query.Get("code")
		if code == "" {
			http.Error(w, "Missing authorization code", http.StatusBadRequest)
			resultCh <- AuthResult{Error: "missing authorization code"}
			return
		}

		w.Header().Set("Content-Type", "text/html; charset=utf-8")
		w.WriteHeader(http.StatusOK)
		fmt.Fprint(w, successHTML)

		resultCh <- AuthResult{Code: code}
	})

	server = &http.Server{
		Addr:     fmt.Sprintf("127.0.0.1:%d", port),
		Handler:  mux,
		ErrorLog: log.New(io.Discard, "", 0),
	}

	listener, err := net.Listen("tcp", server.Addr)
	if err != nil {
		resultCh <- AuthResult{Error: fmt.Sprintf("failed to start callback server: %v", err)}
		return resultCh, server
	}

	go func() {
		if err := server.Serve(listener); err != nil && err != http.ErrServerClosed {
			resultCh <- AuthResult{Error: fmt.Sprintf("callback server error: %v", err)}
		}
	}()

	return resultCh, server
}
