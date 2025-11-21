---
name: epcc-plan
description: Plan phase of EPCC workflow - strategic design before implementation
version: 2.1.0
argument-hint: "[feature-or-task-to-plan]"
---

# EPCC Plan Command

You are in the **PLAN** phase of the Explore-Plan-Code-Commit workflow. Transform exploration insights into actionable strategy through **collaborative planning**.

@../docs/EPCC_BEST_PRACTICES.md - Comprehensive guide covering clarification strategies, error handling planning, sub-agent delegation patterns, and interactive phase best practices

⚠️ **IMPORTANT**: This phase is for PLANNING ONLY. Do NOT write any implementation code. Focus exclusively on:
- Creating detailed plans
- Breaking down tasks
- Assessing risks
- Documenting everything in EPCC_PLAN.md

All implementation will happen in the CODE phase.

## Planning Target
$ARGUMENTS

---

## 🏗️ Phase Architecture

**Mechanism**: Slash command with direct injection (fast, interactive, user-controlled)

**See**: `../docs/EPCC_BEST_PRACTICES.md` → "Interactive Phase Best Practices" for architecture details and CLAUDE.md leverage patterns.

---

## 🎯 Planning Mode: Interactive & Collaborative

This command operates in **collaborative planning mode**, similar to Claude Code's native planning mode:

### Phase 1: Clarification & Requirements Gathering

**ALWAYS start by clarifying requirements**, even if the user provided a task description:

1. **Ask clarifying questions** if ANY of these are unclear:
   - What specific problem does this solve?
   - Who are the users/stakeholders?
   - What are the constraints (time, resources, technology)?
   - Are there existing systems to integrate with?
   - What's the priority/urgency?
   - What are acceptable trade-offs?

2. **Identify ambiguities** in the request:
   - Multiple valid approaches? Ask which direction to pursue
   - Unclear scope? Ask about boundaries and non-goals
   - Missing context? Request specific information
   - Technology choices? Ask about preferences or constraints

3. **Confirm understanding** before proceeding

**Example**:
```
User: "Plan user authentication feature"

You: "I'll help plan the authentication feature. Let me clarify a few things:

1. Authentication method - are you looking for:
   - Traditional email/password?
   - OAuth (Google, GitHub)?
   - Multi-factor authentication?

2. User management - do you need:
   - User registration?
   - Password reset?
   - Role-based access control?

3. Integration - should this work with:
   - Existing user database?
   - Third-party auth providers?

4. Scope - should I focus on:
   - Backend API only?
   - Full stack (backend + frontend)?

Please let me know your preferences."
```

## Clarification Strategy

This phase is **collaborative** - balancing technical decisions with user input. Focus on architecture and approach.

**See**: `../docs/EPCC_BEST_PRACTICES.md` → "Clarification Decision Framework" for complete guidance.

### PLAN Phase Guidelines

**Expected questions**: 6-15 (varies by complexity)

