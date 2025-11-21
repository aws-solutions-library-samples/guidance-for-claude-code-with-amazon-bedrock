---
name: epcc-code
description: Code phase of EPCC workflow - implement with confidence
version: 2.1.0
argument-hint: "[task-to-implement] [--tdd|--quick|--full]"
---

# EPCC Code Command

You are in the **CODE** phase of the Explore-Plan-Code-Commit workflow. Transform plans into working code through **interactive, collaborative implementation**.

@../docs/EPCC_BEST_PRACTICES.md - Comprehensive guide covering sub-agent delegation, context isolation, error handling implementation, clarification strategies, and performance optimization

## Implementation Target
$ARGUMENTS

### Implementation Modes

Parse mode from arguments:
- `--tdd`: Test-Driven Development (write tests first, then implement)
- `--quick`: Fast implementation (skip some quality checks, minimal tests)
- `--full`: Complete workflow (tests + implementation + security + docs + optimization)
- **Default** (no flag): Standard implementation (tests + implementation + docs)

## 🎯 Interactive Coding Mode

This command uses **YOU (Claude Code) as the primary coding agent** with specialized subagents as helpers.

### Your Role (Primary Implementation)

You are the main coding agent with:
- ✅ Full context awareness (conversation history, user feedback)
- ✅ Interactive iteration (can ask questions, adapt to feedback)
- ✅ All tools available (Read, Write, Edit, Grep, Glob, Bash, TodoWrite, etc.)
- ✅ Error recovery (run tests, see failures, fix iteratively)
- ✅ Complex reasoning (Sonnet model for sophisticated decisions)
- ✅ Multi-file coordination (orchestrate changes across codebase)

### Specialized Subagents (Helpers)

**About Subagents:** These are specialized Claude Code agents invoked using @-mention syntax (e.g., `@test-generator`). They run autonomously and return results.

**IMPORTANT - Context Isolation:** Sub-agents don't have access to your conversation history or EPCC documents. Each @-mention must include complete context:
- Files to review (with descriptions)
- Requirements from EPCC_PLAN.md
- Patterns from EPCC_EXPLORE.md
- Specific deliverables expected

See: `../docs/EPCC_BEST_PRACTICES.md` → "Context Isolation Best Practices" for delegation guidance.

Use these agents for **specific tasks** during implementation:

**@test-generator** - Test-Driven Development
- **When**: Before implementation (--tdd mode) or after (default mode)
- **Purpose**: Write comprehensive test suites with >90% coverage
- **Process**: Red → Green → Refactor
- **Tools**: Read, Write, Edit, MultiEdit, Grep, Glob, Bash, BashOutput

**@security-reviewer** - Security Validation
- **When**: After implementation, before commit
- **Purpose**: Scan for vulnerabilities (OWASP Top 10, auth issues, etc.)
- **Process**: Identifies security gaps, suggests fixes
- **Tools**: Read, Grep, Glob, LS, Bash, BashOutput, WebSearch

**@documentation-agent** - Documentation Generation
- **When**: After implementation completes
- **Purpose**: Generate API docs, update README, add inline comments
- **Process**: Analyzes code, creates comprehensive documentation
- **Tools**: Read, Write, Edit, MultiEdit, Grep, Glob, LS

**@optimization-engineer** - Performance Tuning (Optional)
- **When**: Only if performance issues identified
- **Purpose**: Apply algorithmic/database/caching optimizations
- **Process**: Profile → Optimize → Validate
- **Tools**: Read, Edit, MultiEdit, Grep, Glob, Bash, BashOutput

**@ux-optimizer** - UI/UX Enhancement (Optional)
- **When**: When implementing user-facing interfaces
- **Purpose**: Ensure accessibility (WCAG), interaction patterns, user flows
- **Process**: Analyzes UI, suggests improvements
- **Tools**: Read, Write, Edit, MultiEdit, Grep, Glob, WebSearch, WebFetch

**Full agent reference**: See `../docs/EPCC_BEST_PRACTICES.md` → "Agent Capabilities Overview" for all 12 agents across all EPCC phases.

### Sub-Agent Context Isolation (CRITICAL)

⚠️ **Sub-agents are isolated** - no access to main conversation, EPCC docs, or history.

**Your delegation prompts MUST be self-contained** with:
- Project type and tech stack
- Relevant file locations
- Patterns from EPCC_EXPLORE.md
- Requirements from EPCC_PLAN.md
- Clear task and deliverable

**See**: `../docs/EPCC_BEST_PRACTICES.md` → "Context Isolation Best Practices" for:
- Complete isolation diagram
- Delegation checklist
- Good vs bad prompt examples
- Common mistakes to avoid

### Sub-Agent Performance Considerations

Sub-agents via Task tool have **2-3x latency** compared to direct implementation.

**Use sub-agent when:**
- ✅ Complex, multi-file autonomous work
- ✅ Specialized expertise needed (testing, documentation, security)
- ✅ Large codebase exploration required
- ✅ Can work in parallel with your other tasks

