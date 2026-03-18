package quota

import (
	"fmt"
	"html"
	"math"
	"net"
	"net/http"
	"os"

	"github.com/pkg/browser"
)

// ShowBrowserNotification starts a temporary HTTP server on the given port and opens the browser.
// isBlocked: determines if it shows a "blocked" vs "warning" page
func ShowBrowserNotification(result *Result, isBlocked bool, port int) {
	usage := result.Usage
	if usage == nil {
		usage = make(map[string]interface{})
	}
	message := result.Message

	monthlyPercent := toFloat64(usage["monthly_percent"])
	dailyPercent := toFloat64(usage["daily_percent"])
	monthlyTokens := toFloat64(usage["monthly_tokens"])
	monthlyLimit := toFloat64(usage["monthly_limit"])
	dailyTokens := toFloat64(usage["daily_tokens"])
	dailyLimit := toFloat64(usage["daily_limit"])

	// Status styling
	var statusText, statusColor, headerBg string
	if isBlocked {
		statusText = "Access Blocked"
		statusColor = "#dc3545"
		headerBg = "#f8d7da"
	} else {
		statusText = "Quota Warning"
		statusColor = "#ffc107"
		headerBg = "#fff3cd"
	}

	monthlyBarColor := barColor(monthlyPercent)
	dailyBarColor := barColor(dailyPercent)
	if dailyLimit == 0 {
		dailyBarColor = "#6c757d"
	}

	// Build daily section HTML
	dailySection := ""
	if dailyLimit > 0 {
		dailySection = fmt.Sprintf(`
            <div class="usage-section">
                <div class="usage-label">
                    <span>Daily Usage</span>
                    <span class="usage-value">%s / %s (%.1f%%)</span>
                </div>
                <div class="progress-bar">
                    <div class="progress-fill" style="width: %.0f%%; background: %s;">
                        %.0f%%
                    </div>
                </div>
            </div>`,
			formatTokens(dailyTokens), formatTokens(dailyLimit), dailyPercent,
			math.Min(dailyPercent, 100), dailyBarColor, dailyPercent)
	}

	// Build message HTML
	escapedMessage := ""
	if message != "" {
		escapedMessage = html.EscapeString(message)
	} else if isBlocked {
		escapedMessage = "Your access has been blocked due to quota limits."
	} else {
		escapedMessage = "You're approaching your quota limit."
	}
	if isBlocked {
		escapedMessage += " Contact your administrator for assistance."
	}

	htmlPage := fmt.Sprintf(`<!DOCTYPE html>
<html>
<head>
    <title>Quota Status - Claude Code</title>
    <style>
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif;
            margin: 0;
            padding: 40px;
            background: #f5f5f5;
            min-height: 100vh;
            box-sizing: border-box;
        }
        .container {
            max-width: 500px;
            margin: 0 auto;
            background: white;
            border-radius: 12px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
            overflow: hidden;
        }
        .header {
            background: %s;
            padding: 30px;
            text-align: center;
            border-bottom: 1px solid rgba(0,0,0,0.1);
        }
        .header h1 {
            margin: 0;
            color: %s;
            font-size: 28px;
        }
        .content {
            padding: 30px;
        }
        .usage-section {
            margin-bottom: 25px;
        }
        .usage-label {
            display: flex;
            justify-content: space-between;
            margin-bottom: 8px;
            font-size: 14px;
            color: #666;
        }
        .usage-value {
            font-weight: 600;
            color: #333;
        }
        .progress-bar {
            height: 24px;
            background: #e9ecef;
            border-radius: 12px;
            overflow: hidden;
        }
        .progress-fill {
            height: 100%%;
            border-radius: 12px;
            transition: width 0.3s ease;
            display: flex;
            align-items: center;
            justify-content: flex-end;
            padding-right: 10px;
            font-size: 12px;
            font-weight: 600;
            color: white;
            box-sizing: border-box;
        }
        .message {
            background: #f8f9fa;
            padding: 15px;
            border-radius: 8px;
            font-size: 14px;
            color: #666;
            line-height: 1.5;
            margin-bottom: 20px;
        }
        .footer {
            text-align: center;
            padding: 20px;
            background: #f8f9fa;
            font-size: 13px;
            color: #666;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>%s</h1>
        </div>
        <div class="content">
            <div class="usage-section">
                <div class="usage-label">
                    <span>Monthly Usage</span>
                    <span class="usage-value">%s / %s (%.1f%%)</span>
                </div>
                <div class="progress-bar">
                    <div class="progress-fill" style="width: %.0f%%; background: %s;">
                        %.0f%%
                    </div>
                </div>
            </div>%s
            <div class="message">
                %s
            </div>
        </div>
        <div class="footer">
            Return to your terminal to continue.
        </div>
    </div>
</body>
</html>`,
		headerBg, statusColor,
		statusText,
		formatTokens(monthlyTokens), formatTokens(monthlyLimit), monthlyPercent,
		math.Min(monthlyPercent, 100), monthlyBarColor, monthlyPercent,
		dailySection,
		escapedMessage,
	)

	// Try to start HTTP server; don't fail if port unavailable
	ln, err := net.Listen("tcp", fmt.Sprintf("127.0.0.1:%d", port))
	if err != nil {
		// Port unavailable, skip browser notification
		return
	}

	served := make(chan struct{}, 1)

	mux := http.NewServeMux()
	mux.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/html")
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte(htmlPage))
		select {
		case served <- struct{}{}:
		default:
		}
	})

	server := &http.Server{Handler: mux}

	go func() {
		_ = server.Serve(ln)
	}()

	// Open browser
	_ = browser.OpenURL(fmt.Sprintf("http://localhost:%d/quota-status", port))

	// Wait for one request to be served
	<-served

	// Shut down server
	_ = server.Close()
}

// barColor returns the progress bar color based on usage percentage.
func barColor(pct float64) string {
	switch {
	case pct >= 100:
		return "#dc3545" // Red
	case pct >= 90:
		return "#fd7e14" // Orange
	case pct >= 80:
		return "#ffc107" // Yellow
	default:
		return "#28a745" // Green
	}
}

// formatTokens formats a token count for display (e.g., 1.5B, 2.3M, 100K).
func formatTokens(n float64) string {
	switch {
	case n >= 1_000_000_000:
		return fmt.Sprintf("%.1fB", n/1_000_000_000)
	case n >= 1_000_000:
		return fmt.Sprintf("%.1fM", n/1_000_000)
	case n >= 1_000:
		return fmt.Sprintf("%.1fK", n/1_000)
	default:
		return fmt.Sprintf("%d", int64(n))
	}
}

// debugPrint prints a debug message to stderr if debug is true.
func debugPrint(debug bool, format string, args ...interface{}) {
	if debug {
		fmt.Fprintf(os.Stderr, "Debug: "+format+"\n", args...)
	}
}
