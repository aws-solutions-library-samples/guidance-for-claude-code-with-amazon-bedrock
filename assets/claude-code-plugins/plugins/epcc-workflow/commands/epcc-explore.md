---
name: epcc-explore
description: Explore phase of EPCC workflow - understand thoroughly before acting
version: 3.1.0
argument-hint: "[area-to-explore] [--deep|--quick]"
---

# EPCC Explore Command

You are in the **EXPLORE** phase of the Explore-Plan-Code-Commit workflow. Your mission is to understand thoroughly before taking any action.

**Opening Principle**: High-quality exploration reveals not just what exists, but why it exists—enabling confident forward decisions without re-discovery.

@../docs/EPCC_BEST_PRACTICES.md - Comprehensive guide covering clarification strategies, error handling patterns, sub-agent delegation, and EPCC workflow optimization

⚠️ **IMPORTANT**: This phase is for EXPLORATION ONLY. Do NOT write any implementation code. Focus exclusively on:
- Reading and understanding existing code
- Analyzing patterns and architecture
- Identifying constraints and dependencies
- Documenting everything in EPCC_EXPLORE.md

All implementation will happen in the CODE phase.

## Exploration Target
$ARGUMENTS

### Exploration Thoroughness

Parse thoroughness level from arguments:
- `--quick`: Fast surface-level exploration (key areas, basic patterns)
- `--deep` or `--thorough`: Comprehensive analysis (multiple locations, cross-referencing, detailed patterns)
- **Default** (no flag): Medium thoroughness (balanced exploration)

## 🎯 Autonomous Exploration Mode

This command operates as an **autonomous exploration agent**, similar to Claude Code's Explore subagent:

### Exploration Characteristics

1. **Self-Directed Search**: Automatically tries multiple search strategies if initial attempts don't find relevant information
2. **Comprehensive Coverage**: Systematically explores all relevant areas without needing step-by-step guidance
3. **Pattern Recognition**: Identifies and documents coding patterns, architectural decisions, and conventions
4. **Persistent Investigation**: Doesn't give up easily - tries different file patterns, search terms, and approaches
5. **Complete Report**: Delivers a single, comprehensive exploration report in EPCC_EXPLORE.md

## When to Ask Questions

This phase is designed to be **autonomous** - you should explore independently without frequent user interaction.

### Rarely Ask (Exploration is Self-Directed)

✅ **Only ask when:**
- **Exploration target is genuinely unclear** ("explore authentication" but no auth code found anywhere)
- **Multiple conflicting patterns exist** and unclear which is canonical
- **Completely blocked** after trying multiple search strategies
- **Critical information is missing** that prevents meaningful exploration (e.g., can't access certain directories)

❌ **Don't ask when:**
- First search doesn't find something (try alternative approaches first)
- Multiple patterns exist (document all of them)
- Code is messy or unclear (document what you find)
- You're unsure which pattern is best (document options, let PLAN decide)
- Exploration is taking longer than expected (be thorough)

### Problem-Solving Approach

**Instead of asking, try:**

1. **Multiple search strategies**: If `grep authentication` fails, try `grep auth`, `find . -name "*auth*"`, check common directories
2. **Follow the trail**: Found one file? Check its imports, look for similar files in same directory
3. **Document uncertainty**: "Pattern X found in 3 places, Pattern Y in 2 places. Both appear active."
4. **Note gaps**: "No authentication code found after checking [list of searches]. This appears to be a greenfield area."

### When to Use AskUserQuestion Tool

**Almost never in EXPLORE phase.** This phase is autonomous by design.

**Rare exception**: If exploration target is ambiguous AND you've tried reasonable interpretations:
```
User: "explore the payment system"
You've searched: payment*, billing*, transaction*, checkout*, stripe*, paypal*
Found: Nothing related to payments
Then ask: "I searched extensively but found no payment-related code. Should I:
  - Explore a different area?
  - Treat this as greenfield (no existing payment code)?
  - Search with different terms?"
```

### Clarification Pattern

**Pattern: Try → Try → Try → Document**
```
1. Try search approach A → No results
2. Try search approach B → No results
3. Try search approach C → No results
4. Document: "Searched for X using [approaches]. No matches found. This appears greenfield."
```

NOT: ~~Try once → Ask user~~

Remember: You're an **autonomous explorer**. Be persistent, try multiple approaches, and document what you find (or don't find). Save questions for genuine blockers, not first obstacles.

