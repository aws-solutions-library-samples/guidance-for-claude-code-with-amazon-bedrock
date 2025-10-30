# Requirements Plugin

> **Product and Technical Requirements Gathering with Expert Technology Evaluation**

Systematic approach to capturing product vision and making informed technical decisions through conversational discovery and expert guidance.

## Overview

The Requirements Plugin provides two complementary slash commands for comprehensive requirements gathering:

1. **`/prd`** - Product Requirements Discovery
   Conversational workflow to create Product Requirement Documents (PRD) through guided questions about vision, features, users, and constraints.

2. **`/tech-req`** - Technical Requirements Gathering
   Expert technology evaluation with detailed pros/cons analysis for frameworks, databases, cloud providers, and architecture patterns.

## Quick Start

### Installation

```bash
# Install from marketplace
/plugin install requirements@aws-claude-code-plugins
```

### Basic Usage

**Step 1: Gather Product Requirements** (Hybrid Interactive + Questionnaire)
```bash
/prd "build a team collaboration tool"
```

This starts with 3-5 foundational questions, then generates a questionnaire file (`PRD_QUESTIONS.md`) for you to complete at your own pace. Run `/prd --process PRD_QUESTIONS.md` to generate final `PRD.md`.

**Step 2: Evaluate Technical Options** (Hybrid Interactive + Questionnaire)
```bash
/tech-req
```

This starts with 2-3 critical questions (architecture, cloud, framework), then generates a questionnaire file (`TECH_REQ_QUESTIONS.md`) for detailed decisions. Run `/tech-req --process TECH_REQ_QUESTIONS.md` to generate final `TECH_REQ.md`.

**Step 3: Implement** (Optional EPCC Integration)
```bash
# Direct implementation
# OR use EPCC workflow
/epcc-explore  # Analyze existing systems
/epcc-plan     # Create implementation plan
/epcc-code     # Build the feature
```

## Commands

### `/prd` - Product Requirements Discovery (v2.0 - Hybrid Workflow)

**Purpose**: Create comprehensive Product Requirement Documents through focused questions + guided questionnaire.

**Usage**:
```bash
/prd [initial-idea-or-project-name]

# After completing questionnaire:
/prd --process PRD_QUESTIONS.md
```

**Hybrid Workflow** (NEW in v2.0):
1. **Interactive Phase** (5-10 min): Asks 3-5 foundational questions (vision, problem, users, success)
2. **Questionnaire Generation**: Creates `PRD_QUESTIONS.md` with detailed requirements
3. **Self-Paced Completion** (15-20 min): You answer questions at your own pace (features, constraints, scope, metrics)
4. **Processing**: Run `/prd --process PRD_QUESTIONS.md` to generate final `PRD.md`

**What it does**:
- **Interactive foundation**: Critical understanding through conversational questions
- **Self-paced details**: Detailed planning in questionnaire file you can complete anytime
- **Smart filtering**: Shows only relevant questions based on your project type
- **No information overload**: Never asks 10+ questions at once
- **Strictly non-technical**: Focuses on what/why/who (technical HOW happens in `/tech-req`)

**Example**:
```bash
/prd "e-commerce platform for artisans"
# Answer 3-5 foundational questions interactively
# Open PRD_QUESTIONS.md and fill in detailed requirements
# Run: /prd --process PRD_QUESTIONS.md
```

**Output**: `PRD.md` containing:
- Executive summary and vision statement
- Problem statement and target users
- Prioritized features (P0/P1/P2)
- User journeys
- Technical constraints (deployment, scale, team comfort)
- Timeline, budget, and success criteria
- Out-of-scope items and risks

**Duration**: 20-30 minutes total (5-10 min interactive + 15-20 min questionnaire)

---

### `/tech-req` - Technical Requirements Gathering (v2.0 - Hybrid Workflow)

**Purpose**: Evaluate technology choices through focused interactive questions + self-paced questionnaire.

**Usage**:
```bash
/tech-req [existing-prd-file-or-project-name]

# After completing questionnaire:
/tech-req --process TECH_REQ_QUESTIONS.md
```

**Hybrid Workflow** (NEW in v2.0):
1. **Interactive Phase** (5 min): Asks 2-3 critical questions (architecture, cloud, framework category)
2. **Questionnaire Generation**: Creates `TECH_REQ_QUESTIONS.md` with remaining questions
3. **Self-Paced Completion** (10-15 min): You answer questions at your own pace
4. **Processing**: Run `/tech-req --process TECH_REQ_QUESTIONS.md` to generate final `TECH_REQ.md`

