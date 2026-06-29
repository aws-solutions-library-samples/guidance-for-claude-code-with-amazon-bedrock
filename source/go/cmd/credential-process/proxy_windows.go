//go:build windows

package main

import "os/exec"

// detachProcess is a no-op on Windows — the child process already runs
// independently when started without a console window.
func detachProcess(cmd *exec.Cmd) {
	// On Windows, processes spawned via exec.Command are already detached
	// from the parent. No SysProcAttr needed.
}