## Handling Ambiguity (CRITICAL)

**EXPLORE phase is autonomous by design - avoid asking questions unless truly blocked.**

Before escalating to AskUserQuestion, ensure you've exhausted autonomous exploration:

### Unclear Exploration Target?

**Try multiple interpretations first:**

```
User: "explore the payment system"

Step 1: Try broad searches
- grep -r "payment" .
- find . -name "*payment*"
- grep -r "billing\|transaction\|checkout" .

Step 2: Try platform-specific patterns
- Stripe: grep -r "stripe"
- PayPal: grep -r "paypal"
- Generic: grep -r "charge\|invoice\|subscription"

Step 3: Check configuration
- Look for API keys in .env files
- Check package.json/requirements.txt for payment libraries

Step 4: Document findings
If nothing found: "Searched extensively (payment*, billing*, stripe*, etc.). No payment code found. This appears to be a greenfield area."
If multiple found: "Found two payment implementations: legacy (src/billing/) and new (src/payments/). Both appear active."
```

**Only ask if genuinely blocked:**

Use AskUserQuestion tool with proper format:
```json
{
  "questions": [{
    "question": "I found no payment-related code after extensive searching. How should I proceed?",
    "header": "Next Step",
    "multiSelect": false,
    "options": [
      {
        "label": "Treat as greenfield",
        "description": "Document that no payment code exists yet"
      },
      {
        "label": "Different search terms",
        "description": "Provide specific terms or file paths to search"
      },
      {
        "label": "Different feature area",
        "description": "Explore a different part of the codebase instead"
      }
    ]
  }]
}
```

### Multiple Conflicting Patterns Exist?

**Document all patterns, don't ask which to choose:**

```markdown
## 8. Multiple Patterns Found

**Authentication Implementation:**

Pattern A: JWT-based (src/auth/jwt/)
- Used in: API endpoints (3 files)
- Last modified: 2025-10-15
- Pros: Stateless, scalable
- Status: Appears to be current standard

Pattern B: Session-based (src/auth/sessions/)
- Used in: Legacy admin panel (2 files)
- Last modified: 2024-03-20
- Pros: Simpler
- Status: Possibly deprecated (no recent changes)

**Recommendation**: Pattern A (JWT) appears to be the current standard based on recent activity.
```

**See Also**: EPCC_BEST_PRACTICES.md → "Clarification Decision Framework"

### Exploration Strategy

**BE SYSTEMATIC AND THOROUGH:**

1. **Try multiple search approaches** if first attempt yields no results:
   - Different file patterns (*.py, *auth*, authentication*)
   - Various naming conventions (camelCase, snake_case, kebab-case)
   - Related terms and synonyms
   - Directory-specific searches

2. **Follow the trail**:
   - If you find a relevant file, check its imports/dependencies
   - Look for related files in the same directory
   - Search for similar patterns in other modules
   - Trace relationships between components

3. **Be comprehensive**:
   - Don't stop at the first match
   - Explore multiple examples of the same pattern
   - Check both implementation and test files
   - Review configuration and documentation

4. **Document as you go**:
   - Track what you've searched and what you found
   - Note patterns and conventions
   - Identify gaps or unclear areas
   - Record assumptions that need validation

## 🔍 Exploration Objectives

1. **Review Project Instructions**: Check for CLAUDE.md files with project-specific guidance
2. **Map the Territory**: Understand project structure and architecture
3. **Identify Patterns**: Find coding conventions and design patterns
4. **Discover Constraints**: Technical, business, and operational limitations
5. **Review Similar Code**: Find existing implementations to learn from
6. **Assess Complexity**: Understand the scope and difficulty
7. **Document Dependencies**: Map internal and external dependencies
8. **Evaluate Test Coverage**: Understand testing approaches and gaps

## Thoroughness-Based Exploration Heuristics

### Completion Criteria (NOT File Count Targets)

**Stop exploring when objectives are met**, not when you hit arbitrary file counts.

### Quick Exploration (--quick)
**Stop when you understand:**
- Entry points and main flow
- 2-3 key patterns that dominate the codebase
- Basic tech stack and dependencies
- CLAUDE.md instructions (if present)

**Typical indicators you're done:**
- Can explain project structure in 2-3 sentences
- Identified dominant framework and language
- Found 1-2 similar implementations to learn from

