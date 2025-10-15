> 📚 [Back to Documentation Hub](../README.md)

# How to Configure and Use Claude Code Plugins

> **Goal**: Successfully install, configure, and use plugins from the Claude Code marketplace
> **Use case**: Teams and individuals who need to extend Claude Code with specialized tools
> **Time required**: 15-30 minutes for basic setup, 1-2 hours for enterprise configuration

## Prerequisites
Before starting, you should:
- Have Claude Code installed and authenticated
- Be familiar with Claude Code basic commands
- Understand your project's development workflow needs
- Have access to your project repository (for team configuration)
- Know which problems you're trying to solve (documentation, security, testing, etc.)

## Problem Context
Claude Code provides powerful base functionality, but specialized development tasks require additional tools. The Claude Code Plugins Marketplace (`aws-solutions-library-samples/guidance-for-claude-code-with-amazon-bedrock`) offers 11 production-ready plugins for systematic development, documentation, security, testing, and more. This guide shows you how to install, configure, and use these plugins effectively.

## Solution Overview
We'll solve this by:
1. Adding the marketplace to your Claude Code installation
2. Installing individual plugins or bundles based on your needs
3. Configuring team-wide plugin requirements
4. Using plugin components (agents, commands, hooks)
5. Troubleshooting common configuration issues

**Why this approach**: The marketplace provides modular, battle-tested plugins that integrate seamlessly with Claude Code, avoiding the need to build custom tooling from scratch.

## Step 1: Add the Marketplace

Connect Claude Code to the plugins marketplace:

```bash
# Add the marketplace (one-time setup)
/plugin marketplace add aws-solutions-library-samples/guidance-for-claude-code-with-amazon-bedrock

# Verify marketplace was added
/plugin marketplace list
```

**Expected result**: You should see `aws-solutions-library-samples/guidance-for-claude-code-with-amazon-bedrock` in the marketplace list.

**Alternative using CLI**:
```bash
# If using Claude Code from terminal
claude "/plugin marketplace add aws-solutions-library-samples/guidance-for-claude-code-with-amazon-bedrock"
```

## Step 2: Browse Available Plugins

Explore plugins interactively to find what you need:

```bash
# Interactive browser showing all 11 plugins
/plugin

# Or browse specific marketplace
/plugin browse aws-solutions-library-samples/guidance-for-claude-code-with-amazon-bedrock
```

**What you'll see**:
- Plugin names and descriptions
- Categories (workflow, documentation, security, testing, etc.)
- Version information
- Installation commands

**Success criteria**: You can see the list of 11 plugins: epcc-workflow, documentation, architecture, security, testing, performance, tdd-workflow, agile-tools, ux-design, deployment, code-analysis.

## Step 3: Install Your First Plugin

Start with the EPCC workflow plugin (recommended for systematic development):

```bash
# Install EPCC workflow plugin
/plugin install epcc-workflow
# Verify installation
/plugin list
```

**Expected result**: The plugin appears in your installed plugins list, and new commands become available.

**Verify it worked**: Try using a plugin command:
```bash
# Test the explore command
/epcc-explore

# Test calling a plugin agent
@code-archaeologist
```

If the command and agent are recognized, the plugin is installed correctly.

## Step 4: Install Plugin Bundles

Instead of installing plugins individually, use pre-configured bundles for common scenarios.

### Understanding Team-Level Plugin Enforcement

Claude Code supports **team-level required plugins** through `.claude/settings.json`. When this file exists in your project root:

**How it works:**
1. Any team member opening the project in Claude Code sees the required plugins
2. Claude Code automatically prompts to install missing plugins
3. All team members get the same tooling and capabilities
4. Configuration is version-controlled with your code

**Key benefits:**
- ✅ **Consistent tooling** - Everyone uses the same agents, commands, and hooks
- ✅ **Zero configuration** - New team members automatically get required plugins
- ✅ **Team standards** - Enforce security, testing, and quality practices
- ✅ **Seamless onboarding** - One git clone gets complete setup

**Enforcement level:**
- `requiredPlugins`: Shows prompts but doesn't block usage
- Best combined with code review requirements and CI/CD checks

### Starter Bundle (Recommended for Teams Getting Started)

Create `.claude/settings.json` in your project root:

```json
{
  "requiredMarketplaces": [
    "aws-solutions-library-samples/guidance-for-claude-code-with-amazon-bedrock"
  ],
  "requiredPlugins": [
    "epcc-workflow@aws-claude-code-plugins",
    "documentation@aws-claude-code-plugins",
    "security@aws-claude-code-plugins"
  ]
}
```

