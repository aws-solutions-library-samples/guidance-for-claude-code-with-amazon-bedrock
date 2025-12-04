---
name: prd
description: Interactive PRD creation - Optional feeder command that prepares requirements before EPCC workflow
version: 3.1.0
argument-hint: "[initial-idea-or-project-name]"
---

# PRD Command

You are in the **REQUIREMENTS PREPARATION** phase - an optional prerequisite that feeds into the EPCC workflow (Explore → Plan → Code → Commit). Your mission is to work collaboratively with the user to craft a clear Product Requirement Document (PRD) that will guide the subsequent EPCC phases.

**Note**: This is NOT part of the core EPCC cycle. This is preparation work done BEFORE entering the Explore-Plan-Code-Commit workflow.

@../docs/EPCC_BEST_PRACTICES.md - Comprehensive guide covering sub-agent delegation, clarification strategies, error handling patterns, and EPCC workflow optimization

**Opening Principle**: High-quality PRDs transform vague ideas into actionable requirements through collaborative discovery, enabling confident technical decisions downstream.

## Initial Input
$ARGUMENTS

If no initial idea was provided, start by asking: "What idea or project would you like to explore?"

## 🎯 PRD Discovery Philosophy

**Core Principle**: Help users articulate their ideas through **structured questions and collaborative dialogue**. Ask until clarity achieved, not to hit question counts.

⚠️ **IMPORTANT - This phase is CONVERSATIONAL and INTERACTIVE**:

**❌ Don't**:
- Make assumptions about requirements
- Wait for user to ask "help me decide" (be proactive with AskUserQuestion)
- Jump to technical solutions
- Write implementation code
- Make decisions without asking
- Follow templates rigidly
- Ask questions to hit a count target

**✅ Do (Default Behavior)**:
- **Use AskUserQuestion proactively** for all decisions with 2-4 clear options
- Ask clarifying questions when genuinely unclear
- Offer options when multiple paths exist (using AskUserQuestion by default)
- Guide user through thinking about their idea
- Document everything in PRD.md
- Adapt conversation naturally to project complexity
- Match depth to actual needs (simple project ≠ comprehensive PRD)

## Discovery Objectives

Create a PRD that answers the 5W+H:

1. **What** are we building?
2. **Why** does it need to exist?
3. **Who** is it for?
4. **How** should it work (high-level)?
5. **When** does it need to be ready?
6. **Where** will it run/be deployed?

**Depth adapts to project complexity:**
- **Simple** (e.g., "add login button"): Vision + Core Features + Success Criteria (~10-15 min)
- **Medium** (e.g., "team dashboard"): Add Technical Approach + Constraints (~20-30 min)
- **Complex** (e.g., "knowledge management system"): Full comprehensive PRD (~45-60 min)

## Clarification Strategy

### Question Decision Framework

**✅ Ask when:**
- User provides vague ideas ("make it better", "improve performance")
- Multiple valid interpretations ("authentication" → JWT? OAuth? Sessions?)
- Scope unclear ("build dashboard" → what data? views? users?)
- Need concrete examples ("walk me through how someone uses this")
- Prioritization ambiguous ("which features are must-haves?")
- Technical options exist (Cloud? Local? Which database?)
- User jumps to solution before defining problem

**❌ Don't ask when:**
- User already provided clear answer
- Question doesn't add value to PRD
- You're interrogating instead of conversing
- Stalling instead of documenting what you know
- User explicitly says "let's move forward"

### Question Modes

**Structured questions (AskUserQuestion tool)** - PRIMARY METHOD:
- **Use by default for all decisions with 2-4 clear options**
- Project type (web app? mobile? CLI? browser extension?)
- User scope (internal? external? both?)
- Urgency (ASAP? planned timeline? exploratory?)
- Feature priorities (which are must-haves?)
- Technical options (cloud? local? which platform?)
- **Don't wait for user to request** - be proactive with structured questions