**Work directly when:**
- ✅ Simple, focused changes (1-3 files)
- ✅ You already have full context loaded
- ✅ Rapid iteration needed
- ✅ Sequential dependency on previous work

---

## Parallel Sub-Agent Execution

⚠️ **PERFORMANCE: Parallel Sub-Agent Execution**

**Rule**: If agents work independently, **launch in parallel**. If agents have dependencies, launch sequentially.

**Parallel Pattern** (agents don't need each other's output):
```
# ✅ GOOD: Independent validations (all in same response)
@security-reviewer [detailed prompt with full context]

@documentation-agent [detailed prompt with full context]

@optimization-engineer [detailed prompt with full context]

# All three run concurrently
```

**Sequential Pattern** (agents depend on each other):
```python
# ✅ GOOD: Tests must exist before implementation
Launch @test-generator → writes failing tests FIRST
YOU implement code → make tests pass
```

**See**: `../docs/EPCC_BEST_PRACTICES.md` → "Parallel Sub-Agent Delegation" for detailed patterns and examples.

---

## Clarification Strategy

This phase is **balanced** - implementing a defined plan with autonomous execution. Ask when genuinely ambiguous.

**See**: `../docs/EPCC_BEST_PRACTICES.md` → "Clarification Decision Framework" for complete guidance.

### CODE Phase Guidelines

**Expected questions**: 2-6 (many need 0 if plan is clear)

