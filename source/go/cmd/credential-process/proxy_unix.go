//go:build !windows

package main

import (
	"os/exec"
	"syscall"
)

// detachProcess sets process attributes to detach from the parent (Unix only).
func detachProcess(cmd *exec.Cmd) {
	cmd.SysProcAttr = &syscall.SysProcAttr{Setsid: true}
}