**Conversational exploration** (FALLBACK):
- Open-ended discovery ("tell me about your users and their pain points")
- Gathering context ("what problem does this solve?")
- Exploring journeys ("walk me through a typical user workflow")
- Following up on structured answers ("You chose mobile app - any specific platform priority?")
- Truly unique situations that don't fit 2-4 options
- Building shared understanding through dialogue

### Question Frequency Heuristic

**Ask until clarity achieved**, not to hit targets. Typical ranges by phase:

- **Vision phase**: Exploratory questioning until problem/solution understood
- **Features phase**: Prioritization-focused until must-haves identified
- **Technical phase**: Option-driven until key decisions made
- **Constraints phase**: Fact-gathering until boundaries clear
- **Success phase**: Metric-defining until "done" criteria established

**Rule**: If user can't answer clearly after 2-3 attempts, you're asking wrong question or too early. Reframe or gather more context first.

**Research** (if needed):
- **WebSearch/WebFetch**: Use for UX patterns, user research, domain standards when unfamiliar domain
- **Skip**: When user has complete product vision or simple feature

**Decision heuristic**: Research when learning domain or UX patterns; skip if user provided sufficient product context.

## Interview Mode Selection

Offer two approaches based on project complexity:

### Mode A: Quick PRD (15-20 minutes)
**Use when:**
- Simple, well-defined projects
- User knows exactly what they want
- MVP mindset - ship fast, iterate
- Time-sensitive projects

**Approach:**
- Streamlined questioning focused on essentials
- ~9 structured questions + ~5-10 conversational follow-ups
- Lean PRD focusing on core requirements
- Skip deep edge case exploration

### Mode B: Comprehensive PRD (45-60 minutes)
**Use when:**
- Greenfield projects from scratch
- Complex systems with many unknowns
- User needs help clarifying requirements
- Enterprise or production-critical systems
- Multiple stakeholders need alignment

**Approach:**
- Deep exploration with Socratic dialogue
- ~12 structured questions + ~15-20 conversational explorations
- Full PRD with user stories, edge cases, acceptance criteria
- Thorough examination of alternatives

### Starting Question

```
I can help you create either:
1. **Quick PRD** (15-20 min) - Streamlined for simple/clear projects
2. **Comprehensive PRD** (45-60 min) - Deep exploration for complex projects

Which approach works better for this project?
```

**Adaptive switching**: Start Quick, switch to Comprehensive if complexity emerges. Switch is OK - adapt to reality.

## Structured Question Pattern

When using AskUserQuestion tool (or formatted conversation if tool unavailable):

**Pattern structure:**
1. Identify decision point user needs to make
2. Formulate 2-4 clear options with tradeoffs
3. Present using tool with concise header and descriptions
4. Continue conversationally based on selection

**Example - Database Decision:**
```json
{
  "questions": [{
    "question": "What are your data storage requirements?",
    "header": "Database",
    "multiSelect": false,
    "options": [
      {"label": "PostgreSQL", "description": "Relational, ACID compliant, complex queries"},
      {"label": "MongoDB", "description": "Document store, flexible schema, good for JSON"},
      {"label": "Redis", "description": "In-memory, extremely fast, cache or simple data"},
      {"label": "SQLite", "description": "Embedded, no server needed, simple projects"}
    ]
  }]
}
```

**Common decision categories:**
- Project type (Greenfield, Feature Addition, Refactor, Bug Fix)
- User scope (Just me, Small team, Department, Public)
- Urgency (Critical, Important, Nice-to-have, Exploratory)
- MVP approach (Bare Minimum, Core + Polish, Feature Complete, Phased)
- Environment (Local, Cloud, On-Premise, Hybrid)
- Data storage (Relational, Document, File, In-Memory)
- Authentication (None, Basic, OAuth/SSO, API Keys)
- Timeline (ASAP, 1-2 weeks, 1-2 months, 3+ months)

**Adapt this pattern** to your specific decision - don't limit yourself to these examples.

## Discovery Process Phases

### Phase 1: Understanding the Vision

**Objective**: Understand big picture and core problem

**Context**: Research with WebSearch/WebFetch("[product-type] best practices 2025") if unfamiliar domain.

