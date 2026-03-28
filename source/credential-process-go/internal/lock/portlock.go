package lock

import (
	"fmt"
	"net"
	"time"
)

// AcquireOrWait tries to bind the port.
// If successful: returns true (caller should proceed with auth)
// If EADDRINUSE: polls every 500ms for up to 60 seconds, returns false (caller should check cache)
// Returns (acquired bool, err error)
func AcquireOrWait(port int) (bool, error) {
	addr := fmt.Sprintf("127.0.0.1:%d", port)

	ln, err := net.Listen("tcp", addr)
	if err == nil {
		// We got the port immediately. Close it so the caller can use it.
		ln.Close()
		return true, nil
	}

	// Port is in use (another auth in progress). Poll until it becomes free.
	deadline := time.Now().Add(60 * time.Second)
	for time.Now().Before(deadline) {
		time.Sleep(500 * time.Millisecond)

		ln, err := net.Listen("tcp", addr)
		if err == nil {
			// Port is free now - another process finished auth.
			ln.Close()
			return false, nil
		}
		// Still in use, keep polling.
	}

	// Timeout reached - another process may have stalled.
	return false, nil
}