### Medium Exploration (default)
**Stop when you understand:**
- All major architectural patterns with examples
- Cross-module relationships and data flow
- Test patterns and coverage approach
- Configuration and deployment approach

**Typical indicators you're done:**
- Can draw component diagram from memory
- Identified 3-5 reusable patterns/components
- Understand how features flow end-to-end

### Deep Exploration (--deep/--thorough)
**Stop when you've exhaustively documented:**
- All patterns with multiple examples each
- Complete dependency tree (internal + external)
- Historical context and technical debt areas
- Edge cases and performance considerations
- Security patterns and compliance requirements

**Typical indicators you're done:**
- Can onboard new developer from your exploration alone
- Documented every architectural decision
- Identified all constraints and risks

**Heuristic Rule**: If reading another file of the same type teaches you nothing new, you're done with that pattern.

## Parallel Exploration Subagents (Optional for Complex Exploration)

For **very large codebases or complex exploration tasks**, you MAY deploy specialized exploration agents **in parallel to save time**.

**Launch simultaneously** (all in same response):

```
# ✅ GOOD: Parallel exploration (agents explore different aspects)
@code-archaeologist Analyze authentication system architecture and data flow.

Target: Authentication implementation across codebase
Focus areas:
- Token generation and validation flow
- Session management approach
- Password hashing implementation
- Rate limiting mechanisms

Trace: User login → token creation → validation → protected endpoint access
Document: Component interactions, data flow, security patterns, technical debt areas.

@system-designer Document authentication system architecture and component design.

Target: Authentication system structure
Analyze:
- Component boundaries and responsibilities
- Service layer architecture
- Database schema for auth
- API endpoint design

Generate: Architecture diagram, component relationships, data models, integration points.

@business-analyst Identify authentication business requirements and user workflows.

Target: Authentication feature scope and purpose
Analyze:
- User registration and login flows
- Password reset mechanisms
- Multi-factor authentication support
- Role-based access control

Document: User stories, business rules, workflow diagrams, requirement gaps.

# All three explore different aspects concurrently
```

**Available agents:**
@code-archaeologist @system-designer @business-analyst @test-generator @documentation-agent

**Full agent reference**: See `../docs/EPCC_BEST_PRACTICES.md` → "Agent Capabilities Overview" for agents in other phases (CODE, PLAN, COMMIT).

**IMPORTANT**: Only use subagents for codebases with 100+ files or highly complex systems. For typical projects, handle exploration directly and autonomously.

## Exploration Methodology

### Phase 1: Project Context & Instructions

**ALWAYS START HERE:**

Check for CLAUDE.md files in this order:
1. Project root CLAUDE.md
2. .claude/CLAUDE.md
3. User global ~/.claude/CLAUDE.md

Document ALL instructions found - these are mandatory requirements for the project.

### Phase 2: Project Structure Discovery

Use multiple approaches to understand structure:
- Directory listings (ls, tree if available)
- File finding (find, Glob)
- Key file identification (entry points, configs)

Adapt if one approach fails - try another.

### Phase 3: Technology Stack Identification

Systematically check for different project types:
- Python: pyproject.toml, requirements.txt, setup.py, Pipfile, poetry.lock
- JavaScript/TypeScript: package.json, tsconfig.json, yarn.lock, pnpm-lock.yaml
- Other languages: Gemfile, pom.xml, build.gradle, Cargo.toml, go.mod, composer.json

Document frameworks, libraries, versions, and tools found.

### Phase 4: Pattern Recognition (Multi-Strategy Search)

**Use persistent, multi-attempt searching:**

Example: Finding authentication patterns
1. Direct file search: `find . -name "*auth*"`
2. Content search: `grep -r "authenticate|login|session"`
3. Class/function search: `grep -r "class.*Auth|def.*login"`
4. Import search: `grep -r "from.*auth import"`
5. Directory check: `ls src/auth/ app/auth/`

**Document what you tried and what worked:**
- Track successful search strategies
- Note what didn't work and why
- Record patterns found with file locations

### Phase 5: Architectural Pattern Discovery

Look for common patterns systematically:
- MVC/MVT Pattern
- Repository Pattern
- Service Layer Pattern
- Factory Pattern
- Middleware/Decorator Pattern
- Observer/Event Pattern

Document each pattern with:
- Where it's used (file paths)
- How many implementations
- Example usage
- When to use it

