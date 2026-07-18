// ABOUTME: Windows process helpers for collector sidecar management —
// ABOUTME: liveness check via OpenProcess/GetExitCodeProcess, windowless detach.
//go:build windows

package main

import "syscall"

const (
	processQueryLimitedInformation = 0x1000
	stillActive                    = 259
	createNoWindow                 = 0x08000000
)

// isProcessAlive reports whether a process with the given PID is running.
// os.FindProcess always succeeds on Windows, so query the process directly.
func isProcessAlive(pid int) bool {
	h, err := syscall.OpenProcess(processQueryLimitedInformation, false, uint32(pid))
	if err != nil {
		return false
	}
	defer syscall.CloseHandle(h)
	var code uint32
	if err := syscall.GetExitCodeProcess(h, &code); err != nil {
		return false
	}
	return code == stillActive
}

// detachedSysProcAttr starts the collector in its own process group with no
// console window, so it outlives the helper and doesn't flash a window.
func detachedSysProcAttr() *syscall.SysProcAttr {
	return &syscall.SysProcAttr{
		CreationFlags: syscall.CREATE_NEW_PROCESS_GROUP | createNoWindow,
	}
}
