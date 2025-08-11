#!/bin/bash
# Enterprise wrapper installation script for Claude Code
set -euo pipefail

# Configuration
WRAPPER_NAME="claude-enterprise"
INSTALL_DIR="/usr/local/bin"
CONFIG_DIR="$HOME/.claude-code"
WRAPPER_SCRIPT="claude-code-wrapper.py"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Utility functions
log_info() {
    echo -e "${BLUE}ℹ️  $1${NC}"
}

log_success() {
    echo -e "${GREEN}✅ $1${NC}"
}

log_warning() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

log_error() {
    echo -e "${RED}❌ $1${NC}"
}

# Check if we're running as root for system-wide install
check_permissions() {
    if [[ $EUID -eq 0 ]]; then
        log_info "Running as root - will install system-wide to $INSTALL_DIR"
        return 0
    else
        log_warning "Not running as root - will install to user directory"
        INSTALL_DIR="$HOME/.local/bin"
        mkdir -p "$INSTALL_DIR"
        return 0
    fi
}

# Check dependencies
check_dependencies() {
    log_info "Checking dependencies..."
    
    # Check Python
    if ! command -v python3 &> /dev/null; then
        log_error "Python 3 is required but not installed"
        exit 1
    fi
    
    # Check Claude Code
    if ! command -v claude &> /dev/null; then
        log_warning "Claude Code not found in PATH"
        log_info "Please install Claude Code first:"
        log_info "  npm install -g @anthropic-ai/claude-code"
        read -p "Continue anyway? (y/N): " -r
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            exit 1
        fi
    else
        CLAUDE_VERSION=$(claude --version 2>/dev/null || echo "unknown")
        log_success "Found Claude Code: $CLAUDE_VERSION"
    fi
    
    # Check AWS CLI (optional but recommended)
    if ! command -v aws &> /dev/null; then
        log_warning "AWS CLI not found - some features may not work"
    fi
}

# Install the wrapper script
install_wrapper() {
    log_info "Installing enterprise wrapper..."
    
    # Copy the wrapper script
    WRAPPER_PATH="$INSTALL_DIR/$WRAPPER_NAME"
    
    if [[ ! -f "$WRAPPER_SCRIPT" ]]; then
        log_error "Wrapper script not found: $WRAPPER_SCRIPT"
        log_info "Please run this script from the enterprise-addons/governance directory"
        exit 1
    fi
    
    cp "$WRAPPER_SCRIPT" "$WRAPPER_PATH"
    chmod +x "$WRAPPER_PATH"
    
    log_success "Installed wrapper to: $WRAPPER_PATH"
}

# Create configuration directory
setup_config() {
    log_info "Setting up configuration directory..."
    
    mkdir -p "$CONFIG_DIR"
    
    # Create default enterprise config if it doesn't exist
    DEFAULT_CONFIG="$CONFIG_DIR/enterprise-config.json"
    if [[ ! -f "$DEFAULT_CONFIG" ]]; then
        cat > "$DEFAULT_CONFIG" << 'EOF'
{
  "security_profile": "standard",
  "cost_tracking_enabled": true,
  "user_attribute_mapping_enabled": true,
  "monitoring_enabled": false,
  "audit_log_path": null,
  "otel_endpoint": "http://localhost:4317"
}
EOF
        log_success "Created default config: $DEFAULT_CONFIG"
    else
        log_info "Using existing config: $DEFAULT_CONFIG"
    fi
}

# Add to PATH if needed
setup_path() {
    if [[ "$INSTALL_DIR" == "$HOME/.local/bin" ]]; then
        # Check if ~/.local/bin is in PATH
        if [[ ":$PATH:" != *":$HOME/.local/bin:"* ]]; then
            log_warning "$HOME/.local/bin is not in PATH"
            log_info "Add this to your shell profile (~/.bashrc, ~/.zshrc, etc.):"
            echo "  export PATH=\"\$HOME/.local/bin:\$PATH\""
        fi
    fi
}

# Create shell aliases
create_aliases() {
    log_info "Setting up shell aliases..."
    
    ALIAS_FILE="$CONFIG_DIR/aliases.sh"
    cat > "$ALIAS_FILE" << EOF
# Claude Code Enterprise Aliases
# Source this file in your shell profile for convenient access

# Direct profile aliases
alias claude-plan='$WRAPPER_NAME --security-profile=plan-only'
alias claude-restricted='$WRAPPER_NAME --security-profile=restricted'
alias claude-standard='$WRAPPER_NAME --security-profile=standard'
alias claude-elevated='$WRAPPER_NAME --security-profile=elevated'

# Utility aliases
alias claude-check='$WRAPPER_NAME --check-policy'
alias claude-profile='echo "Active profile: \$CLAUDE_ENTERPRISE_PROFILE"'

# Set default profile if not already set
if [[ -z "\${CLAUDE_ENTERPRISE_PROFILE:-}" ]]; then
    export CLAUDE_ENTERPRISE_PROFILE="standard"
fi
EOF
    
    log_success "Created aliases file: $ALIAS_FILE"
    log_info "To enable aliases, add this to your shell profile:"
    echo "  source $ALIAS_FILE"
}

# Test the installation
test_installation() {
    log_info "Testing installation..."
    
    if [[ -x "$INSTALL_DIR/$WRAPPER_NAME" ]]; then
        # Test the wrapper
        if "$INSTALL_DIR/$WRAPPER_NAME" --check-policy &>/dev/null; then
            log_success "Wrapper test passed"
        else
            log_warning "Wrapper test failed - check configuration"
        fi
    else
        log_error "Installation failed - wrapper not executable"
        exit 1
    fi
}

# Print usage instructions
print_usage() {
    log_success "Installation completed successfully!"
    echo
    log_info "Usage:"
    echo "  $WRAPPER_NAME                    # Use with default profile"
    echo "  $WRAPPER_NAME --security-profile=restricted"
    echo "  $WRAPPER_NAME --check-policy     # Check compliance"
    echo
    log_info "Profile shortcuts:"
    echo "  claude-plan                      # Plan-only mode"
    echo "  claude-restricted                # Restricted development"
    echo "  claude-standard                  # Standard enterprise"
    echo "  claude-elevated                  # Advanced permissions"
    echo
    log_info "Configuration:"
    echo "  Config file: $CONFIG_DIR/enterprise-config.json"
    echo "  Aliases:     $CONFIG_DIR/aliases.sh"
    echo
    log_info "Next steps:"
    echo "  1. Configure your enterprise profile with 'ccwb enterprise configure'"
    echo "  2. Deploy policies with 'ccwb enterprise deploy-policies'"
    echo "  3. Start using Claude Code with enterprise controls"
}

# Main installation process
main() {
    echo
    log_info "Claude Code Enterprise Wrapper Installation"
    echo
    
    check_permissions
    check_dependencies
    install_wrapper
    setup_config
    setup_path
    create_aliases
    test_installation
    print_usage
}

# Handle command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --uninstall)
            log_info "Uninstalling enterprise wrapper..."
            rm -f "$INSTALL_DIR/$WRAPPER_NAME"
            log_success "Uninstalled successfully"
            exit 0
            ;;
        --help|-h)
            echo "Usage: $0 [--uninstall] [--help]"
            echo
            echo "Options:"
            echo "  --uninstall    Remove the enterprise wrapper"
            echo "  --help         Show this help message"
            exit 0
            ;;
        *)
            log_error "Unknown option: $1"
            echo "Use --help for usage information"
            exit 1
            ;;
    esac
    shift
done

# Run main installation
main