**What this does**:
- Automatically installs 3 essential plugins for all team members
- Enforces systematic development workflow (EPCC)
- Enables comprehensive documentation (Diataxis framework)
- Provides security scanning and compliance

**When to use**: Small to medium teams starting with AI-assisted development.

### Full-Stack Bundle (Comprehensive Development)

```json
{
  "requiredMarketplaces": [
    "aws-solutions-library-samples/guidance-for-claude-code-with-amazon-bedrock"
  ],
  "requiredPlugins": [
    "epcc-workflow@aws-claude-code-plugins",
    "documentation@aws-claude-code-plugins",
    "architecture@aws-claude-code-plugins",
    "testing@aws-claude-code-plugins",
    "ux-design@aws-claude-code-plugins"
  ]
}
```

**When to use**: Full-stack teams building web applications with frontend and backend components.

### Enterprise Bundle (Complete Enterprise Toolkit)

```json
{
  "requiredMarketplaces": [
    "aws-solutions-library-samples/guidance-for-claude-code-with-amazon-bedrock"
  ],
  "requiredPlugins": [
    "epcc-workflow@aws-claude-code-plugins",
    "security@aws-claude-code-plugins",
    "testing@aws-claude-code-plugins",
    "performance@aws-claude-code-plugins",
    "architecture@aws-claude-code-plugins",
    "deployment@aws-claude-code-plugins",
    "agile-tools@aws-claude-code-plugins"
  ]
}
```

**When to use**: Enterprise teams requiring security, compliance, performance monitoring, and deployment automation.

### TDD Bundle (Test-Driven Development)

```json
{
  "requiredMarketplaces": [
    "aws-solutions-library-samples/guidance-for-claude-code-with-amazon-bedrock"
  ],
  "requiredPlugins": [
    "tdd-workflow@aws-claude-code-plugins",
    "testing@aws-claude-code-plugins",
    "epcc-workflow@aws-claude-code-plugins"
  ]
}
```

**When to use**: Teams practicing test-driven development with red-green-refactor cycles.

**Success criteria**: After creating `.claude/settings.json`, run `/plugin list` to verify all required plugins are installed automatically.

## Step 5: Using Plugin Agents

Plugins provide specialized agents for specific tasks. Call agents using the `@` prefix:

```bash
# Call single agent
@security-reviewer

# Call multiple agents in parallel (key pattern)
@docs-tutorial-agent @docs-howto-agent @docs-reference-agent @docs-explanation-agent

# Cross-functional team deployment
@architect @security-reviewer @qa-engineer @deployment-agent
```

**Working example** - Security review:
```bash
# Ask Claude to review security with the security plugin agent
claude "@security-reviewer scan this codebase for vulnerabilities and generate a report"
```

**Expected output**: Security analysis report covering:
- Potential vulnerabilities
- Compliance issues
- Security recommendations
- Risk assessment

**Agent orchestration pattern** - Complete documentation:
```bash
# Generate complete documentation set using parallel agents
claude "@docs-tutorial-agent @docs-howto-agent @docs-reference-agent @docs-explanation-agent create comprehensive documentation for the authentication system"
```

**Why parallel**: Deploying agents in parallel is more efficient than sequential execution and leverages Claude Code's concurrent processing capabilities.

## Step 6: Using Plugin Commands

Plugins provide slash commands with argument support:

```bash
# EPCC workflow commands
/epcc-explore "authentication module"
/epcc-plan
/epcc-code
/epcc-commit

# Documentation commands with smart routing
/docs-create "API endpoints" --complete
/docs-create "user guide" --learning
/docs-howto "configure SSL"

# TDD workflow commands
/tdd-feature "user login"
/tdd-bugfix "authentication timeout"

# Security commands
/security-scan --strict
/permission-audit

# Architecture commands
/design-architecture "microservices system"
/code-review --comprehensive
```

**Working example** - EPCC exploration with depth control:
```bash
# Quick exploration (uses default depth)
/epcc-explore "database layer"

# Deep exploration (more thorough analysis)
/epcc-explore "payment processing" --deep
```

**Expected result**: Creates `EPCC_EXPLORE.md` with comprehensive analysis of the specified area.

## Step 7: Configure Security Hooks

Security plugin provides pre-commit hooks to block dangerous operations.

Create `hooks/security_check.py` in your project:

```python
#!/usr/bin/env python3
"""Security validation hook for Claude Code."""

import sys
import re

def check_secrets(file_path, content):
    """Check for potential secrets in code."""
    secret_patterns = [
        r'api[_-]?key\s*=\s*["\'][\w\-]+["\']',
        r'secret[_-]?key\s*=\s*["\'][\w\-]+["\']',
        r'password\s*=\s*["\'][\w\-]+["\']',
        r'token\s*=\s*["\'][\w\-]+["\']',
    ]

    for pattern in secret_patterns:
        if re.search(pattern, content, re.IGNORECASE):
            print(f"ERROR: Potential secret detected in {file_path}")
            return False

    return True

def main():
    file_path = sys.argv[1] if len(sys.argv) > 1 else None
    content = sys.stdin.read()

    if not check_secrets(file_path, content):
        sys.exit(1)

    sys.exit(0)

if __name__ == "__main__":
    main()
```

Add hook configuration to `.claude/settings.json`:

```json
{
  "requiredPlugins": [
    "security@aws-claude-code-plugins"
  ],
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Write|Edit",
        "hooks": [
          {
            "type": "command",
            "command": "python hooks/security_check.py",
            "blocking": true,
            "description": "Check for secrets before writing files"
          }
        ]
      }
    ]
  }
}
```

**Make script executable**:
```bash
chmod +x hooks/security_check.py
```

**Test the security hook**:
```bash
# This should be blocked by the hook
echo 'API_KEY="sk-1234567890"' > test.py
claude "edit test.py to add a function"
```

**Expected result**: Hook blocks the operation and displays error about potential secret.

**Verify it worked**: The file write should be prevented, and you'll see a security warning.

## Step 8: Configure Quality Gates

Testing plugin provides automated quality checks before commits.

Add to `.claude/settings.json`:

```json
{
  "requiredPlugins": [
    "testing@aws-claude-code-plugins"
  ],
  "hooks": {
    "PreCommit": [
      {
        "type": "command",
        "command": "black --check .",
        "blocking": true,
        "description": "Check Python code formatting"
      },
      {
        "type": "command",
        "command": "ruff check .",
        "blocking": true,
        "description": "Run linting checks"
      },
      {
        "type": "command",
        "command": "mypy . --ignore-missing-imports",
        "blocking": false,
        "description": "Type checking (warning only)"
      },
      {
        "type": "command",
        "command": "pytest tests/ --quiet",
        "blocking": true,
        "description": "Run test suite"
      }
    ]
  }
}
```

**What each gate does**:
- **black**: Ensures consistent code formatting (blocking)
- **ruff**: Checks for code quality issues (blocking)
- **mypy**: Validates type hints (non-blocking warning)
- **pytest**: Runs test suite (blocking)

**Install required tools**:
```bash
# Using uv (recommended)
uvx black --version
uvx ruff --version
uvx mypy --version
uvx pytest --version

# Or install traditionally
pip install black ruff mypy pytest
```

**Test quality gates**:
```bash
# Trigger a commit that will run gates
git add .
git commit -m "test quality gates"
```

**Expected result**: All quality checks run automatically. Commit proceeds only if all blocking checks pass.

## Step 9: Enable/Disable Plugins

Manage plugins without uninstalling:

```bash
# Disable a plugin temporarily
/plugin disable security
# Enable it again
/plugin enable security
# List all plugins showing enabled/disabled status
/plugin list
```

**When to disable**:
- Testing without certain constraints
- Performance optimization
- Troubleshooting plugin conflicts

**Note**: Disabled plugins remain installed but their agents, commands, and hooks are inactive.

## Step 10: Update and Uninstall Plugins

Keep plugins current or remove unused ones:

```bash
# Check for plugin updates
/plugin update --check

# Update specific plugin
/plugin update epcc-workflow
# Update all plugins
/plugin update --all

# Uninstall plugin
/plugin uninstall performance
# Uninstall with confirmation
/plugin uninstall --force performance```

**Best practice**: Update plugins regularly to get bug fixes and new features.

**Verify updates worked**:
```bash
# Check version numbers
/plugin list --verbose
```

## Verification

Confirm your plugin configuration works correctly:

```bash
# Test marketplace access
/plugin marketplace list
# Expected: aws-solutions-library-samples/guidance-for-claude-code-with-amazon-bedrock appears

# Test plugin installation
/plugin list
# Expected: Your installed plugins appear with version numbers

# Test agent availability
@code-archaeologist
# Expected: Agent responds or shows help

# Test command availability
/epcc-explore
# Expected: Command executes or prompts for input

# Test hooks (if configured)
git commit -m "test hooks"
# Expected: Quality gates run automatically
```

**Success indicators**:
- Marketplace is accessible
- Plugins appear in list
- Agents respond to @ mentions
- Slash commands are recognized
- Hooks execute on appropriate triggers

## Troubleshooting

### Problem: Marketplace Not Found
**Symptoms**: `/plugin marketplace list` doesn't show aws-solutions-library-samples/guidance-for-claude-code-with-amazon-bedrock
**Cause**: Marketplace not added or network issue
**Solution**:
```bash
# Re-add marketplace
/plugin marketplace add aws-solutions-library-samples/guidance-for-claude-code-with-amazon-bedrock

# Check internet connectivity
curl -I https://github.com/aws-solutions-library-samples/guidance-for-claude-code-with-amazon-bedrock

# Verify marketplace file
cat ~/.claude/marketplaces.json
```

### Problem: Plugin Not Installing
**Symptoms**: `/plugin install` fails or plugin doesn't appear in list
**Cause**: Version mismatch, permission issue, or corrupt cache
**Solution**:
```bash
# Clear plugin cache
rm -rf ~/.claude/plugins/cache

# Try with explicit version
/plugin install epcc-workflow@1.0.0
# Check permissions
ls -la ~/.claude/plugins/

# Reinstall if necessary
/plugin uninstall epcc-workflow/plugin install epcc-workflow```

### Problem: Agent Not Responding
**Symptoms**: `@agent-name` is not recognized or doesn't work
**Cause**: Plugin not installed, agent name typo, or plugin disabled
**Solution**:
```bash
# Verify plugin is installed and enabled
/plugin list

# Check exact agent name in plugin
cat ~/.claude/plugins/epcc-workflow/agents/code-archaeologist.md

# Enable if disabled
/plugin enable epcc-workflow
# Restart Claude Code session
/clear
```

### Problem: Command Not Available
**Symptoms**: Slash command shows "command not found"
**Cause**: Plugin not installed or command prefix incorrect
**Solution**:
```bash
# Verify plugin with commands is installed
/plugin list

# Use tab completion to find correct command
/epcc[TAB]

# Check command files exist
ls ~/.claude/plugins/epcc-workflow/commands/

# Reload plugins
/plugin reload
```

### Problem: Hooks Not Triggering
**Symptoms**: PreCommit or PreToolUse hooks don't execute
**Cause**: Invalid JSON in settings.json, incorrect matcher, or script not executable
**Solution**:
```bash
# Validate JSON syntax
python -m json.tool .claude/settings.json

# Check hook script permissions
ls -la hooks/security_check.py

# Make script executable
chmod +x hooks/security_check.py

# Test hook directly
python hooks/security_check.py test_file.py < test_file.py

# Check Claude Code hook logs
cat ~/.claude/logs/hooks.log
```

### Problem: Team Settings Not Applied
**Symptoms**: Team members don't have required plugins automatically
**Cause**: settings.json not committed, wrong location, or cache issue
**Solution**:
```bash
# Verify settings.json is in correct location
ls -la .claude/settings.json

# Check settings.json is committed to git
git ls-files .claude/settings.json

# Have team members pull latest
git pull origin main

# Clear local plugin cache
rm -rf ~/.claude/plugins/cache

# Trigger plugin installation
claude /plugin list
```

### Problem: Plugin Conflicts
**Symptoms**: Multiple plugins with same agent/command names
**Cause**: Overlapping functionality from different plugins
**Solution**:
```bash
# List all agents to find conflicts
grep -r "name:" ~/.claude/plugins/*/agents/*.md

# Disable conflicting plugin
/plugin disable conflicting-plugin@marketplace

# Or use fully qualified agent name
@epcc-workflow/code-archaeologist
```

### Problem: Hook Performance Issues
**Symptoms**: Commits or file operations are very slow
**Cause**: Blocking hooks taking too long to execute
**Solution**:
```json
{
  "hooks": {
    "PreCommit": [
      {
        "type": "command",
        "command": "mypy . --ignore-missing-imports",
        "blocking": false,
        "description": "Type checking (non-blocking)"
      }
    ]
  }
}
```

**Strategy**: Convert slow hooks to non-blocking (warnings only) or optimize scripts.