**What it does**:
- **Smart Filtering**: Shows only 2-3 most relevant options per decision (based on PRD constraints)
- **Sequential Decisions**: Later questions adapt based on earlier answers
- **No Information Overload**: Never presents 4+ options simultaneously
- Evaluates architecture, cloud, frameworks, styling, infrastructure, databases
- Generates comprehensive `TECH_REQ.md` with technology decision matrix

**Example**:
```bash
/tech-req PRD.md
# Interactive: Architecture? Cloud? Framework?
# Generates: TECH_REQ_QUESTIONS.md
# [You fill out questionnaire at your own pace]
/tech-req --process TECH_REQ_QUESTIONS.md
# Generates: TECH_REQ.md
```

**Output**:
- `TECH_REQ_QUESTIONS.md` - Questionnaire with filtered options
- `TECH_REQ.md` - Complete technical specification containing:
  - Architecture decision with rationale
  - Technology stack with alternatives considered
  - Infrastructure and deployment strategy
  - Cost estimation and implementation roadmap
  - Technology decision summary table

**Duration**: ~15-20 minutes total (5 min interactive + 10-15 min questionnaire)

## Features

### 🎯 Conversational Requirements Discovery

- **Socratic Method**: Asks questions rather than making assumptions
- **Options with Tradeoffs**: Presents choices with clear pros/cons
- **Iterative Refinement**: Checkpoints to confirm understanding
- **No Prescriptive Advice**: Guides you to make informed decisions

### 🔬 Expert Technology Evaluation

- **Detailed Pros/Cons**: For every technology option (React, Vue, Angular, Node, Python, Go, PostgreSQL, MongoDB, etc.)
- **Total Cost of Ownership**: Infrastructure costs, learning curve, maintenance overhead
- **Team Reality Check**: Matches technology to team skills and experience
- **Real-World Examples**: Case studies and benchmarks

### 📊 Comprehensive Documentation

- **PRD.md**: Complete product specification
- **TECH_REQ.md**: Technical decisions with rationale
- **Decision Matrix**: Summary of all technology choices
- **Alternatives Documented**: What was considered and why not chosen

### 🔄 Optional EPCC Integration

- **Standalone**: Use `/prd` and `/tech-req` independently
- **EPCC Compatible**: Seamlessly feeds into `/epcc-explore` → `/epcc-plan` → `/epcc-code` workflow
- **No Lock-in**: Works with or without EPCC workflow plugin

## Use Cases

### New Project Kickoff
```bash
/prd "build internal knowledge management system"
# ... conversational discovery ...
# PRD.md generated

/tech-req PRD.md
# ... technology evaluation ...
# TECH_REQ.md generated

/epcc-explore  # Optional: Begin EPCC workflow
```

### Technology Decision for Existing Project
```bash
/tech-req "choosing between React and Vue for dashboard"
# Detailed comparison with recommendations
# TECH_REQ.md generated with decision matrix
```

### Architecture Evaluation
```bash
/tech-req "evaluating microservices vs monolith for e-commerce platform"
# Architecture patterns compared
# Pros/cons for each approach
# Recommendation based on team size, scale, complexity
```

### Requirements Refinement
```bash
/prd "refining requirements for mobile app MVP"
# Helps prioritize features (P0/P1/P2)
# Defines minimum viable product
# Updated PRD.md
```

## Documentation

Comprehensive documentation following the Diataxis framework:

### 📘 Tutorials (Learning-Oriented)
- [Requirements Gathering Workflow](docs/tutorials/requirements-gathering-workflow.md) - 20 min hands-on tutorial

### 📗 How-To Guides (Task-Oriented)
- [Evaluate Technology Choices](docs/how-to/evaluate-technology-choices.md) - Quick technology evaluation

### 📙 Explanation (Understanding-Oriented)
- [Requirements Discovery Methodology](docs/explanation/requirements-discovery-methodology.md) - Why separate PRD and Technical Requirements

### 📕 Reference
- This README serves as quick reference

## Agents

The Requirements Plugin leverages two specialized agents:

### `@business-analyst`
- **Purpose**: Assists with business requirements and product vision
- **When Used**: During `/prd` command for product discovery
- **Capabilities**: User research, feature prioritization, success metrics

### `@tech-evaluator`
- **Purpose**: Provides technology evaluation and recommendations
- **When Used**: During `/tech-req` command for technical decisions
- **Capabilities**: Technology comparison, pros/cons analysis, cost-benefit analysis, risk assessment

## Workflow Integration

### Standalone Workflow
```
/prd → /tech-req → Implementation
```

### Integrated with EPCC Workflow
```
/prd → /tech-req → /epcc-explore → /epcc-plan → /epcc-code → /epcc-commit
```

