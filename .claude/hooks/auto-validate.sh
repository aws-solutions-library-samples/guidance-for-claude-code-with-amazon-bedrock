#!/usr/bin/env bash
# PostToolUse hook: auto-validates edited files
# Runs ruff on Python files, cfn-lint on CloudFormation templates
# Non-blocking: always exits 0

set -euo pipefail

INPUT=$(cat)
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // .tool_input.filePath // empty' 2>/dev/null)

if [ -z "$FILE_PATH" ]; then
  exit 0
fi

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || echo ".")"

# Python files: run ruff
if [[ "$FILE_PATH" == *.py ]]; then
  if command -v ruff &>/dev/null; then
    ISSUES=$(cd "$REPO_ROOT/source" && ruff check --no-fix "$FILE_PATH" 2>&1) || true
    if [ -n "$ISSUES" ]; then
      echo "--- ruff found issues in $(basename "$FILE_PATH") ---" >&2
      echo "$ISSUES" >&2
      echo "Run: cd source && poetry run ruff check --fix $FILE_PATH" >&2
    fi
  fi
fi

# CloudFormation templates: run cfn-lint
if [[ "$FILE_PATH" == */deployment/infrastructure/*.yaml ]]; then
  if command -v cfn-lint &>/dev/null; then
    ISSUES=$(cfn-lint "$FILE_PATH" 2>&1) || true
    if [ -n "$ISSUES" ]; then
      echo "--- cfn-lint found issues in $(basename "$FILE_PATH") ---" >&2
      echo "$ISSUES" >&2
    fi
  fi
fi

exit 0