## Alternative Approaches

### For Individual Contributors
If you're working solo and don't need team enforcement:

**Approach**: Install plugins globally for personal use
**Pros**:
- Available across all projects
- No project configuration needed
- Easy to experiment

**Cons**:
- Team members won't have same setup
- Manual updates required

**When to use**: Personal projects, exploration, learning

**How to implement**:
```bash
# Install to global Claude Code config
/plugin install epcc-workflow
# Plugins available in all projects
cd ~/any-project
@code-archaeologist  # Works everywhere
```

### For Large Organizations
For enterprise-scale deployments with hundreds of developers:

**Approach**: Central plugin configuration with organizational defaults
**Pros**:
- Consistent tooling across organization
- Centralized updates and security
- Audit and compliance tracking

**Cons**:
- Requires infrastructure setup
- Less flexibility for individual teams

**When to use**: Enterprise environments with security/compliance requirements

**How to implement**:
```bash
# Create organizational settings template
# .claude/org-defaults.json
{
  "requiredMarketplaces": [
    "aws-solutions-library-samples/guidance-for-claude-code-with-amazon-bedrock"
  ],
  "requiredPlugins": [
    "security@aws-claude-code-plugins",
    "testing@aws-claude-code-plugins",
    "deployment@aws-claude-code-plugins"
  ],
  "hooks": {
    "PreCommit": [
      {
        "type": "agent",
        "agent": "security-reviewer",
        "blocking": true,
        "args": "--strict --compliance"
      }
    ]
  }
}

# Distribute to teams via git template or CI/CD
git clone git@github.com:company/project-template.git
cd project-template
cp .claude/org-defaults.json my-new-project/.claude/settings.json
```

### For Plugin Development
If you need custom functionality not in marketplace:

**Approach**: Create custom plugins alongside marketplace plugins
**Pros**: Extend functionality for specific needs
**Cons**: Maintenance burden, need plugin development skills

**When to use**: Unique workflows or proprietary tools

**How to implement**:
```bash
# Use both marketplace and local plugins
# .claude/settings.json
{
  "requiredMarketplaces": [
    "aws-solutions-library-samples/guidance-for-claude-code-with-amazon-bedrock"
  ],
  "requiredPlugins": [
    "epcc-workflow@aws-claude-code-plugins",
    "security@aws-claude-code-plugins"
  ],
  "localPlugins": [
    ".claude/plugins/custom-workflow",
    ".claude/plugins/company-standards"
  ]
}
```

## Best Practices

**Plugin Selection**:
- Start with Starter Bundle, expand as needed
- Install only plugins you'll actively use
- Review plugin documentation before installing

**Configuration Management**:
- Commit `.claude/settings.json` to version control
- Document plugin choices in project README
- Use consistent configuration across team projects

**Security**:
- Always enable security plugin for production projects
- Review hook scripts before using them
- Keep plugins updated for security patches

**Performance**:
- Use non-blocking hooks for warnings
- Optimize hook scripts for speed
- Disable unused plugins rather than uninstalling

**Team Configuration**:
- **DO commit `.claude/settings.json`** to version control for consistency
- **DO use `requiredMarketplaces`** to specify plugin sources explicitly
- **DO document why plugins are required** (add `description` field explaining team standards)
- **DO keep the list focused** - Start with 3-7 essential plugins, expand as needed
- **DON'T require too many plugins** - Consider onboarding experience and performance
- **DON'T mix personal preferences with team requirements** - Use `requiredPlugins` for team standards only

**Example with documentation:**
```json
{
  "description": "Team standards: EPCC for consistency, security for compliance",
  "requiredMarketplaces": ["aws-solutions-library-samples/guidance-for-claude-code-with-amazon-bedrock"],
  "requiredPlugins": [
    "epcc-workflow@aws-claude-code-plugins",
    "security@aws-claude-code-plugins"
  ]
}
```

## Related Tasks

- [Getting Started with EPCC Workflow](../tutorials/getting-started-epcc-workflow.md) - Learn systematic development
- [Documentation Hub](../README.md) - Complete documentation index

## Further Reading

- **New to Claude Code?** Start with [Getting Started Guide](https://docs.claude.com/claude-code) →
- **Need plugin specifications?** Check [Plugin Reference](https://docs.claude.com/claude-code/plugins-reference) →
- **All plugin details**: See [Main README](../../README.md#available-plugins) →
- **More documentation**: Visit [Documentation Hub](../README.md) →
