# Windows Platform Guards

## Rule
Add platform-specific guards for Windows compatibility:
- `SO_REUSEADDR` needs `sys.platform != "win32"` guard
- Use `shutil.move()` not `os.rename()`
- Always `open(path, encoding="utf-8")`
- CRLF line endings in generated scripts

## Why
Windows handles sockets, file operations, and encodings differently. These differences cause runtime failures if not handled properly.

## Examples
```python
# ✅ Correct socket handling
if sys.platform != "win32":
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

# ✅ Correct file operations
import shutil
shutil.move(src, dst)  # NOT os.rename() — fails cross-device on Windows

# ✅ Correct file encoding
open(path, encoding="utf-8")  # ALWAYS specify encoding

# ❌ Wrong - crashes on Windows
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)  # Always
os.rename(src, dst)  # Fails cross-device
open(path)  # Uses system default encoding
```

## Common Cross-Platform Mistakes

- `os.rename` → use `os.replace` (rename fails on Windows when target exists)
- `subprocess` with `shell=True` → uses `cmd.exe` on Windows, not bash. Verify portability.
- Hardcoded `/` in paths → use `pathlib.Path` or `os.path.join`
- `print()` in credential-process → only for final JSON output (AWS SDK parses stdout)
- File permissions `0o600` → no-op on Windows (skip permission checks with `runtime.GOOS` guard in Go)

## Related Issues
#267, #348, #350, #353, #356, #357, #381, #427, #428, #429