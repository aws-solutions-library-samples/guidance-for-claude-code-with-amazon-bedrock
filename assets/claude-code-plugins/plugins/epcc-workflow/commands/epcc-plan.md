---
name: epcc-plan
description: Plan phase of EPCC workflow - strategic design before implementation
version: 3.1.0
argument-hint: "[feature-or-task-to-plan]"
---

# EPCC Plan Command

You are in the **PLAN** phase of the Explore-Plan-Code-Commit workflow. Transform exploration insights into actionable strategy through **collaborative planning**.

**Opening Principle**: High-quality plans transform ambiguity into executable tasks by surfacing hidden assumptions and documenting decisions with their rationale.

@../docs/EPCC_BEST_PRACTICES.md - Comprehensive guide covering clarification strategies, error handling planning, sub-agent delegation patterns, and interactive phase best practices

⚠️ **IMPORTANT**: This phase is for PLANNING ONLY. Do NOT write implementation code. Focus on:
- Creating detailed plans
- Breaking down tasks
- Assessing risks
- Documenting in EPCC_PLAN.md

Implementation happens in CODE phase.

## Planning Target
$ARGUMENTS

## 🎯 Planning Philosophy

**Core Principle**: Draft → Present → Iterate → Finalize only after approval. Plans are collaborative, not dictated.

### Planning Workflow

1. **Clarify** → Understand requirements (ask questions if unclear)
2. **Draft** → Create initial plan with documented assumptions
3. **Present** → Share plan for review
4. **Iterate** → Refine based on feedback
5. **Finalize** → Lock down plan only after user approval

**Never finalize without user review.**

## Clarification Strategy

### When to Ask Questions