### Phase 6: Dependency Mapping

Trace both external and internal dependencies:
- **External**: From package manifests (package.json, requirements.txt, etc.)
- **Internal**: Module imports, component relationships, data flow

Create dependency graphs showing relationships.

### Phase 7: Constraint & Risk Identification

Actively search for constraints:
- Performance constraints (timeouts, rate limits, caching)
- Security constraints (CORS, CSRF, authentication, encryption)
- Version constraints (language versions, compatibility)
- Environment constraints (env vars, deployment requirements)

### Phase 8: Similar Implementation Search

If exploring a specific feature, find similar existing code:
- Search for related functionality
- Find integration examples
- Review existing third-party integrations
- Identify reusable components

## Exploration Deliverables

### Output File: EPCC_EXPLORE.md

Generate exploration report in `EPCC_EXPLORE.md` with depth matching scope.

### Report Structure - 5 Core Dimensions

**Forbidden patterns**:
- ❌ Filling template sections with "N/A" or "Not found" (omit irrelevant sections)
- ❌ Rigid 12-section structure for simple codebases (adapt to complexity)
- ❌ Documenting every file read (focus on patterns and decisions)
- ❌ Generic descriptions ("uses standard patterns") - be specific

**Document these dimensions** (depth varies by scope):

```markdown
# Exploration: [Area/Feature]

**Date**: [Date] | **Scope**: [Quick/Medium/Deep] | **Status**: ✅ Complete

## 1. Foundation (What exists)
**Tech stack**: [Language, framework, versions]
**Architecture**: [Pattern family - "Express REST API", "Django monolith", "React SPA + FastAPI"]
**Structure**: [Entry points, key directories with purpose]
**CLAUDE.md instructions**: [Critical requirements found]

## 2. Patterns (How it's built)
[Name pattern families, not every instance]

**Architectural patterns**:
- [Pattern name]: [Where used - file:line], [When to use]

**Testing patterns**:
- [Test framework + approach]: [Fixture patterns, mock strategies]
- **Coverage**: [X%], **Target**: [Y%]

**Error handling**: [Exit codes, stderr usage, agent compatibility - see EPCC_BEST_PRACTICES.md]

## 3. Constraints (What limits decisions)
**Technical**: [Language versions, platform requirements]
**Quality**: [Test coverage targets, linting rules, type checking]
**Security**: [Auth patterns, input validation, known gaps]
**Operational**: [Deployment requirements, CI/CD, monitoring]

## 4. Reusability (What to leverage)
[Only if implementing similar feature]

**Similar implementations**: [file:line references]
**Reusable components**: [What can be copied vs adapted]
**Learnings**: [What worked, what to avoid]

## 5. Handoff (What's next)
**For PLAN**: [Key constraints, existing patterns to follow]
**For CODE**: [Tools/commands to use - test runner, linter, formatter]
**For COMMIT**: [Quality gates - coverage target, security checks]
**Gaps**: [Unclear areas requiring clarification]
```

**Adaptation heuristic**:
- **Quick scope** (~150-300 tokens): Foundation + critical constraints only
- **Medium scope** (~400-600 tokens): Foundation + patterns + constraints + handoff
- **Deep scope** (~800-1,500 tokens): All 5 dimensions with comprehensive detail

**Completeness heuristic**: Report is complete when you can answer:
- ✅ What tech stack and patterns must I follow?
- ✅ What quality gates must I pass?
- ✅ What can I reuse vs build new?
- ✅ What constraints limit my choices?

**Anti-patterns**:
- ❌ **Quick scope with 1,500 tokens** → Violates scope contract
- ❌ **Deep scope with 200 tokens** → Insufficient for complex codebase
- ❌ **Listing every file** → Name directory patterns instead
- ❌ **Generic "uses testing"** → Specify framework, fixture patterns, coverage

---

**End of template guidance**

**Important**: Fill each section with **actual findings** from your exploration, not placeholders or examples. Include:
- Specific file paths with line numbers
- Actual code patterns found
- Real metrics and statistics
- Concrete recommendations based on what you discovered

## Common Pitfalls (Anti-Patterns)

### ❌ Giving Up After First Search Fails
**Don't**: Search once, ask user → **Do**: Try 3-5 search strategies before concluding

### ❌ Hitting File Count Instead of Understanding
**Don't**: Read 10 files because target says "~10" → **Do**: Stop when pattern is understood

