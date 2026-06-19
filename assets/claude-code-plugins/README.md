> **Part of**: [Guidance for Claude Code with Amazon Bedrock](https://github.com/aws-solutions-library-samples/guidance-for-claude-code-with-amazon-bedrock)
> **Purpose**: This subdirectory contains example Claude Code plugins - completely independent of the authentication setup

# Claude Code Plugins Marketplace

Example agents, hooks, and workflows for Claude Code - a comprehensive plugin marketplace providing specialized tools for systematic development, documentation, architecture, security, and more.

## 🚀 Quick Start

```bash
# Add the marketplace
/plugin marketplace add aws-solutions-library-samples/guidance-for-claude-code-with-amazon-bedrock

# Install your first plugin (EPCC workflow recommended)
/plugin install epcc-workflow@aws-claude-code-plugins

# Browse all available plugins interactively
/plugin
```

## 📖 Documentation

**New to plugins?** Start with our hands-on tutorial:
- [Getting Started with EPCC Workflow](docs/tutorials/getting-started-epcc-workflow.md) - 25-minute tutorial for beginners

**Need to configure plugins?** Check our practical guides:
- [Plugin Configuration How-To](docs/how-to/configure-plugins.md) - Installation, team setup, and troubleshooting

**Want to explore all resources?** Visit the documentation hub:
- [Documentation Hub](docs/README.md) - Complete guide index with learning paths

## 📦 Available Plugins

### 🔄 epcc-workflow (Recommended First)
**EPCC (Explore-Plan-Code-Commit) systematic development workflow**

A comprehensive methodology for systematic software development with exploration and planning phases.

**Includes:**
- 12 specialized agents for exploration, planning, coding, and commit phases
- 4 workflow commands (/epcc-explore, /epcc-plan, /epcc-code, /epcc-commit)
- Auto-recovery hooks

**Install:** `/plugin install epcc-workflow@aws-claude-code-plugins`

**Use Case:** Teams needing systematic, methodical development approach

---

### 📚 documentation
**Complete Diataxis documentation framework**

Implements the full Diataxis documentation system with 12 specialized agents for tutorials, how-tos, references, explanations, and analysis.

**Includes:**
- 12 specialized agents for documentation and analysis
- 5 documentation commands
- Diataxis-compliant structure

**Install:** `/plugin install documentation@aws-claude-code-plugins`

**Use Case:** Projects requiring comprehensive, user-focused documentation

---

### 🏗️ architecture
**Architecture design, review, and documentation**

Complete toolkit for system architecture design, C4 diagrams, ADRs, and architecture reviews.

**Includes:**
- 10 specialized agents for architecture and quality analysis
- 3 commands (design, review, refactor)
- 3 automation hooks

**Install:** `/plugin install architecture@aws-claude-code-plugins`

**Use Case:** Architects and teams working on system design

---

### 🔒 security
**Security scanning and compliance automation**

Comprehensive security tooling with automated gates, vulnerability scanning, and compliance validation.

**Includes:**
- 4 specialized agents for security and analysis
- 2 commands (/security-scan, /permission-audit)
- Automated security gates and scripts

**Install:** `/plugin install security@aws-claude-code-plugins`

**Use Case:** Security-conscious teams, compliance requirements

---

### ✅ testing
**Testing, QA, and quality gates**

Complete testing infrastructure with automated quality gates, linting, and validation.

**Includes:**
- 3 specialized agents for testing and design
- Test generation command
- Quality gates with Python linting (Black, Ruff, mypy)

**Install:** `/plugin install testing@aws-claude-code-plugins`

**Use Case:** QA teams, TDD practitioners, quality-focused development

---

### ⚡ performance
**Performance profiling and optimization**

Tools for performance analysis, profiling, optimization, and continuous monitoring.

**Includes:**
- 5 specialized agents for performance analysis
- Performance analysis command
- Performance monitoring hooks

**Install:** `/plugin install performance@aws-claude-code-plugins`

**Use Case:** Performance-critical applications, optimization work

---

### 🧪 tdd-workflow
**Test-Driven Development workflow**

Specialized workflow for TDD with red-green-refactor cycle support.

**Includes:**
- 6 specialized agents for TDD and quality analysis
- 2 TDD commands (/tdd-feature, /tdd-bugfix)
- Test-first development patterns

**Install:** `/plugin install tdd-workflow@aws-claude-code-plugins`

**Use Case:** TDD practitioners, test-first development teams

---

### 📋 agile-tools
**Agile team roles and processes**

Complete set of agile role-based agents for team coordination and project management.

**Includes:**
- 4 agile role agents (Scrum Master, Product Owner, Business Analyst, Project Manager)
- Notification hooks

**Install:** `/plugin install agile-tools@aws-claude-code-plugins`

**Use Case:** Agile teams, product management, business analysis

---

### 🎨 ux-design
**UX optimization and UI design**

User experience and interface design tools with accessibility validation.

**Includes:**
- 2 design agents (UI designer, UX optimizer)
- WCAG accessibility support

**Install:** `/plugin install ux-design@aws-claude-code-plugins`

**Use Case:** Frontend teams, design-focused development

---

### 🚀 deployment
**Deployment orchestration and automation**

DevOps tools for deployment automation, progressive rollouts, and compliance.

**Includes:**
- Deployment agent
- Compliance hooks
- Progressive deployment strategies

**Install:** `/plugin install deployment@aws-claude-code-plugins`

**Use Case:** DevOps teams, CI/CD pipelines

---

### 🔍 code-analysis
**Code archaeology and tech evaluation**

Tools for analyzing legacy systems, evaluating technologies, and assessing technical debt.

**Includes:**
- 2 analysis agents (code archaeologist, tech evaluator)
- Legacy system analysis

**Install:** `/plugin install code-analysis@aws-claude-code-plugins`

**Use Case:** Legacy modernization, technology evaluation

---

## 🎯 Recommended Plugin Bundles

### Starter Bundle
Perfect for teams getting started with Claude Code:
```json
{
  "requiredMarketplaces": ["aws-solutions-library-samples/guidance-for-claude-code-with-amazon-bedrock"],
  "requiredPlugins": [
    "epcc-workflow",
    "documentation",
    "security"
  ]
}
```

### Full-Stack Bundle
Comprehensive tools for full-stack development:
```json
{
  "requiredPlugins": [
    "epcc-workflow",
    "documentation",
    "architecture",
    "testing",
    "ux-design"
  ]
}
```

### Enterprise Bundle
Complete enterprise development toolkit:
```json
{
  "requiredPlugins": [
    "epcc-workflow",
    "security",
    "testing",
    "performance",
    "architecture",
    "deployment",
    "agile-tools"
  ]
}
```

### TDD Bundle
Everything needed for test-driven development:
```json
{
  "requiredPlugins": [
    "tdd-workflow",
    "testing",
    "epcc-workflow"
  ]
}
```

## 🔧 Team Configuration

Add to your project's `.claude/settings.json`:

```json
{
  "requiredMarketplaces": [
    "aws-solutions-library-samples/guidance-for-claude-code-with-amazon-bedrock"
  ],
  "requiredPlugins": [
    "epcc-workflow",
    "security",
    "testing"
  ]
}
```

All team members will automatically have access to these plugins.

## 📂 Repository Structure

```
claude-code-plugins/
├── .claude-plugin/
│   └── marketplace.json       # Marketplace manifest
├── plugins/
│   ├── epcc-workflow/         # 11 specialized plugins
│   ├── documentation/
│   ├── architecture/
│   ├── security/
│   ├── testing/
│   ├── performance/
│   ├── tdd-workflow/
│   ├── agile-tools/
│   ├── ux-design/
│   ├── deployment/
│   └── code-analysis/
├── docs/                      # Comprehensive guides
└── README.md                  # This file
```

## 🎓 Learning Resources

### For Individuals
1. Start with `epcc-workflow` for systematic development
2. Add `documentation` for writing great docs
3. Include `security` for automated security checks

### For Teams
1. Configure required plugins in `.claude/settings.json`
2. Choose a bundle that matches your workflow
3. Customize per-project as needed

### For Enterprises
1. Deploy security and testing plugins organization-wide
2. Use EPCC workflow for consistency
3. Leverage agile-tools for project management

## 🤝 Contributing

Contributions are welcome! Please read our [Contributing Guide](CONTRIBUTING.md) for details.

## 📄 License

This project is licensed under MIT-0 - see the [LICENSE](LICENSE) file for details.

## 🔗 Links

- [Claude Code Documentation](https://docs.claude.com/claude-code)
- [Plugin Reference](https://docs.claude.com/claude-code/plugins-reference)
- [Marketplace Guide](https://docs.claude.com/claude-code/plugin-marketplaces)
- [Issue Tracker](https://github.com/aws-solutions-library-samples/guidance-for-claude-code-with-amazon-bedrock/issues)

## ⭐ Highlights

- **11 Example Plugins** - Reference implementations for modern development patterns
- **Advanced Metadata** - Rich discoverability with keywords, tags, and categories
- **Modular Design** - Install only what you need
- **Team-Friendly** - Enforce standards with required plugins
- **Well-Documented** - Complete guides and examples
- **Fork & Customize** - Designed as starting points for your organization's specific needs

---

**Get Started:** `/plugin marketplace add aws-solutions-library-samples/guidance-for-claude-code-with-amazon-bedrock`