**✅ Ask when:**
- Multiple valid technical approaches (architecture, technology stack)
- Unclear technical constraints from EPCC_EXPLORE.md
- Ambiguous scope boundaries (what's in/out?)
- Trade-offs need decisions (complexity vs performance)
- User preferences unknown (which option?)

**❌ Don't ask when:**
- EPCC_EXPLORE.md already documents it (read first)
- PRD.md already clarified it (check requirements if available)
- It's an implementation detail (defer to CODE phase)
- You can document multiple options (present alternatives)

### Key Patterns

**Check exploration first**: Read EPCC_EXPLORE.md → use constraints found → ask about gaps

**Draft-driven**: Create draft with documented assumptions → present → iterate → finalize only after approval

**Technical decisions**: 2-4 clear options → use AskUserQuestion → avoid asking about code-level details

### Phase 2: Draft Plan Creation

Once requirements are clear:

1. **Create initial plan** using the planning framework below
2. **Present as DRAFT** for review
3. **Explicitly ask for feedback**: "Does this approach make sense? Any concerns or changes?"
4. **Iterate based on feedback** - refine until approved

### Phase 3: Plan Finalization

Only after user approval:

1. **Finalize the plan** in EPCC_PLAN.md
2. **Summarize next steps**: "Plan is ready. Run `/epcc-code` to begin implementation."

## 📋 Planning Objectives

1. **Define Clear Goals**: What exactly are we building?
2. **Design the Approach**: How will we build it?
3. **Break Down Work**: What are the specific tasks?
4. **Assess Risks**: What could go wrong?
5. **Set Success Criteria**: How do we know we're done?

## Extended Thinking Strategy

- **Simple features**: Standard task breakdown
- **Complex features**: Think about edge cases and interactions
- **System changes**: Think hard about ripple effects
- **Architecture decisions**: Ultrathink about long-term implications

## Parallel Planning Subagents (Optional)

For **very complex planning tasks**, you MAY deploy specialized planning agents **in parallel**.

**Launch simultaneously** (all in same response):

```
# ✅ GOOD: Parallel planning (agents analyze different aspects)
@system-designer Design high-level architecture for authentication feature.

Requirements from PRD.md (if available):
- JWT-based authentication
- User login/logout
- Token refresh mechanism
- Rate limiting on login attempts

Constraints from EPCC_EXPLORE.md:
- Existing framework: Express.js + TypeScript
- Database: PostgreSQL
- Current architecture: Layered (routes → services → repositories)

Design:
- Component structure and boundaries
- Service layer architecture
- Data flow diagrams
- Database schema for users/sessions
- API endpoint structure

Return: Architecture diagram, component descriptions, integration points.

@tech-evaluator Evaluate technology choices for authentication implementation.

Requirements:
- JWT library selection
- Password hashing library
- Rate limiting approach
- Session storage options

Compare options:
- JWT: jsonwebtoken vs jose
- Hashing: bcrypt vs argon2
- Rate limiting: express-rate-limit vs rate-limiter-flexible
- Sessions: Redis vs in-memory vs database

Evaluate: Performance, security, maintenance, community support, learning curve.
Return: Recommendation table with pros/cons and final choices.

@security-reviewer Assess security considerations for authentication feature.

Requirements:
- Secure password storage
- JWT token security
- Rate limiting effectiveness
- Session management security

Analyze risks:
- OWASP Top 10 relevance
- Common authentication vulnerabilities
- Token storage best practices
- Brute force prevention

Return: Security requirements checklist, threat model, mitigation strategies.

# All three analyze different planning aspects concurrently
```

**Available agents:**
@system-designer @tech-evaluator @business-analyst @security-reviewer @qa-engineer @project-manager

**Full agent reference**: See `../docs/EPCC_BEST_PRACTICES.md` → "Agent Capabilities Overview" for agents in other phases (CODE, EXPLORE, COMMIT).

**IMPORTANT**: Only use subagents for genuinely complex planning tasks. For straightforward features, handle planning directly in conversation.

## Project Type: Greenfield vs Brownfield

**Brownfield Projects** (existing codebase):
- EPCC_EXPLORE.md will exist (from `/epcc-explore`)
- Use exploration findings for patterns, constraints, and conventions
- Follow existing architectural patterns
- Reuse identified components

**Greenfield Projects** (new codebase):
- EPCC_EXPLORE.md may not exist (skipped exploration)
- Plan with more flexibility (no existing constraints)
- Define patterns from scratch or industry best practices
- Focus on PRD.md requirements (if available) or user-provided requirements

**Check for exploration findings:**
```bash
if [ -f "EPCC_EXPLORE.md" ]; then
    # Brownfield: Use exploration findings
    echo "Found exploration - planning with existing codebase context"
else
    # Greenfield: Plan from PRD only
    echo "No exploration found - planning greenfield implementation"
fi
```

## Planning Framework

**If EPCC_EXPLORE.md exists:** Use exploration findings as the foundation for your plan.
**If EPCC_EXPLORE.md doesn't exist:** Base your plan on PRD.md (if available) or user-provided requirements and industry best practices.

### Step 1: Define Objectives

```markdown
## Feature Objective

### What We're Building
[Clear, concise description]

### Why It's Needed
[Business value and user benefit]

### Success Criteria
- [ ] Criterion 1: Measurable outcome
- [ ] Criterion 2: Measurable outcome
- [ ] Criterion 3: Measurable outcome

### Non-Goals (What We're NOT Doing)
- Not implementing X (will be done later)
- Not changing Y (out of scope)
```

### Step 2: Design the Approach

```markdown
## Technical Approach

### High-Level Architecture
[Component diagram or description showing how pieces fit together]

### Design Decisions
| Decision | Option Chosen | Rationale |
|----------|--------------|-----------|
| Database | PostgreSQL | Need ACID compliance |
| Caching | Redis | Fast, supports our data types |
| Auth | JWT | Stateless, scalable |

### Data Flow
1. User initiates request
2. System validates input
3. Process business logic
4. Update database
5. Return response
```

### Step 3: Task Breakdown

Document tasks in the plan (will be added to TodoWrite during CODE phase):

```markdown
## Task Breakdown

### Phase 1: Foundation (6 hours)
1. **Database Schema** (2h)
   - Design user tables
   - Create migration scripts
   - Add indexes
   - Dependencies: None
   - Risk: Low

2. **Authentication Middleware** (3h)
   - Implement JWT validation
   - Add request interceptors
   - Error handling
   - Dependencies: Task 1
   - Risk: Medium

### Phase 2: Core Features (8 hours)
[Continue breakdown...]
```

### Step 4: Risk Assessment

```markdown
## Risk Matrix

| Risk | Probability | Impact | Mitigation Strategy |
|------|------------|--------|-------------------|
| Database migration fails | Low | High | Create rollback script, test in staging |
| API rate limits exceeded | Medium | Medium | Implement caching, request batching |
| Performance degradation | Low | High | Load testing, monitoring, optimization plan |
```

### Step 5: Test Strategy

```markdown
## Testing Plan

### Unit Tests
- [ ] Model validation tests
- [ ] Service logic tests
- [ ] Utility function tests
- Coverage target: 90%

### Integration Tests
- [ ] API endpoint tests
- [ ] Database interaction tests
- [ ] External service mock tests
- Coverage target: 80%

### End-to-End Tests
- [ ] User workflow tests
- [ ] Error scenario tests
- [ ] Performance tests
- Coverage target: Critical paths
```

### Step 6: Define Error Handling Strategy

**CRITICAL**: Plan agent-compatible error handling.

```markdown
## Error Handling Strategy

### Requirements (Agent-Observable Errors)

**All scripts/services MUST:**
- Exit code 0 (success) or 2 (error)
- Write errors to stderr (not stdout)
- Provide clear, actionable error messages

**Why**: Enables Claude Code, sub-agents, and automation to observe and respond to errors.

### Planning Checklist

- [ ] Error handling strategy defined for each component
- [ ] Exit codes specified (0=success, 2=error)
- [ ] Error message formats planned
- [ ] Test strategy includes error path validation

### From EXPLORE Phase

Check EPCC_EXPLORE.md for:
- Existing error handling patterns to follow
- Project-specific error conventions
- Patterns that need updating for agent compatibility

**See**: `../docs/EPCC_BEST_PRACTICES.md` → "Agent-Compatible Error Handling" for:
- Complete rationale and implementation patterns
- Language-specific examples (Python, Node.js, Go, Bash)
- Testing strategies for agent observability
- Integration guidance across EPCC phases
```

## Planning Deliverables

### Output File: EPCC_PLAN.md

Generate plan in `EPCC_PLAN.md` **ONLY AFTER USER APPROVAL**.

### Plan Structure

Include these sections with **actual plan details**:

```markdown
# Implementation Plan: [Feature Name]

## Overview
- **Objective**: [What we're building]
- **Timeline**: [Estimated duration]
- **Priority**: [High/Medium/Low]
- **Status**: Draft / Approved

## Approach
[Detailed technical approach]

## Task Breakdown
[Detailed task list with estimates, dependencies, risks]

## Dependencies
- External: [List external dependencies]
- Internal: [List internal dependencies]
- Blockers: [List any blockers]

## Risks & Mitigations
[Risk assessment table]

## Success Metrics
- Performance: [Metrics]
- Quality: [Metrics]
- User satisfaction: [Metrics]

## Testing Strategy
[Test plan summary]

## Technical Design
[API design, data models, database schema]

## Security Considerations
[Authentication, authorization, data validation, encryption methods]

## Rollout Plan
- Phase 1: [Description]
- Phase 2: [Description]
- Rollback procedure: [Description]
```

## Handling Ambiguity (CRITICAL)

**Before creating EPCC_PLAN.md, ensure clarity:**

### Multiple Valid Approaches?

Use AskUserQuestion tool to present options:

```
AskUserQuestion(
    questions=[{
        "question": "Which authentication approach should we use?",
        "header": "Auth method",
        "options": [
            {
                "label": "JWT tokens",
                "description": "Stateless, scalable, good for APIs"
            },
            {
                "label": "Session-based",
                "description": "Traditional, simpler, good for web apps"
            },
            {
                "label": "OAuth only",
                "description": "Delegate to third parties (Google, GitHub)"
            }
        ],
        "multiSelect": false
    }]
)
```

### Unclear Requirements?

Ask directly:

```
I need clarification on a few points before creating the plan:

1. **User registration**: Should users self-register, or will accounts be created by admins?
2. **Password requirements**: Any specific complexity requirements?
3. **Session duration**: How long should auth tokens remain valid?

Please let me know so I can create an accurate plan.
```

### Unknown Technical Constraints?

Investigate EPCC_EXPLORE.md first, then ask:

```
I've checked EPCC_EXPLORE.md and found:
- Existing database: PostgreSQL 14
- Current auth: None (new implementation)
- Framework: Express.js with TypeScript

Questions:
1. Can we add new dependencies (e.g., passport.js, bcrypt)?
2. Are there company security policies I should follow?
3. Should this integrate with any existing services?
```

## Planning Best Practices

### DO:
- ✅ **Ask questions FIRST** before planning
- ✅ **Present draft plans** for approval
- ✅ **Iterate based on feedback**
- ✅ Break tasks into < 4 hour chunks
- ✅ Include testing in every task
- ✅ Consider edge cases explicitly
- ✅ Document design decisions
- ✅ Plan for rollback

### DON'T:
- ❌ **Assume requirements** without clarification
- ❌ **Finalize plan** without user approval
- ❌ Skip risk assessment
- ❌ Underestimate complexity
- ❌ Ignore dependencies
- ❌ Plan without exploration
- ❌ Forget documentation tasks
- ❌ **Write implementation code**

## Planning Workflow

```
┌─────────────────────────────────────┐
│ 1. CLARIFY REQUIREMENTS             │
│    - Ask questions                  │
│    - Identify ambiguities           │
│    - Gather constraints             │
└──────────────┬──────────────────────┘
               ▼
┌─────────────────────────────────────┐
│ 2. CREATE DRAFT PLAN                │
│    - Define objectives              │
│    - Design approach                │
│    - Break down tasks               │
│    - Assess risks                   │
└──────────────┬──────────────────────┘
               ▼
┌─────────────────────────────────────┐
│ 3. PRESENT FOR REVIEW                │
│    - Show draft plan                │
│    - Ask for feedback               │
│    - Highlight key decisions        │
└──────────────┬──────────────────────┘
               ▼
┌─────────────────────────────────────┐
│ 4. ITERATE (if needed)              │
│    - Refine based on feedback       │
│    - Adjust approach                │
│    - Re-present changes             │
└──────────────┬──────────────────────┘
               ▼
┌─────────────────────────────────────┐
│ 5. FINALIZE PLAN                    │
│    - Write EPCC_PLAN.md             │
│    - Confirm next steps             │
│    - Ready for /epcc-code           │
└─────────────────────────────────────┘
```

## Planning Checklist

**Before presenting draft plan:**
- [ ] All requirements clarified
- [ ] Ambiguities resolved
- [ ] Technical constraints understood
- [ ] User preferences known

**Before finalizing EPCC_PLAN.md:**
- [ ] User approved the approach
- [ ] Objectives clearly defined
- [ ] Approach thoroughly designed
- [ ] Tasks broken down and estimated
- [ ] Dependencies identified
- [ ] Risks assessed and mitigated
- [ ] Test strategy defined
- [ ] Success criteria established
- [ ] Documentation planned
- [ ] Timeline realistic
- [ ] Resources available

## Usage Examples

```bash
# Basic planning (will prompt for clarification)
/epcc-plan "Plan user authentication feature"

# Complex feature (will ask detailed questions)
/epcc-plan "Plan payment processing system"

# Small feature (minimal clarification needed)
/epcc-plan "Add email validation to signup form"

# Architecture change (will ask about scope and approach)
/epcc-plan "Migrate from REST to GraphQL"
```

## Integration with Other Phases

### From EXPLORE:
- Use exploration findings from `EPCC_EXPLORE.md`
- Reference identified patterns from exploration
- Consider discovered constraints

### To CODE:
- Provide clear task list in `EPCC_PLAN.md`
- Define acceptance criteria in plan document
- Specify test requirements
- Run `/epcc-code` to begin implementation

### To COMMIT:
- Reference `EPCC_PLAN.md` in commit message
- Update documentation
- Include plan details in PR description

## Final Output

Upon **user approval**, generate `EPCC_PLAN.md` containing:
- Implementation overview and objectives
- Technical approach and architecture
- Complete task breakdown with estimates
- Risk assessment and mitigation strategies
- Testing strategy and success criteria
- Dependencies and timeline

Then confirm:
```markdown
✅ Plan finalized and saved to EPCC_PLAN.md

Next steps:
1. Review the plan if needed
2. Run `/epcc-code` to begin implementation
3. Tasks will be tracked using TodoWrite during CODE phase

Ready to proceed?
```

Remember: **A good plan is half the implementation, but collaboration makes it great!**

🚫 **DO NOT**: Write code, create files, implement features, fix bugs, or finalize plans without approval

✅ **DO**: Ask questions, clarify requirements, present drafts, iterate on feedback, collaborate with the user
