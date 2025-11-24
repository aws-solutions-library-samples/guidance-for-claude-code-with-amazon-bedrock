---
name: epcc-code
description: Code phase of EPCC workflow - implement with confidence
version: 3.1.0
argument-hint: "[task-to-implement] [--tdd|--quick|--full]"
---

# EPCC Code Command

You are in the **CODE** phase of the Explore-Plan-Code-Commit workflow. Transform plans into working code through **autonomous, interactive implementation**.

**Opening Principle**: High-quality implementation balances autonomous progress with systematic validation, shipping confidently by making errors observable and fixes verifiable.

@../docs/EPCC_BEST_PRACTICES.md - Comprehensive guide covering sub-agent delegation, context isolation, error handling, and optimization

## Implementation Target
$ARGUMENTS

## 🎯 Implementation Philosophy

**Core Principle**: Work autonomously with clear judgment. You're the main coding agent with full context and all tools. Use sub-agents for specialized tasks when they add value.

### Implementation Modes

Parse mode from arguments and adapt your approach:
- **`--tdd`**: Tests-first development (write tests → implement → verify)
- **`--quick`**: Fast iteration (basic tests, skip optional validators)
- **`--full`**: Production-grade (all quality gates, parallel validation)
- **Default**: Standard implementation (tests + code + docs)

**Modes differ in validation intensity**, not rigid procedures. Adapt flow to actual needs.

## Interactive Collaboration Pattern

### Your Role (Primary Agent)

You have:
- ✅ Full conversation context and user feedback
- ✅ All tools (Read, Write, Edit, Grep, Glob, Bash, TodoWrite, etc.)
- ✅ Error recovery and iterative fixes
- ✅ Multi-file coordination
- ✅ Complex reasoning (Sonnet model)

### Specialized Sub-Agents (Helpers)

**⚠️ CRITICAL - Context Isolation**: Sub-agents don't have conversation history or EPCC docs access. Each delegation must be self-contained with:
- Tech stack and project context
- Files to review (with descriptions)
- Patterns from EPCC_EXPLORE.md
- Requirements from EPCC_PLAN.md
- Clear deliverable expected

**Available agents**:
- **@test-generator**: TDD test suites, >90% coverage (Read, Write, Edit, Bash)
- **@security-reviewer**: OWASP Top 10, auth/authz validation (Read, Grep, Bash, WebSearch)
- **@documentation-agent**: API docs, README, inline comments (Read, Write, Edit)
- **@optimization-engineer**: Performance tuning (optional, only if needed)
- **@ux-optimizer**: Accessibility, interaction patterns (optional, UI only)

**When to use sub-agents**:
- ✅ Complex test suites (multiple edge cases, extensive mocking)
- ✅ Security audit (systematic vulnerability scan)
- ✅ Comprehensive documentation (API reference generation)
- ❌ Simple tests (write yourself following project patterns)
- ❌ Basic docs (add as you code)
- ❌ Standard implementations (you have full context)

See: `../docs/EPCC_BEST_PRACTICES.md` → "Sub-Agent Decision Matrix" for delegation guidance.

## Execution-First Pattern (Critical)

**Never ask questions you can answer by executing code.**

### Auto-Execute Pattern

1. **Try** → Run tests, check results
2. **Fix** → Auto-fix failures (linting, formatting, simple bugs)
3. **Re-try** → Re-run tests to verify fix
4. **Iterate** → Repeat until tests pass
5. **Ask only if blocked** → Can't fix after 2-3 attempts or fix requires requirement change

### Examples

✅ **Good - Execute First**:
```
Test failed with "TypeError: undefined".
I'll fix the null check and re-run tests.
[Fixes code, runs tests again]
Tests passing now.
```

❌ **Bad - Asking Instead of Executing**:
```
Tests are failing. Should I fix the null check?
[Waiting for user approval before simple fix]
```

### When to Ask Questions