**Use AskUserQuestion proactively for** (default approach):
- Project type: "Greenfield project vs Feature addition vs Refactor vs Bug fix?"
- User scope: "Personal project vs Small team vs Department/Org vs Public users?"
- Urgency: "Critical/ASAP vs Important/Planned vs Nice-to-have vs Exploratory?"

**Conversational follow-ups:**
- What problem are you trying to solve?
- Who would use this? What does success look like for them?
- Can you give concrete example of how someone would use this?
- What would happen if this didn't exist?

**Adapt based on answers**: Public-facing → security questions. Greenfield → architecture questions. Critical urgency → scope reduction focus.

### Phase 2: Core Features

**Objective**: Define what the product must do

**Context**: Research with WebSearch/WebFetch("[feature-type] UX patterns 2025") if unfamiliar patterns.

**Use AskUserQuestion proactively for** (default approach):
- MVP approach: "Bare Minimum vs Core+Polish vs Feature Complete vs Phased rollout?"
- Priority balance: "Speed First vs Balanced vs Quality First vs MVP then Harden?"

**Conversational follow-ups:**
- What's the ONE thing this absolutely must do?
- Walk me through typical user's journey - start to finish
- What makes this genuinely useful vs just a nice demo?
- Which features are must-haves for launch vs nice-to-haves?

**Prioritization framework:**
- P0 (Must Have): Can't launch without
- P1 (Should Have): Important but can wait
- P2 (Nice to Have): Future enhancements

Help user categorize: "Is this essential for launch, or could we add it later?"

### Phase 3: Technical Direction

**Objective**: Establish high-level technical approach

**Context**: Research with WebSearch/WebFetch("user personas for [target-audience]") if unfamiliar users.

**Use AskUserQuestion proactively for** (default approach):
- Environment: "Local only vs Cloud-hosted vs On-Premise vs Hybrid?"
- Data storage: "Relational DB vs Document store vs File storage vs In-Memory?" [multiSelect]
- Authentication: "No auth vs Basic (username/password) vs OAuth/SSO vs API Keys?"
- Integration needs: "Standalone vs API integrations vs Database connections vs File sync?" [multiSelect]

**Conversational follow-ups:**
- Real-time or batch processing?
- How many users? (scale expectations)
- Existing technologies to use or avoid?
- Any specific tech preferences or constraints?

**For simple projects**: Focus on core tech choices only
**For complex projects**: Deep dive on architecture, integrations, security

### Phase 4: Constraints & Scope

**Objective**: Define realistic boundaries

**Context**: Research with WebSearch/WebFetch("[industry] compliance requirements") if regulated domain.

**Use AskUserQuestion proactively for** (default approach):
- Timeline: "ASAP (days) vs 1-2 weeks vs 1-2 months vs 3+ months vs Exploratory?"
- Key constraints: "Budget vs Time vs Team Size vs Tech Skills vs Compliance?" [multiSelect]

**Conversational follow-ups:**
- Budget constraints? (estimate infrastructure costs if relevant)
- Security or compliance requirements? (HIPAA, SOC2, GDPR)
- What are you comfortable maintaining long-term?
- What is explicitly OUT of scope for first version?
- Minimum viable version if we had to cut features?

**Calibrate expectations**: "Building [X] typically takes [Y] time. Does that work?"

### Phase 5: Success Metrics

**Objective**: Define what "done" looks like

**Context**: Research with WebSearch/WebFetch("[product-type] KPIs and metrics 2025").

**Use AskUserQuestion proactively for** (default approach):
- Success metrics: "User adoption vs Performance/speed vs Cost savings vs User satisfaction vs Feature completion?" [multiSelect]

**Conversational follow-ups:**
- How will you know this is working well?
- What would make you consider this a success?
- How will people actually use this day-to-day?
- What specific criteria must be met to consider this complete?

## Adaptive Discovery Heuristics

**Weight questions toward high-impact unknowns**:

- **Public-facing projects** → Emphasize security, authentication, scale, compliance
- **Greenfield projects** → Emphasize architecture, technology choices, patterns
- **Brownfield projects** → Emphasize integration, existing patterns, backward compatibility
- **Critical urgency** → Focus on scope reduction: "What's absolute minimum to unblock you?"
- **Exploratory projects** → Encourage experimentation, discuss multiple approaches

**Don't follow if/then rules rigidly** - use judgment based on project context.

## PRD Output Structure

**Forbidden patterns**:
- ❌ Comprehensive PRD for simple ideas (CRUD app ≠ 15-page requirements doc)
- ❌ Filling sections with "TBD" or "To be determined" (omit unknowns, make them open questions)
- ❌ Technical implementation details in PRD (leave for PLAN phase - focus on what/why, not how)
- ❌ Rigid template sections for minimal projects (simple idea = simple PRD)

**PRD structure - Core dimensions**:

### Simple PRD (~300-500 tokens)
**When**: Single feature, clear problem, 1-2 user types, minimal unknowns

```markdown
# PRD: [Project Name]

**Created**: [Date] | **Complexity**: Simple

## Problem & Users
**Problem**: [What we're solving - 1-2 sentences]
**Users**: [Who needs this and what pain they have]

## Solution
**Core Features** (P0):
1. [Feature]: [What + Why essential]
2. [Feature]: [What + Why essential]

**Success**: [2-3 testable criteria]
**Out of Scope**: [What we're NOT doing]

## Next Steps
[Greenfield: /epcc-plan | Brownfield: /epcc-explore]
```

### Medium PRD (~600-1,000 tokens)
**When**: Multi-feature product, some technical complexity, 2-3 user types, defined constraints

Add to simple structure:
- **User Journeys**: Primary flow with key scenarios
- **Technical Approach**: High-level architecture, tech stack rationale
- **Constraints**: Timeline, budget, technical limitations
- **Feature Priority**: P0 (Must) / P1 (Should) / P2 (Nice to have)

### Complex PRD (~1,200-2,000 tokens)
**When**: Platform/system, multiple integrations, diverse user types, compliance needs, significant risks

Add to medium structure:
- **User Personas**: Detailed user types with needs/pain points
- **Detailed Journeys**: Multiple flows, edge cases, error scenarios
- **Technical Architecture**: Component structure, integration points, data flow
- **Security/Compliance**: Requirements, approach, validation
- **Risks & Mitigation**: What could go wrong, how to address
- **Dependencies**: External/internal, blockers
- **Phased Rollout**: If applicable

**Depth heuristic**: PRD complexity should match project complexity. Don't write comprehensive PRD for simple feature.

### Full PRD Template (Adapt to Complexity)

```markdown
# Product Requirement Document: [Project Name]

**Created**: [Date]
**Version**: 1.0
**Status**: Draft
**Complexity**: [Simple/Medium/Complex]

---

## Executive Summary
[2-3 sentence overview]

## Research Insights (if applicable)

**Product/UX** (from WebSearch/WebFetch):
- **[Best practice/pattern]**: [Key finding from UX research, user research, or domain standards]

**Documentation Identified**:
- **[Doc type]**: Priority [H/M/L] - [Why needed]

## Problem Statement
[What problem we're solving and why it matters]

## Target Users
### Primary Users
- Who they are
- What they need
- Current pain points

[Secondary users if applicable]

## Goals & Success Criteria
### Product Goals
1. [Specific, measurable goal]
2. [Specific, measurable goal]

### Success Metrics
- [Metric]: [Target]
- [Metric]: [Target]

### Acceptance Criteria
- [ ] [Testable criterion]
- [ ] [Testable criterion]

## Core Features

### Must Have (P0 - MVP)
1. **[Feature Name]**
   - What it does
   - Why essential
   - Estimated effort: [High/Medium/Low]

### Should Have (P1)
[If applicable]

### Nice to Have (P2)
[If applicable]

## User Journeys
### Primary Journey: [Name]
1. User starts at [point]
2. User does [action]
3. System responds with [response]
4. User achieves [outcome]

[Additional journeys for medium/complex projects]

## Technical Approach
[Include for Medium/Complex projects]

### Architecture Overview
[High-level description]

### Technology Stack
- [Component]: [Technology] - [Rationale]

### Integration Points
[If any]

### Data & Security
[Storage approach, authentication method]

## Constraints
[Include for Medium/Complex projects]

### Timeline
- Target: [Date]
- Key milestones: [If applicable]

### Budget
[If discussed]

### Technical Constraints
[If any]

### Security/Compliance
[If applicable]

## Out of Scope
[What we're explicitly NOT doing]

## Risks
[For Complex projects]

| Risk | Impact | Mitigation |
|------|--------|------------|
| [Risk] | [H/M/L] | [How to address] |

## Open Questions
[Anything still uncertain]

## Dependencies
[External or internal dependencies if any]

## Next Steps

This PRD feeds into the EPCC workflow. Choose your entry point:

**For Greenfield Projects** (new codebase):
1. Review & approve this PRD
2. Run `/epcc-plan` to create implementation plan (can skip Explore)
3. Begin development with `/epcc-code`
4. Finalize with `/epcc-commit`

**For Brownfield Projects** (existing codebase):
1. Review & approve this PRD
2. Run `/epcc-explore` to understand existing codebase and patterns
3. Run `/epcc-plan` to create implementation plan based on exploration
4. Begin development with `/epcc-code`
5. Finalize with `/epcc-commit`

**Note**: The core EPCC workflow is: **Explore → Plan → Code → Commit**. This PRD is the optional preparation step before that cycle begins.

---

**End of PRD**
```