### ❌ Skipping CLAUDE.md Files
**Don't**: Jump straight to code → **Do**: Read CLAUDE.md first (critical project requirements)

### ❌ Documenting Only "Happy Path" Patterns
**Don't**: Document only what works well → **Do**: Document edge cases, error handling, constraints

### ❌ Treating Exploration as Code Review
**Don't**: Judge code quality → **Do**: Document what exists objectively

### ❌ Asking User to Clarify Obvious Search Targets
**Don't**: "What do you mean by authentication?" → **Do**: Try auth*, login*, session*, JWT patterns first

## Second-Order Convergence Warnings

Even with this guidance, you may default to:

- ❌ **Stopping at first pattern match** (one test file ≠ understanding test patterns - read 3-5 examples)
- ❌ **Reading exactly N files per mode** (file count ≠ understanding - stop when objectives met)
- ❌ **Asking about every ambiguity** (document multiple patterns, let PLAN decide)
- ❌ **Documenting only implementation files** (tests, configs, docs reveal critical context)
- ❌ **Shallow pattern documentation** (don't just list patterns - explain when/why/how to use each)
- ❌ **Treating modes as rigid procedures** (modes are calibration, adapt to actual codebase complexity)

## Exploration Best Practices

### DO:
- ✅ **Try multiple search strategies** if first attempt fails
- ✅ **Read CLAUDE.md files first** - they contain critical requirements
- ✅ **Document your search process** - helps identify gaps
- ✅ **Follow the trail** - check imports and related files
- ✅ **Be comprehensive** - explore multiple examples of patterns
- ✅ **Note what you DON'T find** - gaps are important information
- ✅ **Provide file references** - specific line numbers help later phases

### DON'T:
- ❌ **Give up after one search** - try different terms and patterns
- ❌ **Skip CLAUDE.md** - missing project requirements causes rework
- ❌ **Assume patterns** - verify with actual code examples
- ❌ **Ignore test files** - they reveal intended behavior
- ❌ **Write code** - this is exploration only
- ❌ **Leave gaps undocumented** - note what's missing or unclear

## Exploration Checklist

Before finalizing EPCC_EXPLORE.md:

**Context & Instructions**:
- [ ] Checked for CLAUDE.md in project root
- [ ] Checked for .claude/CLAUDE.md
- [ ] Checked for ~/.claude/CLAUDE.md
- [ ] Documented all project-specific requirements

**Structure & Technology**:
- [ ] Project structure fully mapped
- [ ] Entry points identified
- [ ] Technology stack documented
- [ ] All dependencies listed (external + internal)

**Patterns & Conventions**:
- [ ] Coding patterns documented (with examples)
- [ ] Naming conventions identified
- [ ] Architectural patterns mapped
- [ ] Team conventions understood

**Code Quality**:
- [ ] Testing approach understood
- [ ] Test coverage assessed
- [ ] Code quality tools identified

**Constraints & Risks**:
- [ ] Technical constraints documented
- [ ] Business constraints identified
- [ ] Security patterns reviewed
- [ ] Performance requirements understood
- [ ] Gaps and risks documented

**Similar Implementations**:
- [ ] Related code found and reviewed
- [ ] Reusable components identified
- [ ] Patterns to follow documented

**Completeness**:
- [ ] Search strategies documented
- [ ] Information gaps identified
- [ ] Recommendations provided
- [ ] Next steps outlined

## Usage Examples

```bash
# Quick exploration of entire codebase
/epcc-explore --quick

# Medium exploration (default) of specific area
/epcc-explore authentication

# Deep exploration of specific feature
/epcc-explore payment-processing --deep

# Thorough exploration of multiple areas
/epcc-explore "API routes and database models" --thorough
```

## Integration with Other Phases

### To PLAN Phase:
- EPCC_EXPLORE.md provides complete context
- Patterns to follow documented
- Constraints identified
- Similar implementations found

### To CODE Phase:
- Conventions to follow established
- Reusable components identified
- Test patterns documented
- File organization understood

### To COMMIT Phase:
- Project standards documented
- Team conventions known
- Required checks identified

## Remember

**Time spent exploring saves time coding!**

🚫 **DO NOT**: Write code, create files, implement features, fix bugs, or modify anything

✅ **DO**: Be persistent, try multiple approaches, follow the trail, document thoroughly, save to EPCC_EXPLORE.md
