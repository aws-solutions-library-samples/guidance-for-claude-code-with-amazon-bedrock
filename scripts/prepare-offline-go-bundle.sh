#!/usr/bin/env bash
# ABOUTME: Prepares (on an internet-connected machine) and installs (on an offline
# ABOUTME: machine) everything `ccwb package` needs to build Go binaries and the
# ABOUTME: OTEL Collector sidecar without network access.
#
# The sidecar collector build (`_build_otelcol` in package.py) cannot use a
# vendor/ directory: OCB generates a fresh Go module in a temp dir on every
# run, then resolves its dependencies from the network. Instead, this script
# pre-seeds the two artifacts that build consults before touching the network:
#
#   1. The OCB binary at ~/.cache/ocb/ocb_<ver>_<os>_<arch> — package.py only
#      downloads it when that exact file is missing.
#   2. A Go module cache (GOMODCACHE) containing every module needed by both
#      source/go (credential-process, otel-helper) and the OCB-generated
#      collector. With GOPROXY=off, all `go` invocations — including the
#      `go mod tidy` OCB runs internally — resolve from this cache.
#
# Because every go/ocb subprocess in package.py inherits the parent
# environment, no changes to ccwb itself are required.
#
# Usage:
#   On a machine WITH internet (same OS/arch and Go version as the offline box):
#       ./scripts/prepare-offline-go-bundle.sh prepare [bundle-dir]
#   Transfer the resulting ccwb-offline-go-bundle.tar.gz, then on the OFFLINE box:
#       tar xzf ccwb-offline-go-bundle.tar.gz
#       ./scripts/prepare-offline-go-bundle.sh install [bundle-dir]
#       source <bundle-dir>/offline-env.sh
#       poetry run ccwb package --go
#
# Requirements on both machines: bash, Go >= 1.23 (ideally the same minor version).

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PACKAGE_PY="$REPO_ROOT/source/claude_code_with_bedrock/cli/commands/package.py"
MANIFEST="$REPO_ROOT/source/otel_helper/ocb-manifest.yaml"

MODE="${1:-prepare}"
BUNDLE_DIR="$(cd "$(dirname "${2:-$REPO_ROOT/ccwb-offline-go-bundle}")" 2>/dev/null && pwd)/$(basename "${2:-ccwb-offline-go-bundle}")"

# OCB version is pinned in package.py — parse it so the bundle can never drift.
OCB_VERSION="$(sed -n 's/.*OCB_VERSION = "\([0-9.]*\)".*/\1/p' "$PACKAGE_PY")"
if [ -z "$OCB_VERSION" ]; then
    echo "ERROR: could not parse OCB_VERSION from $PACKAGE_PY" >&2
    exit 1
fi

case "$(uname -s)" in
    Darwin) OCB_OS=darwin ;;
    MINGW*|MSYS*|CYGWIN*) OCB_OS=windows ;;
    *) OCB_OS=linux ;;
esac
case "$(uname -m)" in
    arm64|aarch64) OCB_ARCH=arm64 ;;
    *) OCB_ARCH=amd64 ;;
esac
OCB_SUFFIX=""
[ "$OCB_OS" = "windows" ] && OCB_SUFFIX=".exe"
OCB_NAME="ocb_${OCB_VERSION}_${OCB_OS}_${OCB_ARCH}${OCB_SUFFIX}"

write_env_file() {
    cat > "$BUNDLE_DIR/offline-env.sh" <<EOF
# Source this before running 'ccwb package' on the offline machine.
export GOMODCACHE="$BUNDLE_DIR/gomodcache"
export GOPROXY=off
export GOSUMDB=off
export GOTOOLCHAIN=local
EOF
}