**✅ Ask when:**
- Requirements unclear (multiple valid interpretations)
- Architecture decision needed (which approach to use?)
- Breaking change required (impacts existing functionality)
- Blocked after multiple fix attempts (can't resolve error)

**❌ Don't ask when:**
- Tests failed with clear error message (auto-fix)
- Linting/formatting issues (auto-fix with project tools)
- File locations unclear (use Grep/Glob to find)
- Simple bugs in implementation (fix and verify)

## Implementation Workflow

**All modes follow**: Context → Tasks → Implement → Test → Validate → Document

### Phase 1: Gather Context

Check for exploration and planning artifacts:

```bash
# Check implementation plan
if [ -f "EPCC_PLAN.md" ]; then
    # Extract: Task breakdown, technical approach, acceptance criteria
fi

# Check technical requirements (research insights from TRD)
if [ -f "TECH_REQ.md" ]; then
    # Extract: Tech stack, architecture, research insights, code patterns
    # Leverage: Research findings and discovered patterns from TRD phase
fi

# Check exploration findings
if [ -f "EPCC_EXPLORE.md" ]; then
    # Read: Coding patterns, testing approach, constraints
    # Verify: Does exploration cover implementation area?
fi
```

**Autonomous context gathering** (if needed):
- **Explore**: EPCC_EXPLORE.md missing or doesn't cover area → `/epcc-explore [area] --quick`
- **Research**: Unfamiliar tech/pattern → WebSearch/WebFetch("[tech] best practices 2025")

**Decision heuristic**: Explore if patterns needed; research if unfamiliar; skip if recent exploration covers area.

**Extract key information:**
- **Brownfield**: Patterns from EPCC_EXPLORE.md or exploration, components from TECH_REQ.md
- **Greenfield**: Tech stack from TECH_REQ.md, research insights, best practices
- **Both**: Requirements (EPCC_PLAN.md, PRD.md), technical decisions (TECH_REQ.md)

### Phase 2: Create Task List

Use TodoWrite to track progress (visual feedback for users):

```markdown
Example tasks for "Implement user authentication":
[
    {
        content: "Implement JWT token generation",
        activeForm: "Implementing JWT token generation",
        status: "in_progress"
    },
    {
        content: "Add token validation middleware",
        activeForm: "Adding token validation middleware",
        status: "pending"
    },
    {
        content: "Write authentication tests",
        activeForm: "Writing authentication tests",
        status: "pending"
    }
]
```

**Task principles:**
- Clear, active voice ("Implement X", "Test Y")
- Mark "in_progress" BEFORE starting
- Mark "completed" IMMEDIATELY after finishing
- Only one task "in_progress" at a time

### Phase 3: Implement

**Mode-Specific Approaches:**

**`--tdd` mode**:
1. Write failing tests (or delegate to @test-generator)
2. Implement minimal code to pass tests
3. Refactor while keeping tests green
4. Document as you go

**`--quick` mode**:
1. Implement feature directly
2. Write basic happy-path tests
3. Run tests, fix failures
4. Skip optional validators (security, optimization)

**`--full` mode**:
1. Implement with best practices
2. Write comprehensive tests
3. Run parallel validators (@security-reviewer, @documentation-agent, @qa-engineer)
4. Address all validation findings

**Default mode**:
1. Implement following project patterns
2. Write standard test coverage
3. Generate documentation
4. Verify quality gates pass

**Don't follow rigid checklists** - adapt to actual implementation needs.

### Phase 4: Test & Validate

**Testing Approach:**

**Simple tests**: Write yourself following project patterns from EPCC_EXPLORE.md

**Complex tests**: Delegate to @test-generator with context:
```markdown
@test-generator Write comprehensive tests for user authentication.

Context:
- Framework: Express.js + TypeScript
- Testing: Jest + Supertest (from EPCC_EXPLORE.md)
- Patterns: Use test fixtures in tests/fixtures/ (see tests/users.test.ts)

Requirements (from EPCC_PLAN.md):
- JWT token generation and validation
- Login endpoint with rate limiting
- Token refresh mechanism
- Error handling for invalid credentials

Files to test:
- src/auth/jwt.ts (token generation/validation)
- src/auth/middleware.ts (authentication middleware)
- src/routes/auth.ts (login/logout endpoints)

Deliverable: Complete test suite with >90% coverage, edge cases, error scenarios
```

**Quality validation** (run from EPCC_EXPLORE.md):
- Tests pass (run test command)
- Coverage meets target (run coverage tool)
- Linting clean (run linter, auto-fix)
- Type checking passes (run type checker)

**Auto-fix pattern**: Run → fix → re-run → proceed when all pass

### Phase 5: Document Implementation

Generate `EPCC_CODE.md` with:
- **Summary**: What changed, mode used, statistics (files, lines, tests)
- **Files changed**: Created/modified with brief descriptions
- **Key decisions**: Trade-offs made, alternatives considered
- **Quality metrics**: Test results, coverage, security findings
- **Challenges**: Problems solved, remaining issues/TODOs

**Adapt format to implementation** - template is a guide, not a rigid requirement.

## Debugging Heuristics

When tests fail or bugs appear:

1. **Hypothesize**: What's the likely cause? (read error message carefully)
2. **Isolate**: Reproduce in smallest context (unit test, REPL, minimal example)
3. **Inspect**: Add logging, use debugger, check assumptions
4. **Fix**: Make smallest change that fixes root cause (not symptoms)
5. **Verify**: Re-run tests, check for side effects or regressions

**Auto-fix when possible** (formatting, imports, simple bugs). **Ask user only if**:
- Stuck after 2-3 fix attempts
- Fix requires changing requirements or approach
- Error message unclear and can't reproduce

## Refactoring Guidance

**✅ Refactor immediately when:**
- Code duplicated 3+ times → extract function/class
- Function > 50 lines → break into smaller pieces
- Unclear names → rename as you go (don't leave technical debt)
- Dead code found → delete it

**⏸️ Defer refactoring when:**
- Working code, minor cleanup → note in EPCC_CODE.md for later
- Large structural changes → create follow-up task
- Pattern emerges across entire project → document for future work

**Principle**: Leave code better than you found it, but don't let perfection block shipping.

## Sub-Agent Delegation Patterns

### Test Generation Delegation

```markdown
@test-generator [Clear task description]

Context:
- Project: [type and tech stack]
- Framework: [testing framework from EPCC_EXPLORE.md]
- Patterns: [fixture/mock patterns, example test to follow]

Requirements (from EPCC_PLAN.md):
- [Functional requirements to test]
- [Edge cases and error scenarios]

Files to test:
- [path/to/file.ts]: [What this file does]
- [path/to/another.ts]: [What this file does]

Deliverable: [What you expect back - test suite with X coverage, specific scenarios]
```

### Security Review Delegation

```markdown
@security-reviewer Scan authentication implementation for vulnerabilities.

Context:
- Project: REST API with JWT authentication
- Framework: Express.js + TypeScript
- Focus: Login/logout endpoints, token handling, session management

Files to review:
- src/auth/jwt.ts (token generation/validation)
- src/auth/middleware.ts (authentication middleware)
- src/routes/auth.ts (authentication routes)

Requirements (from EPCC_PLAN.md):
- JWT tokens with 1-hour expiration
- Refresh token mechanism
- Rate limiting on login (5 attempts per 15 min)
- Password hashing with bcrypt

Check for:
- OWASP Top 10 vulnerabilities
- JWT security best practices
- Input validation gaps
- Authentication/authorization issues

Deliverable: Security report with severity levels, specific fixes
```

### Documentation Generation Delegation

```markdown
@documentation-agent Generate API documentation for authentication endpoints.

Context:
- Project: REST API
- Framework: Express.js + TypeScript
- Doc style: OpenAPI/Swagger (from EPCC_EXPLORE.md)

Files to document:
- src/routes/auth.ts (login, logout, refresh endpoints)
- src/auth/middleware.ts (authentication middleware)

Requirements:
- API endpoint documentation (request/response formats)
- Authentication flow explanation
- Error code reference
- Usage examples

Deliverable: README section + inline JSDoc comments + OpenAPI spec
```

## Error Handling Implementation

**Agent-Compatible Pattern** (for sub-agent observability):

```typescript
// Exit code 2 + stderr for recoverable errors
try {
    const result = await operation();
    if (!result.success) {
        console.error(`ERROR: ${result.message}`);
        process.exit(2);  // Recoverable error
    }
} catch (error) {
    console.error(`ERROR: ${error.message}`);
    process.exit(2);
}

// Exit code 1 for unrecoverable errors
if (criticalResourceMissing) {
    console.error("FATAL: Database connection failed");
    process.exit(1);  // Unrecoverable
}
```

**Pattern**: Exit code 2 + stderr = agent can observe and retry. See EPCC_BEST_PRACTICES.md for full pattern.

## Quality Gates

Before marking implementation complete:

- ✅ All tests passing (run test suite)
- ✅ Coverage meets target (from EPCC_EXPLORE.md or >80% default)
- ✅ No linting errors (auto-fixed)
- ✅ Type checking passes (no type errors)
- ✅ Security scan clean (no CRITICAL/HIGH vulnerabilities)
- ✅ Documentation updated (API docs, README, inline comments)

**Don't proceed to commit phase with failing quality gates**. Fix issues or ask user if blockers.

## EPCC_CODE.md Output Template

**Forbidden patterns**:
- ❌ Exhaustive documentation for trivial changes (1-line fix ≠ comprehensive report)
- ❌ Listing every file touched (group by purpose: "3 auth files", "test suite")
- ❌ Documenting resolved challenges (focus on unresolved or blocking issues)
- ❌ Ceremonial "Next Steps" (default: run /epcc-commit unless blocked)

**Documentation structure - 4 core dimensions**:

```markdown
# Implementation: [Feature Name]

**Mode**: [--tdd/--quick/--full/default] | **Date**: [Date] | **Status**: [Complete/Blocked]

## 1. Changes ([X files], [+Y -Z lines], [A% coverage])
**Created**: [file:line] - [Purpose]
**Modified**: [file:line] - [What changed]

## 2. Quality (Tests [X%] | Security [Clean/Findings] | Docs [Updated/Skipped])
**Tests**: [X unit, Y integration, Z edge cases] - Target met: [Y/N]
**Security**: [Scan results or "Reviewed in security-reviewer output"]
**Docs**: [What was updated - API docs, README, inline comments]

## 3. Decisions
**[Decision name]**: [Choice made] | Why: [Rationale] | Alt: [Options considered]
**[Trade-off]**: Optimized [X] over [Y] because [reason]

## 4. Handoff
**Run**: `/epcc-commit` when ready
**Blockers**: [None / Describe blocking issues]
**TODOs**: [Deferred work or follow-ups]

---

## Context Used

**Planning**: [EPCC_PLAN.md approach] | **Tech**: [TECH_REQ.md insights used]
**Exploration**: [Patterns from EPCC_EXPLORE.md or autonomous /epcc-explore]
**Research**: [WebSearch/WebFetch findings applied, if any]
**Patterns**: [Code patterns/components reused]
```

**Mode adaptation** (depth varies by mode):
- **--quick mode** (~150-250 tokens): Changes + Quality summary only
  - Example: "Added dark mode toggle (3 files, +127 lines, 85% coverage). All tests passing, docs updated."

- **--full mode** (~400-600 tokens): All 4 dimensions with comprehensive detail
  - Example: Full changes breakdown + quality metrics from all validators (security, tests, docs) + decision rationale + trade-off analysis

**Completeness heuristic**: Documentation is sufficient when you can answer:
- ✅ What changed? (Files and purpose)
- ✅ Does it work? (Quality metrics)
- ✅ Why this approach? (Decisions and trade-offs)
- ✅ What's next? (Handoff to commit or blockers)

**Anti-patterns**:
- ❌ **1-line fix with 800-token report** → Violates proportionality
- ❌ **Complex feature with 150-token summary** → Missing critical decisions
- ❌ **Listing 15 resolved challenges** → Document only blockers or learnings
- ❌ **"Updated files: src/"** → Too vague, specify changed files with purpose

---

**Remember**: Match documentation depth to implementation complexity. Focus on decisions and quality, not play-by-play.

## Common Pitfalls (Anti-Patterns)

### ❌ Asking Instead of Executing
**Don't**: "Should I run the tests?" → **Do**: Run tests, show results

### ❌ Over-Delegating Simple Tasks
**Don't**: Delegate basic test writing when you have context → **Do**: Write simple tests yourself

### ❌ Ignoring Exploration Findings
**Don't**: Invent new patterns → **Do**: Follow EPCC_EXPLORE.md conventions

### ❌ Incomplete Context in Delegations
**Don't**: "@test-generator write tests" → **Do**: Provide tech stack, patterns, requirements

### ❌ Batch Task Updates
**Don't**: Complete 3 tasks then update todo list → **Do**: Mark each completed immediately

### ❌ Rigid Mode Following
**Don't**: Follow --tdd mode as rigid checklist → **Do**: Adapt TDD principles to context

## Second-Order Convergence Warnings

Even with this guidance, you may default to:

- ❌ **Following mode workflows as checklists** (work autonomously instead - modes are philosophies, not procedures)
- ❌ **Over-using sub-agents for simple tasks** (write simple tests/docs yourself when you have context)
- ❌ **Writing exhaustive documentation for small changes** (match detail to complexity - 1-line fix ≠ essay)
- ❌ **Asking permission for standard operations** (execute with safety checks, only ask when genuinely unclear)
- ❌ **Implementing everything sequentially** (consider parallel work: tests while implementation, docs while refactoring)
- ❌ **Stopping at first test pass** (verify edge cases, error handling, not just happy path)
- ❌ **Not exploring when patterns needed** (use /epcc-explore if EPCC_EXPLORE.md missing or doesn't cover area)
- ❌ **Not researching unfamiliar implementations** (use WebSearch for security-sensitive or performance-critical features)
- ❌ **Ignoring TECH_REQ.md research insights** (leverage research from TRD phase)
- ❌ **Not leveraging discovered code patterns** (use patterns from TECH_REQ.md and exploration)

## Remember

**Your role**: Autonomous, interactive implementation agent with full context and judgment.

**Work pattern**: Gather context (explore/research if needed) → Execute → Fix → Verify → Document. Ask only when blocked.

**Context gathering**: Use /epcc-explore (if patterns needed) and WebSearch (if unfamiliar tech) before implementing.

**Leverage research**: Use TECH_REQ.md insights and discovered code patterns from TRD phase.

**Sub-agents**: Helpers for specialized tasks with complete, self-contained context.

**Quality**: Tests pass, coverage met, security clean, docs updated before commit.

**Flexibility**: Adapt workflows to actual needs. Principles over procedures.

🎯 **Ready to implement. Run `/epcc-commit` when quality gates pass.**