### Agile Integration
```
Sprint Planning: /prd for new features
Tech Spike: /tech-req for technology decisions
Implementation: Direct coding or EPCC workflow
```

## Best Practices

### Product Requirements (`/prd`)
- ✅ **Start broad, then narrow**: Begin with vision, drill into specifics
- ✅ **Prioritize ruthlessly**: Focus on P0 (must-have) features for MVP
- ✅ **Define success metrics**: Quantifiable targets, not vague goals
- ✅ **Document constraints**: Budget, timeline, team capabilities
- ❌ **Don't solution too early**: Focus on problems and users, not implementation

### Technical Requirements (`/tech-req`)
- ✅ **Consider total cost of ownership**: Development + operations + maintenance
- ✅ **Match team skills**: Don't choose tech your team can't support
- ✅ **Start simple, scale later**: Monolith before microservices, SQL before NoSQL (unless specific needs)
- ✅ **Document alternatives**: Record what was considered and why not chosen
- ❌ **Don't chase hype**: Evaluate based on needs, not trends

## Examples

### Example 1: Web Application

**Input**:
```bash
/prd "building a SaaS platform for project management"
```

**Conversational Flow**:
- Vision: Streamline project tracking for small teams
- Users: Project managers, team members, clients
- Features: Task management (P0), time tracking (P1), reporting (P1), integrations (P2)
- Constraints: 6-month timeline, $500/month infrastructure budget, 3-person team

**Output**: `PRD.md` with complete specification

**Next Step**:
```bash
/tech-req PRD.md
```

**Technology Evaluation**:
- Frontend: React (team has experience, large ecosystem)
- Backend: Node.js (same language as frontend, real-time needs)
- Database: PostgreSQL (complex relationships, ACID transactions)
- Hosting: AWS (mature, wide service selection)
- Auth: Auth0 (managed solution, don't build auth yourself)

**Output**: `TECH_REQ.md` with decision matrix

### Example 2: API Service

**Input**:
```bash
/tech-req "choosing database for high-throughput API (10k req/sec)"
```

**Technology Evaluation**:

**Context**: High read throughput, simple key-value lookups, auto-scaling needed

**Options**:
1. **PostgreSQL**: Great for complex queries, but may need read replicas at 10k req/sec
2. **DynamoDB**: Built for scale, auto-scaling, pay-per-request, perfect for key-value
3. **Redis**: Extremely fast, but requires data persistence strategy

**Recommendation**: DynamoDB
- Handles 10k+ req/sec without tuning
- Auto-scaling eliminates capacity planning
- Cost-effective for read-heavy workloads (~$100/month at 10k req/sec)
- Fully managed (zero ops)

**Output**: `TECH_REQ.md` with detailed analysis

## Troubleshooting

### Issue: "Too many questions, I just want a quick PRD"

**Solution**: Provide more context upfront:
```bash
/prd "build e-commerce site for 1k users, 6-month timeline, React frontend, Node backend, AWS hosting, MVP with product catalog and checkout"
```

The more context you provide, the fewer clarifying questions needed.

### Issue: "Technology recommendations don't match my constraints"

**Solution**: Be explicit about constraints in `/tech-req`:
```bash
/tech-req "evaluate frontend framework for team with no React experience, 3-month learning budget, building data dashboard"
```

The agent will recommend based on learning curve, not just popularity.

### Issue: "PRD is too detailed for my simple project"

**Solution**: Skip sections that don't apply. For simple projects:
- Focus on P0 features only
- Minimal technical approach
- Simple success criteria

Or use `/tech-req` directly without PRD for technology decisions only.

## Version History

- **v1.0.0** (2025-01-21): Initial release
  - `/prd` command for product requirements discovery
  - `/tech-req` command for technical requirements evaluation
  - Standalone plugin architecture
  - Optional EPCC workflow integration

## Contributing

See [CONTRIBUTING.md](../../CONTRIBUTING.md) for guidelines on how to contribute to this plugin.

## License

MIT-0 - See [LICENSE](../../LICENSE) for details.

## Support

- **Issues**: [GitHub Issues](https://github.com/aws-samples/guidance-for-claude-code-with-amazon-bedrock/issues)
- **Discussions**: [GitHub Discussions](https://github.com/aws-samples/guidance-for-claude-code-with-amazon-bedrock/discussions)
- **Documentation**: [Full Documentation](../../docs/)

## Related Plugins

- **epcc-workflow**: Explore → Plan → Code → Commit systematic development workflow
- **troubleshooting**: Systematic debugging when things go wrong
- **documentation**: Generate comprehensive documentation after implementation