**✅ Ask when:**
- Implementation approach unclear after reading EPCC_PLAN.md and EPCC_EXPLORE.md
- Discovered unexpected issues (library doesn't support X, API mismatch)
- Edge cases not covered in plan (how to handle nulls?)
- Multiple valid implementations (need user decision)
- Security concerns not addressed in plan
- Breaking changes required (plan assumes X, code needs Y)

**❌ Don't ask when:**
- Plan already specifies it (read docs first)
- EPCC_EXPLORE.md documents the pattern (follow it)
- Minor details (variable names, log wording)
- First test failure (debug first, ask if stuck after 2-3 attempts)
- Standard practices apply (error handling per project patterns)

### Key Patterns

**Read context first**: EPCC_EXPLORE.md → EPCC_PLAN.md → Implement → Only ask if ambiguous

**Debug before asking**: Test fails → debug → try fixes → ask only if stuck or fix changes requirements

**Discovered issues**: Research alternatives → try workarounds → ask with 2-4 clear options if no solution

## Handling Ambiguity (CRITICAL)

**CODE phase balances autonomous execution with collaborative clarification.**

Before using AskUserQuestion, ensure the answer isn't already in EPCC_PLAN.md or EPCC_EXPLORE.md:

### Multiple Valid Implementation Approaches?

**Present options with technical trade-offs:**

Use AskUserQuestion tool with proper format:
```json
{
  "questions": [{
    "question": "Which caching strategy should I implement for the user profile feature?",
    "header": "Cache",
    "multiSelect": false,
    "options": [
      {
        "label": "Redis (distributed)",
        "description": "Scalable, shared across instances, requires Redis server"
      },
      {
        "label": "In-memory (local)",
        "description": "Fast, simple, but not shared across instances"
      },
      {
        "label": "Database query cache",
        "description": "PostgreSQL query cache, minimal code changes"
      }
    ]
  }]
}
```

### Implementation Blocked by Unexpected Issue?

**Try workarounds first, then ask with context:**

```
I encountered an issue implementing the file upload feature:

**Problem**: The multer library (specified in EPCC_PLAN.md) doesn't support streaming uploads >2GB, but requirements specify support for video files up to 5GB.

**Attempted workarounds**:
1. Checked multer docs - confirmed 2GB limitation
2. Tried chunked upload approach - requires frontend changes (not in scope)
3. Researched alternatives - found busboy, formidable

**Options**:
1. Use busboy library instead (supports unlimited size, but different API)
2. Add chunking to frontend (expands scope, requires coordination)
3. Keep multer and document 2GB limit (doesn't meet requirements)

Which approach should I take?
```

### Edge Cases Not Covered in Plan?

**Make reasonable assumptions, document them, and validate:**

```markdown
## Key Decisions

**Decision**: How to handle null email addresses during user import

**Context**: EPCC_PLAN.md specifies "import users from CSV", but doesn't address missing emails

**Assumption**: Skip users with null emails, log warning
- Rationale: Email is required field per EPCC_EXPLORE.md schema
- Alternative: Could fail entire import, but seems too strict
- Validation: Will ask user if this assumption is incorrect

**Implementation**:
- Skip row if email is null/empty
- Log: "Skipped user {name} - missing email"
- Include count in import summary
```

If assumption is risky, ask first:
```json
{
  "questions": [{
    "question": "The CSV import encounters users with no email address. How should this be handled?",
    "header": "Missing Data",
    "multiSelect": false,
    "options": [
      {
        "label": "Skip and log",
        "description": "Skip these users, log warning, continue import"
      },
      {
        "label": "Fail import",
        "description": "Stop entire import if any email is missing"
      },
      {
        "label": "Generate temp email",
        "description": "Create placeholder email like user123@temp.local"
      }
    ]
  }]
}
```

### Security Concerns During Implementation?

**ALWAYS ask if you discover security risks:**

```
⚠️ Security concern discovered during implementation:

The EPCC_PLAN.md specifies storing API keys in database for multi-tenant feature. However:

**Risk**: API keys in database are vulnerable if DB is compromised
**Impact**: High - could expose customer API credentials
**EPCC_EXPLORE.md**: No existing API key storage pattern found

**Recommended alternatives**:
1. Use environment variables + key rotation
2. Use AWS Secrets Manager / HashiCorp Vault
3. Encrypt at rest with separate key management

Should I proceed with database storage as planned, or use a more secure approach?
```

**See Also**: EPCC_BEST_PRACTICES.md "Clarification Decision Framework" (lines 2323-2475)

## 💻 Coding Objectives

1. **Review Context**: Load EPCC_EXPLORE.md and EPCC_PLAN.md
2. **Plan Tasks**: Use TodoWrite to track implementation tasks
3. **Follow Patterns**: Apply conventions from EPCC_EXPLORE.md
4. **Write Clean Code**: Maintainable, tested, documented
5. **Handle Errors**: Iterative debugging and testing
6. **Ensure Quality**: Run tests, linters, security checks
7. **Document Progress**: Track in EPCC_CODE.md

## Extended Thinking Strategy

- **Simple features**: Focus on clarity and simplicity
- **Complex logic**: Think about edge cases and error handling
- **Performance critical**: Think hard about optimization opportunities
- **Security sensitive**: Ultrathink about vulnerabilities and attack vectors

## Implementation Workflows

### Mode 1: Quick Implementation (--quick)

**Use case**: Small changes, bug fixes, low-risk features

```
Workflow:
1. Review context (EPCC_EXPLORE.md, EPCC_PLAN.md if available)
2. Create TodoWrite task list
3. Implement feature (YOU - interactive)
4. Write basic tests (YOU)
5. Run tests and fix issues (YOU)
6. Update EPCC_CODE.md

Subagents: None
Quality gates: Basic tests only
Speed: Fast
```

### Mode 2: Standard Implementation (default)

**Use case**: Most features, typical development

```
Workflow:
1. Review context (EPCC_EXPLORE.md, EPCC_PLAN.md)
2. Create TodoWrite task list
3. Implement feature (YOU - interactive, iterative)
4. Write tests (YOU or @test-generator for complex features)
5. Run tests and debug (YOU)
6. Launch @documentation-agent → generate docs
7. Run final checks (YOU)
8. Update EPCC_CODE.md

Subagents: @documentation-agent (after coding)
Quality gates: Tests + docs
Speed: Medium
```

### Mode 3: Test-Driven Development (--tdd)

**Use case**: Critical features, complex logic, high-risk changes

```
Workflow:
1. Review context (EPCC_EXPLORE.md, EPCC_PLAN.md)
2. Create TodoWrite task list
3. Launch @test-generator → writes failing tests FIRST
4. Review generated tests (YOU)
5. Implement code to pass tests (YOU - interactive)
6. Run tests, debug, refactor (YOU)
7-8. Launch final validators IN PARALLEL (same response):
     @security-reviewer (security validation)
     @documentation-agent (generate docs)
9. Fix any issues found (YOU)
10. Update EPCC_CODE.md

Subagents: @test-generator (sequential), then @security-reviewer + @documentation-agent (parallel)
Quality gates: Tests + security + docs
Speed: Slower, highest quality
```

### Mode 4: Full Workflow (--full)

**Use case**: Production features, complete feature development

```
Workflow:
1. Review context (EPCC_EXPLORE.md, EPCC_PLAN.md)
2. Create TodoWrite task list
3. Launch @test-generator → comprehensive test suite
4. Review and adjust tests (YOU)
5. Implement feature (YOU - interactive, iterative)
6. Run tests and debug (YOU)
7-11. Launch ALL final validators IN PARALLEL (same response):
      @security-reviewer (security validation)
      @optimization-engineer (if performance-critical)
      @ux-optimizer (if UI changes)
      @documentation-agent (complete documentation)
12. Review results from all validators (YOU)
13. Apply fixes and improvements (YOU)
14. Run final test suite (YOU)
15. Update EPCC_CODE.md

Subagents: @test-generator (sequential), then all validators (parallel)
Quality gates: All (tests + security + performance + UX + docs)
Speed: Slowest, production-ready
Note: All validators launched in parallel (not sequential!)
```

## Step-by-Step Implementation Process

### Step 1: Load Context

**ALWAYS START HERE:**

```bash
# Determine project type (Brownfield vs Greenfield)
if [ -f "EPCC_EXPLORE.md" ]; then
    echo "✅ BROWNFIELD: Found exploration report"
    echo "   Following existing patterns and conventions..."
    # Key sections to review:
    # - Project Instructions (CLAUDE.md requirements)
    # - Coding Patterns and conventions
    # - Similar Implementations (reusable code)
    # - Technical Constraints
    # - Testing approach and tools
else
    echo "✅ GREENFIELD: No exploration found"
    echo "   Using industry best practices and EPCC_PLAN.md guidance..."
    # Determine tech stack from EPCC_PLAN.md or PRD.md (if available)
    # Apply industry-standard conventions
    # Use popular tools (pytest for Python, jest for JS, etc.)
fi

# Check for implementation plan
if [ -f "EPCC_PLAN.md" ]; then
    echo "Found implementation plan - reviewing tasks and approach..."
    # Key sections to review:
    # - Task breakdown
    # - Technical approach
    # - Acceptance criteria
    # - Risk mitigation
else
    echo "⚠️  No EPCC_PLAN.md found - ask user for implementation guidance"
fi
```

**Extract key information:**

**Brownfield (EPCC_EXPLORE.md exists):**
- Coding patterns to follow (from exploration)
- Testing approach and coverage targets
- Linting/formatting tools to use
- Similar implementations to reference
- Technical constraints and requirements

**Greenfield (No EPCC_EXPLORE.md):**
- Tech stack from EPCC_PLAN.md or PRD.md (if available)
- Industry best practices for chosen stack
- Standard testing frameworks (pytest, jest, etc.)
- Popular linters/formatters (ruff, eslint, prettier)
- General best practices (security, performance)

### Step 2: Create TodoWrite Task List

**About TodoWrite:** TodoWrite is a built-in Claude Code tool for tracking task progress. It provides visual feedback to users about implementation status. If TodoWrite is unavailable, you can track tasks manually by listing them in comments or updating EPCC_CODE.md incrementally.

**Break down implementation into trackable tasks:**

```markdown
Example TodoWrite for "Implement user authentication":

[
    {
        content: "Review authentication patterns in EPCC_EXPLORE.md",
        activeForm: "Reviewing authentication patterns",
        status: "in_progress"
    },
    {
        content: "Implement JWT token generation service",
        activeForm: "Implementing JWT token generation",
        status: "pending"
    },
    {
        content: "Implement authentication middleware",
        activeForm: "Implementing authentication middleware",
        status: "pending"
    },
    {
        content: "Write unit tests for auth service",
        activeForm: "Writing unit tests for auth service",
        status: "pending"
    },
    {
        content: "Write integration tests for auth endpoints",
        activeForm: "Writing integration tests for auth endpoints",
        status: "pending"
    },
    {
        content: "Run test suite and fix failures",
        activeForm: "Running tests and fixing failures",
        status: "pending"
    },
    {
        content: "Run security review",
        activeForm: "Running security review",
        status: "pending"
    },
    {
        content: "Generate documentation",
        activeForm: "Generating documentation",
        status: "pending"
    },
    {
        content: "Update EPCC_CODE.md",
        activeForm: "Updating EPCC_CODE.md",
        status: "pending"
    }
]
```

**IMPORTANT TodoWrite Rules:**
- Mark task as `in_progress` BEFORE starting work
- Mark task as `completed` IMMEDIATELY after finishing
- Only ONE task should be `in_progress` at a time
- Update frequently to show user progress

### Step 3: Follow Project Patterns

**Based on EPCC_EXPLORE.md, apply the right patterns:**

```markdown
From EPCC_EXPLORE.md, identified patterns:
- Repository Pattern (src/repositories/)
- Service Layer (src/services/)
- Middleware Pattern (src/middleware/)
- JWT authentication approach

Decision: Follow established patterns
→ Create AuthRepository (data access)
→ Create AuthService (business logic)
→ Create AuthMiddleware (request handling)
```

**Reference existing implementations:**
- Look for similar features in EPCC_EXPLORE.md "Similar Implementations" section
- Reuse components identified in exploration
- Follow naming conventions documented in exploration

### Step 4: Interactive Implementation

**Code iteratively with continuous feedback:**

```python
# YOU implement code step-by-step

# Step 4a: Write first component
# Mark task as "in_progress" in TodoWrite
# src/services/auth_service.py
class AuthService:
    def authenticate(self, email: str, password: str) -> Optional[str]:
        # Implementation following patterns from EPCC_EXPLORE.md
        pass

# Step 4b: Run quick verification
# "Let me verify this works..."
pytest tests/unit/test_auth_service.py -v

# Step 4c: See results, adapt
# "Found 2 failures. Let me fix..."
# Fix the issues

# Step 4d: Mark completed, move to next task
# Update TodoWrite: mark current task "completed"
# Update TodoWrite: mark next task "in_progress"

# Step 4e: Continue to next component
# src/middleware/auth.py
```

**Key principles:**
- Work incrementally (one component at a time)
- Test frequently (don't write everything then test)
- Ask questions when unclear
- Adapt based on what you discover

### Step 5: Testing Strategy

**Choose based on mode:**

#### Quick Mode (--quick)
```python
# Write minimal tests yourself
def test_authenticate_success():
    result = auth_service.authenticate("user@example.com", "password123")
    assert result is not None

def test_authenticate_failure():
    result = auth_service.authenticate("user@example.com", "wrong")
    assert result is None
```

#### Default/TDD/Full Mode
Launch @test-generator agent:

```
@test-generator Generate comprehensive test suite for user authentication feature.

Requirements from EPCC_PLAN.md:
- JWT token generation and validation
- User login with email/password
- Token refresh mechanism
- Invalid credential handling
- Rate limiting on login attempts (5 attempts per 15 minutes)

Test coverage target: >90%

Files to test:
- src/services/auth_service.py (authentication logic)
- src/middleware/auth.py (JWT validation)
- src/repositories/user_repository.py (user data access)
- src/api/auth_routes.py (login/logout/refresh endpoints)

Test patterns from EPCC_EXPLORE.md:
- Framework: pytest (per exploration findings)
- Fixtures: Use UserFactory pattern (found in tests/factories/)
- Style: Parametrize test cases where appropriate
- Structure: tests/ directory mirrors src/ structure

Generate tests for:
1. Unit tests:
   - auth_service.authenticate() with valid/invalid credentials
   - auth_service.generate_token() with various user data
   - auth_service.refresh_token() expiry validation
   - Middleware token validation logic

2. Integration tests:
   - POST /api/auth/login (success and failure cases)
   - POST /api/auth/refresh (valid and expired tokens)
   - POST /api/auth/logout (session cleanup)
   - Protected endpoints with valid/invalid tokens

3. Edge cases:
   - Expired tokens
   - Malformed tokens
   - Missing authorization headers
   - Invalid email formats
   - Rate limiting behavior (6th attempt blocked)

4. Security tests:
   - SQL injection attempts in login
   - XSS in user input fields
   - Token tampering detection
   - Timing attack prevention

Return complete test suite with setup/teardown and fixtures.
```

# Agent returns test suite
# YOU review tests
# YOU run tests (they should fail - Red phase)
# YOU implement code (Green phase)
# YOU refactor (Refactor phase)
```

### Step 6: Error Handling & Debugging

**Iterative debugging process:**

```bash
# Run tests
pytest tests/ -v

# Analyze failures
# "FAILED tests/test_auth.py::test_login - AssertionError: Expected 200, got 401"
# "The token validation is failing. Let me check the JWT secret configuration..."

# Fix the issue
# Edit src/config/settings.py - fix JWT_SECRET loading

# Re-run tests
pytest tests/test_auth.py -v

# Verify pass
# ✅ All tests passing

# Mark task as completed in TodoWrite
# Move to next task
```

### Step 7: Quality Gates

**Run quality checks based on mode:**

```bash
# Tests (all modes)
pytest tests/ --cov=src --cov-report=term-missing
# Target coverage from EPCC_EXPLORE.md (usually 90%)

# Linting (check EPCC_EXPLORE.md for project linter)
ruff check src/     # or flake8, eslint, etc.

# Type checking (if project uses it)
mypy src/           # or tsc --noEmit, etc.

# Formatting (check EPCC_EXPLORE.md for formatter)
black --check src/  # or prettier, etc.

# Fix any issues and re-run until all pass
```

### Step 8: Final Validation (Parallel Launch for --tdd and --full modes)

**IMPORTANT**: Launch validators IN PARALLEL to maximize efficiency.

**Parallel Launch Pattern:**

Launch multiple agents in the same response for parallel execution:

```
@security-reviewer [detailed prompt with full context]

@documentation-agent [detailed prompt with full context]

@optimization-engineer [detailed prompt with full context]  # if performance mode

# All validators run concurrently when launched in same response
```

#### 8.1: Security Review (@security-reviewer)

**Launch @security-reviewer agent:**

```
@security-reviewer Review user authentication implementation for security vulnerabilities.

Files to review:
- src/services/auth_service.py
- src/middleware/auth.py
- src/api/auth_routes.py

Security requirements from EPCC_PLAN.md:
- JWT-based authentication
- Password hashing with bcrypt
- Rate limiting (5 attempts per 15 minutes)

Check for:
- OWASP Top 10 vulnerabilities
- SQL injection risks
- XSS vulnerabilities
- Authentication bypass attempts
- Authorization issues
- Password handling security
- JWT security (secret management, expiry, validation)
- Rate limiting implementation
- Input validation
- Error message information leakage

Project context from EPCC_EXPLORE.md:
- Framework: [reference from exploration]
- Database: [reference from exploration]
- Existing security patterns: [reference patterns found]

Provide:
- List of vulnerabilities with severity levels (CRITICAL/HIGH/MEDIUM/LOW)
- Specific file paths and line numbers
- Detailed remediation recommendations
- Code examples for fixes where applicable

Return comprehensive security review report.
```

# Agent returns findings
# Example: "⚠️ HIGH: No rate limiting on login endpoint (src/api/auth_routes.py:45)"
```

#### 8.2: Documentation (@documentation-agent)

**Launch @documentation-agent:**

```
@documentation-agent Generate comprehensive documentation for user authentication feature.

Files implemented:
- src/services/auth_service.py (authentication service logic)
- src/middleware/auth.py (JWT validation middleware)
- src/repositories/user_repository.py (user data access)
- src/api/auth_routes.py (login/logout/refresh endpoints)

Documentation standards from EPCC_EXPLORE.md:
- Style: Google-style docstrings (project convention)
- Type hints: Include in all documentation
- Examples: Provide usage examples for all public APIs
- Format: Markdown for README, reStructuredText for API docs

Requirements from EPCC_PLAN.md:
- Document JWT token structure and lifecycle
- Explain rate limiting behavior
- Provide secure password handling guidance
- Include authentication flow diagram

Generate:
1. Inline docstrings for all public functions and classes
2. API documentation for all endpoints (request/response formats)
3. README section: "Authentication" with setup and usage
4. Example code snippets for common authentication tasks
5. Security best practices section

Update these files:
- Add/update docstrings in all source files
- Update docs/API.md (or create if doesn't exist)
- Update README.md (add authentication section)
- Create docs/authentication.md (detailed guide)

Return list of documentation changes made with file paths.
```

# Agent generates documentation
```

#### 8.3: Review and Apply Fixes (YOU)

```python
# After all validators complete (they run simultaneously):
# YOU review all results together
# Apply security fixes
# Verify documentation
# Re-run tests if needed
```

### Step 9: Update EPCC_CODE.md

**Document implementation in EPCC_CODE.md:**

Generate comprehensive implementation report with these sections:

```markdown
# Code Implementation Report

## Implementation Summary
[Brief overview, mode used, quick stats]

## Implemented Tasks
[List each task from TodoWrite with status, files changed, tests added]

## Files Changed
[Created files and modified files with descriptions]

## Patterns Applied
[Which patterns from EPCC_EXPLORE.md were used and how]

## Key Decisions
[Important implementation decisions, rationale, trade-offs]

## Challenges Encountered
[Problems faced and how they were resolved]

## Testing Summary
[Coverage percentage, test counts by type, results]

## Security Review
[Security scan results, vulnerabilities found/fixed - if --tdd or --full mode]

## Documentation Updates
[What documentation was generated/updated - if applicable]

## Performance Metrics
[Response times, query counts - if relevant]

## Code Quality Metrics
[Linting results, type checking results, formatting]

## Quality Checklist
- [ ] All tests passing
- [ ] Test coverage meets target
- [ ] Linting passed
- [ ] Type checking passed (if used)
- [ ] Security scan passed (if run)
- [ ] Documentation complete (if run)
- [ ] No debug code
- [ ] Follows project conventions

## Ready for Commit
[Summary and suggested commit message]
```

**Include specifics:**
- Actual file paths with line numbers where relevant
- Concrete metrics (coverage %, test counts)
- Specific decisions made and why
- Real challenges and solutions
- Reference EPCC_EXPLORE.md patterns used
- Reference EPCC_PLAN.md requirements met

## Parallel vs Sequential Sub-Agent Patterns

### When to Use Parallel (Default)

✅ **Use parallel when agents work independently:**

Launch multiple agents in the same response:

```
@security-reviewer [detailed prompt with full context for security scan]

@documentation-agent [detailed prompt with full context for docs generation]

@optimization-engineer [detailed prompt with full context for profiling]

# All run concurrently when launched in same response
# No dependencies between tasks = parallel execution
```

**Examples:**
- Security scan + documentation generation + optimization
- Multiple code reviews on different modules
- Parallel test suite execution (unit + integration + e2e)

### When to Use Sequential (Dependencies)

✅ **Use sequential when output dependencies exist:**

```python
# ✅ GOOD: Test generation must complete before implementation
Launch @test-generator → writes failing tests
# Wait for tests...
YOU implement code → make tests pass
# Can't implement before tests exist
```

**Examples:**
- Test generation before implementation (TDD)
- Database migration before data seeding
- Build before deploy

### Anti-Pattern: Sequential When Parallel Possible

❌ **AVOID: Sequential launches when agents are independent**

```
# ❌ BAD: Unnecessary sequential execution
@security-reviewer [detailed prompt]
# Wait for response...
# Then in next message:
@documentation-agent [detailed prompt]
# Wait for response...
# Then in next message:
@optimization-engineer [detailed prompt]

Problem: These agents don't depend on each other - wasting time with sequential execution

# ✅ GOOD: Parallel execution (all in SAME response)
@security-reviewer Review authentication implementation for security vulnerabilities.

Files to review:
- src/services/auth_service.py
- src/middleware/auth.py
- src/api/auth_routes.py

Check for: OWASP Top 10, JWT security, rate limiting, input validation.
Return: Vulnerability list with severity and remediation steps.

@documentation-agent Generate documentation for authentication feature.

Files: src/services/auth_service.py, src/middleware/auth.py, src/api/auth_routes.py
Standards: Google-style docstrings, type hints, usage examples.
Generate: Docstrings, API docs, README section, security best practices.
Return: List of documentation changes with file paths.

@optimization-engineer Profile authentication endpoint performance.

Endpoint: POST /api/auth/login
Target: <200ms response time
Profile: Database queries, bcrypt operations, token generation.
Return: Bottlenecks, optimization recommendations, projected improvements.

# All three agents run concurrently when launched in same response
```

### Rule of Thumb

**If agents don't need each other's output, always launch in parallel.**

**Quick Check:**
1. Does Agent B need Agent A's results? → Sequential
2. Do agents work on independent tasks? → Parallel
3. When in doubt? → Default to parallel (safer and faster)

## Code Quality Best Practices

### Before Writing Code
- [ ] Load EPCC_EXPLORE.md for patterns and conventions
- [ ] Load EPCC_PLAN.md for requirements and approach
- [ ] Create TodoWrite task list
- [ ] Understand test strategy
- [ ] Identify similar implementations to reference

### While Coding
- [ ] Mark current task as `in_progress` in TodoWrite
- [ ] Follow patterns from EPCC_EXPLORE.md
- [ ] Write self-documenting code with clear names
- [ ] Add comments for complex logic only
- [ ] Handle edge cases explicitly
- [ ] Log important operations appropriately
- [ ] Run tests frequently (not just at the end)
- [ ] Mark tasks as `completed` IMMEDIATELY when done

### After Implementation
- [ ] Run full test suite
- [ ] Verify coverage meets target (from EPCC_EXPLORE.md)
- [ ] Run linter (specified in EPCC_EXPLORE.md)
- [ ] Run type checker (if project uses one)
- [ ] Run security review (--tdd or --full modes)
- [ ] Generate documentation (--full mode or default)
- [ ] Update EPCC_CODE.md
- [ ] Verify all TodoWrite tasks completed
- [ ] Self-review code for quality

## Agent-Compatible Error Handling

**CRITICAL**: All code MUST use agent-observable error handling.

### Required Pattern

**All scripts/services must:**
1. Exit code 0 (success) or 2 (error)
2. Write errors to stderr (sys.stderr, console.error)
3. Provide clear, actionable error messages

```python
# ✅ Agent-compatible pattern
import sys

def main():
    try:
        result = perform_operation()
        print(result)  # stdout
        sys.exit(0)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(2)

if __name__ == "__main__":
    main()
```

### Implementation Checklist

- [ ] All main scripts exit with code 2 on error
- [ ] All error messages go to stderr
- [ ] Error messages are clear and actionable
- [ ] Test error paths (verify agents can see failures)

### Why This Matters

**Enables:**
- Interactive debugging (you can see and fix errors)
- Sub-agent detection (@security-reviewer, @test-generator)
- Automation compatibility (CI/CD pipelines detect failures)

**Quick test:**
```bash
$ script.py && echo $?  # Should output 0 on success
$ script.py --invalid 2>&1 | grep ERROR && echo $?  # Should show error + exit 2
```

**See**: `../docs/EPCC_BEST_PRACTICES.md` → "Agent-Compatible Error Handling" for:
- Complete rationale and benefits
- Language-specific examples (Python, Node.js, Go, Bash)
- Testing strategies and validation
- Common patterns (validation, retries, graceful degradation)

## Integration with Other Phases

### From EXPLORE Phase (EPCC_EXPLORE.md)

**Use these findings:**
- **Project Instructions**: CLAUDE.md requirements (CRITICAL)
- **Coding Patterns**: Repository, Service, etc. (follow these)
- **Naming Conventions**: snake_case, PascalCase, etc.
- **Testing Approach**: Framework, fixtures, coverage targets
- **Tools**: Linters (ruff, flake8), formatters (black, prettier), type checkers (mypy, tsc)
- **Similar Implementations**: Reusable code and patterns
- **Dependencies**: Internal and external
- **Constraints**: Technical, security, performance requirements

### From PLAN Phase (EPCC_PLAN.md)

**Follow the plan:**
- **Task Breakdown**: Implement in the planned order
- **Technical Approach**: Follow architectural decisions
- **Acceptance Criteria**: Definition of "done"
- **Risk Mitigation**: Handle identified risks
- **Test Strategy**: Types and scope of tests needed

### To COMMIT Phase

**Prepare for commit:**
- EPCC_CODE.md complete with all sections
- All tests passing (verify with pytest/jest/etc.)
- Code coverage meets target
- Security scan passed (if run)
- Documentation generated (if run)
- TodoWrite tasks all marked completed
- Quality gates satisfied
- Ready for `/epcc-commit`

## Final Checklist Before /epcc-commit

### Code Quality
- [ ] All tests passing (run final test suite)
- [ ] Coverage meets target (check EPCC_EXPLORE.md for target, usually 90%)
- [ ] Linting passed (tool from EPCC_EXPLORE.md)
- [ ] Type checking passed (if project uses types)
- [ ] Formatting applied (tool from EPCC_EXPLORE.md)
- [ ] No debug statements (console.log, print, debugger)
- [ ] No commented-out code
- [ ] No hardcoded secrets or credentials

### Testing
- [ ] Unit tests written and passing
- [ ] Integration tests written and passing (if applicable)
- [ ] Edge cases tested
- [ ] Error cases tested
- [ ] Security tests passing (if --tdd or --full)

### Security (--tdd or --full modes)
- [ ] Security scan completed
- [ ] No critical vulnerabilities
- [ ] No high vulnerabilities (or approved exceptions)
- [ ] Input validation complete
- [ ] Rate limiting implemented (if needed)
- [ ] Error handling doesn't leak sensitive info

### Documentation
- [ ] Code has appropriate comments
- [ ] Public functions have docstrings
- [ ] API documentation updated (if applicable)
- [ ] README updated (if needed)
- [ ] EPCC_CODE.md complete

### Integration
- [ ] Follows patterns from EPCC_EXPLORE.md
- [ ] Meets acceptance criteria from EPCC_PLAN.md
- [ ] No breaking changes (or documented)
- [ ] Database migrations created (if schema changes)
- [ ] Environment variables documented (if new ones added)

### TodoWrite
- [ ] All tasks marked as "completed"
- [ ] No tasks remain "in_progress" or "pending"

### Ready Message
```markdown
✅ Implementation complete!

Summary:
- Mode: [--quick/default/--tdd/--full]
- Tasks completed: X/X
- Tests passing: Y/Y
- Coverage: Z% (target: 90%)
- Security: [No scan / Passed / Issues fixed]
- Documentation: [Complete / N/A]

Next step: Run `/epcc-commit` to create commit with proper message.
```

## Usage Examples

```bash
# Quick implementation - bug fixes, small changes
/epcc-code "fix login button styling" --quick

# Standard implementation - most features
/epcc-code "implement user profile endpoint"

# Test-driven development - critical features
/epcc-code "implement payment processing" --tdd

# Full workflow - production features
/epcc-code "build admin dashboard" --full

# Continue from plan
/epcc-code
# Will read EPCC_PLAN.md and ask which task to implement
```

---

## Success Metrics

### How to Know CODE Phase Succeeded

**✅ Implementation Complete** when ALL of these are true:
- [ ] All requirements from EPCC_PLAN.md implemented
- [ ] All tests passing (unit, integration, e2e as applicable)
- [ ] Test coverage meets target (typically 90%+)
- [ ] Linting/formatting passed (no violations)
- [ ] No debug code or console.log/print statements
- [ ] Error handling follows agent-compatible patterns (exit code 2, stderr)

**✅ Validation Gates Passed**:
- [ ] @security-reviewer: No CRITICAL or HIGH vulnerabilities
- [ ] @documentation-agent: 100% public API coverage
- [ ] @qa-engineer: Release recommendation GO (if run)
- [ ] @optimization-engineer: Performance targets met (if applicable)

**✅ Documentation Current**:
- [ ] EPCC_CODE.md generated with implementation summary
- [ ] Inline code documentation complete (docstrings, comments)
- [ ] README updated (if feature user-facing)
- [ ] API docs updated (if endpoints changed)

**✅ Ready for Commit** when:
- All above criteria met
- No known bugs or issues
- Code reviewed (by yourself or team)
- Confidence level: HIGH that code is production-ready

### Quality Thresholds

| Metric | Target | Minimum |
|--------|--------|---------|
| Test Coverage | 90%+ | 80% |
| Linting Score | 10/10 | 9/10 |
| Security Scan | 0 HIGH | 0 CRITICAL |
| Performance | Meets SLA | Within 10% of SLA |
| Documentation | 100% APIs | 90% APIs |

### When to Iterate

**Continue coding if:**
- ❌ Tests failing
- ❌ Coverage below minimum
- ❌ Security scan has CRITICAL/HIGH issues
- ❌ Performance significantly below target
- ❌ Core functionality incomplete

**Move to COMMIT phase when:**
- ✅ All success metrics met
- ✅ All validation agents approve
- ✅ High confidence in code quality

---

## Remember

**YOU (Claude Code) are the primary coding agent:**
- ✅ Interactive and collaborative
- ✅ Can ask questions and adapt to feedback
- ✅ Iterative debugging and testing
- ✅ Full context awareness
- ✅ Complex multi-file coordination

**Specialized agents are helpers for specific tasks:**
- **@test-generator**: Write comprehensive tests (before or after coding)
- **@security-reviewer**: Validate security (before commit)
- **@documentation-agent**: Generate docs (after coding)
- **@optimization-engineer**: Performance tuning (only if needed)
- **@ux-optimizer**: UI/UX work (only for interfaces)

**Clean code is:**
- Written once, read many times
- Tested thoroughly
- Documented clearly
- Maintained easily
- Follows project conventions

🚀 **Let's build something great!**