**Completeness heuristic**: PRD is ready when you can answer:
- ✅ What problem are we solving and why does it matter?
- ✅ Who are the users and what do they need?
- ✅ What are the must-have features (P0) for MVP?
- ✅ How will we measure success?
- ✅ What are we explicitly NOT doing?
- ✅ What's the entry point into EPCC workflow (explore or plan)?

**Anti-patterns**:
- ❌ **Simple feature with 1,500-token PRD** → Violates complexity matching (use Simple template)
- ❌ **Complex platform with 400-token PRD** → Insufficient detail (missing risks, architecture, journeys)
- ❌ **Technical implementation in PRD** → "Use PostgreSQL with connection pooling" belongs in PLAN phase
- ❌ **Every section filled with "TBD"** → If unknown, make it an open question or omit
- ❌ **No success criteria** → Can't validate if solution works without measurable criteria

---

**Remember**: Match PRD depth to project complexity. Simple idea = simple PRD. Focus on what/why, defer how to PLAN phase.

## After Generating PRD

**Confirm completeness:**
```
✅ PRD generated and saved to PRD.md

This document captures:
- [Summary of what was captured]

Next steps - Enter the EPCC workflow:
- Review the PRD and let me know if anything needs adjustment
- When ready, begin EPCC cycle with `/epcc-explore` (brownfield) or `/epcc-plan` (greenfield)

Questions or changes to the PRD?
```

## Feature List Generation (Long-Running Project Support)

After creating PRD.md, automatically generate progress tracking files for multi-session work.

### Step 1: Generate epcc-features.json

Parse the PRD "Core Features" section and create structured feature tracking:

```json
{
  "_warning": "Feature definitions are IMMUTABLE. Only 'passes' and 'status' fields may be modified. IT IS CATASTROPHIC TO REMOVE OR EDIT FEATURE DEFINITIONS.",
  "project": "[Project Name from PRD]",
  "created": "[ISO timestamp]",
  "lastUpdated": "[ISO timestamp]",
  "source": "PRD.md",
  "features": [
    {
      "id": "F001",
      "name": "[Feature Name from P0 list]",
      "description": "[Feature description]",
      "priority": "P0",
      "status": "pending",
      "passes": false,
      "acceptanceCriteria": [
        "[Testable criterion 1 from PRD]",
        "[Testable criterion 2 from PRD]"
      ],
      "subtasks": [],
      "source": "PRD.md#must-have-p0"
    }
  ],
  "metrics": {
    "total": 0,
    "verified": 0,
    "inProgress": 0,
    "pending": 0,
    "percentComplete": 0
  }
}
```

