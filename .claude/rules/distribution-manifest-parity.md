# Distribution Manifest Parity

## Rule
When adding a new file that ships to end users, update ALL distribution paths:
1. `package.py` — local package creation (installer, settings)
2. `distribute.py` — S3/landing page archives (per-OS zips + full archive)

These are independent code paths with no shared manifest. Missing a file
in one silently breaks end-user deployments.

## Checklist (for any new distributable file)
- [ ] Added to `_create_archive()` all-files list in distribute.py
- [ ] Added to per-OS file list in `_upload_landing_page_packages()`
- [ ] Added to `PLATFORM_FILES[platform]["installer"]` or `["binaries"]`
- [ ] Added to `package.py` installer copy logic
- [ ] Added test assertion in `test_distribute.py` confirming zip contains file

## Why
install.bat/install.sh reference files by name. If the distribution
archive doesn't include them, the installer configures paths that don't
exist → silent failures (no error, just missing functionality).

## Anti-Pattern
```python
# ❌ Adding to package.py but forgetting distribute.py
# package.py copies otel-helper.cmd to install dir ✓
# distribute.py never includes it in the zip ✗
# Result: install.bat references otel-helper.cmd → "not recognized"
```

## Related
- PR #572 (introduced .cmd/.ps1 but missed distribute.py)
- PR #672 (fix)
- `binary-distribution.md`, `go-binary-architecture.md`
