package portlock

import (
	"fmt"
	"net"
	"time"
)

// TryAcquire attempts to bind to the given port on 127.0.0.1.
// If successful, returns the listener (caller must close it before starting the callback server).
// If the port is busy, returns nil and no error.
func TryAcquire(port int) (net.Listener, error) {
	ln, err := net.Listen("tcp", fmt.Sprintf("127.0.0.1:%d", port))
	if err != nil {
		// Port is busy
		return nil, nil
	}
	return ln, nil
}

// WaitForRelease polls until the port becomes available or timeout is reached.
// Returns true if the port was released, false on timeout.
func WaitForRelease(port int, timeout time.Duration) bool {
	deadline := time.Now().Add(timeout)
	for time.Now().Before(deadline) {
		ln, err := net.Listen("tcp", fmt.Sprintf("127.0.0.1:%d", port))
		if err == nil {
			ln.Close()
			return true
		}
		time.Sleep(500 * time.Millisecond)
	}
	return false
}