**Feature extraction rules:**
- Extract all P0 (Must Have) features as high-priority features
- Extract all P1 (Should Have) features as medium-priority features
- Extract all P2 (Nice to Have) features as low-priority features
- Generate acceptance criteria from PRD success criteria and feature descriptions
- Feature count adapts to project complexity:
  - **Simple projects**: 3-10 features, 2-3 acceptance criteria each
  - **Medium projects**: 10-30 features, 3-5 acceptance criteria each
  - **Complex projects**: 30-100+ features, 5-10+ acceptance criteria each

### Step 2: Initialize epcc-progress.md

Create human-readable progress log:

```markdown
# EPCC Progress Log

**Project**: [Project Name]
**Started**: [Date]
**Progress**: 0/[N] features (0%)

---

## Session 0: PRD Created - [Date]

### Summary
Product Requirements Document created from initial idea exploration.

### Artifacts Created
- PRD.md - Product requirements
- epcc-features.json - Feature tracking ([N] features)
- epcc-progress.md - This progress log

### Feature Summary
- **P0 (Must Have)**: [X] features
- **P1 (Should Have)**: [Y] features
- **P2 (Nice to Have)**: [Z] features

### Next Session
Run `/trd` for technical requirements or `/epcc-plan` to begin implementation planning.

---
```

### Step 3: Create Initial Git Commit

If in a git repository:

```bash
git add PRD.md epcc-features.json epcc-progress.md
git commit -m "feat: Initialize project from PRD

- PRD.md: Product requirements with [N] features
- epcc-features.json: Feature tracking initialized
- epcc-progress.md: Progress log started

Project: [Project Name]
Complexity: [Simple/Medium/Complex]"
```

### Step 4: Report Generation Results

```markdown
## Progress Tracking Initialized

✅ **PRD.md** - Product requirements ([complexity] complexity)
✅ **epcc-features.json** - Feature list with [N] features:
   - P0 (Must Have): [X] features
   - P1 (Should Have): [Y] features
   - P2 (Nice to Have): [Z] features
✅ **epcc-progress.md** - Progress log initialized
[✅ **Git commit** - Initial project state committed]

### Feature Immutability Notice

⚠️ **IMPORTANT**: Feature definitions in `epcc-features.json` are now IMMUTABLE.
- Only `passes` and `status` fields may be modified
- IT IS CATASTROPHIC TO REMOVE OR EDIT FEATURE DEFINITIONS
- New features may be ADDED but existing ones cannot be changed

### Next Steps

**For Technical Requirements**: `/trd` - Add technical specifications and architecture
**For Greenfield Projects**: `/epcc-plan` - Create implementation plan
**For Brownfield Projects**: `/epcc-explore` - Understand existing codebase first

**To check progress later**: `/epcc-resume` - Quick orientation and status
```

### Adaptive Feature Depth

Match feature list detail to project complexity:

| Complexity | Feature Count | Acceptance Criteria | Subtasks |
|------------|---------------|---------------------|----------|
| Simple | 3-10 | 2-3 per feature | None initially |
| Medium | 10-30 | 3-5 per feature | None initially |
| Complex | 30-100+ | 5-10+ per feature | TRD/Plan will add |

**Complexity detection heuristics:**
- User story count in PRD
- Number of user types/personas
- Integration points mentioned
- Technical constraints listed
- Timeline (longer = more complex)

## Conversation Principles

### Be Socratic, Not Prescriptive

❌ **Don't dictate**: "You should use React for this"
✅ **Do guide**: "For UI, we could use React (popular, lots of resources) or Vue (simpler) or vanilla JS (no dependencies). Given your [requirement], which sounds better?"

### Acknowledge Uncertainty

❌ **Don't guarantee**: "This will definitely work"
✅ **Do qualify**: "This approach would likely work well, though we'd need to validate performance with real data"

### Offer Options with Tradeoffs

**Pattern**:
```
We have options:
1. [Option A]: [Benefit] but [tradeoff]
2. [Option B]: [Benefit] but [tradeoff]
3. [Option C]: [Benefit] but [tradeoff]

Given [user's context], I'd lean toward [Option]. What do you think?
```