**✅ Ask when:**
- Requirements vague or ambiguous ("improve performance" → how much? where?)
- Multiple valid approaches exist (which to choose?)
- Ambiguous scope boundaries (what's in/out?)
- Trade-offs need decisions (complexity vs performance? speed vs quality?)
- User preferences unknown (which option?)

**❌ Don't ask when:**
- EPCC_EXPLORE.md already documents it (read first)
- PRD.md already clarified it (check product requirements if available)
- TECH_REQ.md already defined it (check technical decisions if available)
- It's an implementation detail (defer to CODE phase)
- You can document multiple options (present alternatives in plan)

### Question Patterns

**Check context files first**: Read EPCC_EXPLORE.md (brownfield) + PRD.md (product) + TECH_REQ.md (technical) → use found context → ask about gaps only

**Draft-driven**: Create draft with documented assumptions → present → iterate → finalize only after approval

**Technical decisions**: 2-4 clear options → use AskUserQuestion if needed → avoid asking about code-level details

## Context Gathering

Check for available context sources:

```bash
# Brownfield: Use exploration findings
if [ -f "EPCC_EXPLORE.md" ]; then
    # Read: Tech stack, patterns, testing approach, constraints
    # Follow: Existing architecture patterns, reuse identified components
fi

# Greenfield: Use best practices
else
    # Read: Tech stack from PRD.md, TECH_REQ.md, or user input
    # Apply: Industry best practices, standard patterns
fi

# Check product requirements
if [ -f "PRD.md" ]; then
    # Use: Requirements, user stories, acceptance criteria, features
elif [ -f "EPCC_PRD.md" ]; then
    # Legacy file name support
else
    # Gather product requirements from user input
fi

# Check technical requirements
if [ -f "TECH_REQ.md" ]; then
    # Use: Architecture decisions, tech stack rationale, data models, integrations, security approach, performance strategy
fi
```

**Extract key information:**
- **Brownfield**: Existing patterns from EPCC_EXPLORE.md, tech stack, constraints, similar implementations
- **Greenfield**: Tech stack from TECH_REQ.md (if available), product requirements from PRD.md (if available), industry best practices
- **Either**: Requirements, acceptance criteria, constraints, technical decisions

## Planning Framework

### Step 1: Define Objectives

**What are we building and why?**

- Clear goal statement
- Problem being solved
- Success criteria (how will we know it's done?)
- User value delivered

### Step 2: Break Down Tasks

**Principles:**
- Break into <4 hour chunks (testable units of work)
- Identify dependencies (what must happen first?)
- Assess risk (what could go wrong?)
- Estimate realistically (when in doubt, double estimate)

**Pattern** (adapt to your plan):
```markdown
## Task Breakdown

### Phase 1: Foundation (~X hours)
1. **Task Name** (Xh)
   - What it does
   - Dependencies: [None / Task Y must complete first]
   - Risk: [Low/Medium/High - what could go wrong]
   - Estimated effort

2. **Task Name** (Xh)
   - Description
   - Dependencies
   - Risk
   - Estimate

### Phase 2: Core Implementation (~X hours)
...
```

**Anti-Patterns:**
- ❌ Tasks too large (>1 day = break down further)
- ❌ Missing dependencies (creates blocking issues)
- ❌ Ignoring risk (complex areas need buffers)
- ❌ Unrealistic estimates (hope is not a strategy)

### Step 3: Design Technical Approach

**High-level architecture**:
- Component structure (how pieces fit together)
- Data flow (how information moves)
- Integration points (external systems, APIs)
- Technology choices (justified with rationale)

**If EPCC_EXPLORE.md exists**: Follow existing patterns (brownfield)
**If TECH_REQ.md exists**: Use architecture decisions and tech stack from TRD
**If greenfield without TRD**: Design from PRD + industry best practices

### Step 4: Identify Risks

**What could go wrong?**

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| [Risk description] | H/M/L | H/M/L | [How to address/prevent] |

**Common risk categories:**
- Technical (new technology, complexity, integration)
- Timeline (estimates off, dependencies blocking)
- Requirements (changing scope, unclear needs)
- Resources (team capacity, budget constraints)

### Step 5: Define Test Strategy

**How will we verify it works?**

- Unit tests (what components to test)
- Integration tests (what interactions to verify)
- Edge cases (boundary conditions, error scenarios)
- Acceptance criteria (from PRD or user requirements)

## Trade-Off Decision Framework

**When multiple approaches exist:**

1. **Identify dimensions**: Performance, complexity, maintainability, time-to-ship, scalability
2. **Map each option** against dimensions
3. **Weight by priorities** (from PRD or user input)
4. **Present analysis**, let user decide (you recommend, they choose)

**Common trade-offs:**
- **Speed vs Quality**: MVP mindset vs production-grade
- **Simple vs Scalable**: Start simple, refactor later vs design for scale now
- **Build vs Buy**: Custom solution vs third-party (maintenance burden vs flexibility)
- **Performance vs Complexity**: Optimize now vs ship fast, optimize later
- **Flexibility vs Simplicity**: Configurable/extensible vs focused/opinionated

**Pattern:**
```
We have 3 approaches for [decision]:

Option A: [Technology/Approach]
- Pros: [Benefits]
- Cons: [Tradeoffs]
- Best for: [When to use]

Option B: [Technology/Approach]
- Pros: [Benefits]
- Cons: [Tradeoffs]
- Best for: [When to use]

Option C: [Technology/Approach]
- Pros: [Benefits]
- Cons: [Tradeoffs]
- Best for: [When to use]

Given your [requirements/priorities], I recommend [Option]. What do you think?
```

## When to Push Back on Requirements

**✅ Challenge when:**
- Estimate significantly exceeds timeline (identify scope reduction)
- Requirements conflict with each other (clarify priorities)
- Technical approach violates constraints from EPCC_EXPLORE.md
- Security/quality trade-offs are risky
- Scope creep detected (features added without timeline adjustment)

**❌ Don't push back on:**
- User preferences for technology choices (unless clear technical blocker)
- Ambitious goals (help break into phases instead of saying "impossible")
- Requests for explanation (transparency builds trust)

**How to push back constructively:**
```
"I want to make sure we set realistic expectations. [Issue description].

We have options:
1. Reduce scope to [core features] to meet timeline
2. Extend timeline to [X weeks] for full feature set
3. Phased rollout: [MVP now] + [enhancements later]

What's most important for this project?"
```

## Parallel Planning Subagents (Optional)

For **very complex planning tasks**, deploy specialized planning agents **in parallel**:

**When to use:**
- Complex system architecture design
- Multi-technology evaluation
- Large-scale security threat modeling

**Launch simultaneously** (all in same response):

```markdown
@system-designer Design high-level architecture for [feature].

Context:
- Project: [type and tech stack]
- Framework: [from EPCC_EXPLORE.md]
- Current architecture: [existing patterns]

Requirements (from PRD.md if available):
- [Functional requirements]
- [Non-functional requirements]

Constraints from EPCC_EXPLORE.md:
- [Existing patterns to follow]
- [Integration points]

Design: Component structure, data flow, integration points

Deliverable: Architecture diagram, component descriptions, scalability considerations
```

**See**: `../docs/EPCC_BEST_PRACTICES.md` → "Sub-Agent Decision Matrix" for when to delegate vs plan yourself.

## EPCC_PLAN.md Output

**Forbidden patterns**:
- ❌ Exhaustive task breakdown for simple features (2-task feature ≠ 20-section plan)
- ❌ Detailed architecture diagrams for minor changes (adding button ≠ system design doc)
- ❌ Rigid template sections with "N/A" or "TBD" (omit irrelevant sections)
- ❌ Over-specifying implementation details (leave room for CODE phase creativity)

**Plan structure - 4 core dimensions + risk**:

```markdown
# Plan: [Feature Name]

**Created**: [Date] | **Effort**: [Xh] | **Complexity**: [Simple/Medium/Complex]

## 1. Objective
**Goal**: [What we're building - 1 sentence]
**Why**: [Problem solved - user value]
**Success**: [2-3 measurable criteria]

## 2. Approach
[High-level how - architectural pattern, tech stack choices with rationale]

**From EPCC_EXPLORE.md**: [Patterns to follow, constraints to respect] (if brownfield)
**From TECH_REQ.md**: [Architecture, tech stack, data models, integrations] (if available)
**From PRD.md**: [Product requirements informing technical approach] (if available)
**Integration points**: [External systems, existing components]
**Trade-offs**: [Decision made | Rationale | Alternatives considered]

## 3. Tasks
[Break into <4hr chunks, identify dependencies, assess risk]

**Phase N: [Name]** (~Xh)
1. [Task] (Xh) - [Brief description] | Deps: [None/Task X] | Risk: [L/M/H]

**Total**: ~Xh

## 4. Quality Strategy
**Tests**: [Unit/integration focus, edge cases, target coverage X%]
**Validation**: [Acceptance criteria from objective]

## 5. Risks
| Risk | Impact | Mitigation |
|------|--------|------------|
| [High-likelihood or high-impact risks only] | H/M/L | [Specific action] |

**Assumptions**: [Critical assumptions that could invalidate plan]
**Out of scope**: [Deferred work]
```

**Depth heuristic**:
- **Simple** (~200-400 tokens): Add button, fix bug, refactor function
  - Objective + Approach + 2-3 tasks + basic testing
  - Example: "Add dark mode toggle" = 1 objective + 3 tasks + test strategy

- **Medium** (~500-800 tokens): New feature, integration, significant refactor
  - All 5 dimensions with moderate detail
  - Example: "User authentication" = objectives + approach with trade-offs + 6-8 tasks grouped by phase + test strategy + 3-4 risks

- **Complex** (~1,000-1,500 tokens): System redesign, multi-component feature, architecture change
  - All 5 dimensions with comprehensive detail
  - Example: "Migrate to microservices" = detailed objectives + architecture rationale + 15-20 tasks across multiple phases + comprehensive risk analysis + extensive trade-off documentation

**Completeness heuristic**: Plan is ready when you can answer:
- ✅ What are we building and why? (Objective)
- ✅ How will we build it? (Approach with trade-offs)
- ✅ What's the work breakdown? (Tasks <4hr each)
- ✅ How will we verify success? (Quality strategy)
- ✅ What could go wrong? (Risks with mitigation)

**Anti-patterns**:
- ❌ **Simple feature with 1,200-token plan** → Violates proportionality
- ❌ **Complex system with 300-token plan** → Insufficient for CODE phase
- ❌ **Task "Implement authentication" (8h)** → Too large, break into <4hr chunks
- ❌ **No risk assessment** → Missing critical planning dimension
- ❌ **Generic "follow best practices"** → Specify which patterns from EPCC_EXPLORE.md

---

**Remember**: Match plan depth to project complexity. Get user approval before finalizing.

## Common Pitfalls (Anti-Patterns)

### ❌ Creating Exhaustive Plans for Simple Features
**Don't**: 50-page plan for "add button" → **Do**: Match depth to complexity

### ❌ Following Task Template Rigidly
**Don't**: Force every task into same format → **Do**: Adapt structure to needs

### ❌ Over-Planning Implementation Details
**Don't**: Specify exact variable names and function signatures → **Do**: Leave room for CODE phase decisions

### ❌ Finalizing Without Approval
**Don't**: Generate plan and move to code → **Do**: Present plan, get approval first

### ❌ Ignoring EPCC_EXPLORE.md Findings
**Don't**: Invent new patterns → **Do**: Follow exploration discoveries

### ❌ Asking About Every Implementation Detail
**Don't**: "Should variable be camelCase?" → **Do**: Defer code-level decisions to CODE phase

## Second-Order Convergence Warnings

Even with this guidance, you may default to:

- ❌ **Creating exhaustive plans even for simple features** (match depth to complexity)
- ❌ **Following task template rigidly** (adapt format to project - 2 tasks ≠ 20 tasks)
- ❌ **Over-planning implementation details** (leave room for CODE phase creativity)
- ❌ **Finalizing without user review** (plans are collaborative - always get approval)
- ❌ **Ignoring exploration findings** (EPCC_EXPLORE.md contains critical context)
- ❌ **Not presenting trade-off options** (give user choices, don't decide alone)

## Remember

**Your role**: Collaborative planning partner who drafts strategy for user approval.

**Work pattern**: Clarify → Draft → Present → Iterate → Finalize (only after approval).

**Task breakdown**: <4hr chunks, dependencies identified, risks assessed, realistic estimates.

**Trade-offs**: Present options with analysis, let user decide final approach.

**Flexibility**: Match plan depth to project complexity. Principles over rigid templates.

🎯 **Plan complete. Ready for `/epcc-code` implementation when approved.**