prepare() {
    command -v go >/dev/null || { echo "ERROR: Go is required" >&2; exit 1; }
    mkdir -p "$BUNDLE_DIR/ocb" "$BUNDLE_DIR/gomodcache"
    go version | awk '{print $3}' > "$BUNDLE_DIR/GO_VERSION"

    echo "==> Downloading OCB v$OCB_VERSION ($OCB_OS/$OCB_ARCH)"
    if [ ! -f "$BUNDLE_DIR/ocb/$OCB_NAME" ]; then
        curl -fsSL -o "$BUNDLE_DIR/ocb/$OCB_NAME" \
            "https://github.com/open-telemetry/opentelemetry-collector-releases/releases/download/cmd%2Fbuilder%2Fv${OCB_VERSION}/${OCB_NAME}"
        [ "$OCB_OS" != "windows" ] && chmod +x "$BUNDLE_DIR/ocb/$OCB_NAME"
    fi

    export GOMODCACHE="$BUNDLE_DIR/gomodcache" GOTOOLCHAIN=local

    echo "==> Seeding module cache: source/go (credential-process, otel-helper)"
    # Copy go.mod/go.sum to a temp module so 'download all' can't mutate the repo's go.sum.
    tmp_mod="$(mktemp -d)"
    cp "$REPO_ROOT/source/go/go.mod" "$REPO_ROOT/source/go/go.sum" "$tmp_mod/"
    (cd "$tmp_mod" && go mod download all)
    rm -rf "$tmp_mod"

    echo "==> Seeding module cache: OCB-generated collector module"
    build_dir="$(mktemp -d)"
    sed "s|output_path: ./build/otelcol|output_path: $build_dir|" "$MANIFEST" > "$build_dir/manifest.yaml"
    "$BUNDLE_DIR/ocb/$OCB_NAME" --config "$build_dir/manifest.yaml" --skip-compilation
    (cd "$build_dir" && go mod download)

    echo "==> Verifying: rebuilding collector with GOPROXY=off (offline rehearsal)"
    verify_dir="$(mktemp -d)"
    sed "s|output_path: ./build/otelcol|output_path: $verify_dir|" "$MANIFEST" > "$verify_dir/manifest.yaml"
    (
        export GOPROXY=off GOSUMDB=off
        "$BUNDLE_DIR/ocb/$OCB_NAME" --config "$verify_dir/manifest.yaml" --skip-compilation
        cd "$verify_dir" && go mod download
        GOOS=linux GOARCH=amd64 CGO_ENABLED=0 go build -trimpath -o /dev/null .
    )
    rm -rf "$build_dir" "$verify_dir"

    write_env_file

    echo "==> Creating archive"
    tar -C "$(dirname "$BUNDLE_DIR")" -czf "$BUNDLE_DIR.tar.gz" "$(basename "$BUNDLE_DIR")"
    echo ""
    echo "Bundle ready: $BUNDLE_DIR.tar.gz ($(du -sh "$BUNDLE_DIR.tar.gz" | cut -f1))"
    echo "Transfer it to the offline machine, extract, then run:"
    echo "    ./scripts/prepare-offline-go-bundle.sh install <bundle-dir>"
}

install_bundle() {
    [ -d "$BUNDLE_DIR" ] || { echo "ERROR: bundle dir not found: $BUNDLE_DIR" >&2; exit 1; }

    if command -v go >/dev/null; then
        local_go="$(go version | awk '{print $3}')"
        bundled_go="$(cat "$BUNDLE_DIR/GO_VERSION" 2>/dev/null || echo unknown)"
        if [ "$local_go" != "$bundled_go" ]; then
            echo "WARNING: bundle was prepared with $bundled_go but this machine has $local_go." >&2
            echo "         Module resolution is usually compatible, but prefer matching versions." >&2
        fi
    fi

    echo "==> Installing OCB binary to ~/.cache/ocb/ (package.py skips its download when present)"
    mkdir -p "$HOME/.cache/ocb"
    cp "$BUNDLE_DIR/ocb/$OCB_NAME" "$HOME/.cache/ocb/$OCB_NAME"
    [ "$OCB_OS" != "windows" ] && chmod +x "$HOME/.cache/ocb/$OCB_NAME"

    write_env_file
    echo ""
    echo "Done. Before running 'ccwb package', activate the offline Go environment:"
    echo "    source $BUNDLE_DIR/offline-env.sh"
    echo "    poetry run ccwb package --go"
}

case "$MODE" in
    prepare) prepare ;;
    install) install_bundle ;;
    *) echo "Usage: $0 {prepare|install} [bundle-dir]" >&2; exit 1 ;;
esac