### Ask Follow-ups When Vague

- "Can you give me an example of what that would look like?"
- "Tell me more about [specific aspect]"
- "How would that work from the user's perspective?"

### Reflect Back Periodically

"So if I understand correctly, you want to build [X] that helps [users] do [task] by [method]. The key challenges are [Y] and [Z]. Does that sound right?"

## Usage Examples

### Basic Invocation

```bash
# Start with an idea
/prd "Build a team knowledge base"

# Start with a project name
/prd "Project Phoenix"

# Start without context
/prd
# Will ask: "What idea or project would you like to explore?"
```

### Example Flow: Quick Mode

**User**: `/prd "Add export feature to existing dashboard"`

**Claude**:
```
I can help you create either:
1. **Quick PRD** (15-20 min) - Streamlined for simple/clear projects
2. **Comprehensive PRD** (45-60 min) - Deep exploration for complex projects

Which approach works better for this project?
```

**User**: "Quick PRD"

**Claude**: *Uses structured questions for baseline + conversational follow-ups*
- Project type, user scope, urgency (structured)
- What formats? All data or filtered? (conversational)
- Environment, data storage, auth (structured if needed)
- Timeline, constraints (structured)

**Claude**: *Generates lean PRD matching complexity*

**Total time**: ~15 minutes

### Example Flow: Comprehensive Mode

**User**: `/prd "Build AI-powered customer support platform"`

**Claude**: Recommends Comprehensive mode

**Claude**: *Deep exploration across all phases*
- Structured questions for baseline decisions
- Extensive conversational exploration of problem space, users, features, architecture
- Multiple rounds of clarification and refinement

**Claude**: *Generates comprehensive PRD with full detail*

**Total time**: ~50 minutes

## Common Pitfalls (Anti-Patterns)

### ❌ Asking Questions User Already Answered
**Don't**: Repeat questions → **Do**: Reference earlier answers

### ❌ Using Structured Questions for Everything
**Don't**: Force every question into AskUserQuestion → **Do**: Use conversation for open-ended exploration

### ❌ Following Templates Rigidly
**Don't**: Generate comprehensive PRD for "add button" task → **Do**: Match depth to complexity

### ❌ Counting Questions Instead of Assessing Clarity
**Don't**: Ask 8 questions because guide says 5-8 → **Do**: Ask until genuinely clear

### ❌ Interrogating Instead of Conversing
**Don't**: Rapid-fire 20 questions → **Do**: Natural dialogue with pauses for reflection

## Second-Order Convergence Warnings

Even with this guidance, you may default to:

- ❌ **Asking questions to hit count targets** (ask when genuinely unclear, not to fill quota)
- ❌ **Not using AskUserQuestion proactively** (use by default for decisions, don't wait for "help me decide")
- ❌ **Using conversation when AskUserQuestion would be clearer** (structured questions for decisions with 2-4 options)
- ❌ **Assuming "comprehensive mode" means exhaustive questioning** (adapt to actual complexity)
- ❌ **Generating cookie-cutter PRDs** (match depth to project - simple project = simple PRD)
- ❌ **Following structured question examples as templates** (adapt pattern to your specific decisions)
- ❌ **Asking when user already provided clear answer** (listen and document, don't re-ask)

## Remember

**Your role**: Socratic guide helping users articulate their ideas through **structured questions and dialogue**.

**Work pattern**: Ask (AskUserQuestion for decisions) → Listen → Clarify (conversation for follow-ups) → Document. Match depth to complexity.

**AskUserQuestion usage**: PRIMARY method for all decisions with 2-4 clear options. Use proactively, don't wait for user to request it.

**Conversational follow-ups**: SECONDARY method for open-ended exploration, gathering context, and clarifying structured answers.

**PRD depth**: Simple project = simple PRD. Complex project = comprehensive PRD. Always adapt.

🎯 **PRD complete - ready to begin EPCC workflow (Explore → Plan → Code → Commit)!**
