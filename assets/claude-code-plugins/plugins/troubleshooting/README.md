# Troubleshooting Plugin

> **Systematic Debugging with Ask-for-Help Mechanism to Prevent Spinning Wheels**

Methodical 5-stage troubleshooting workflow that diagnoses problems efficiently while preventing endless debugging cycles through built-in collaboration triggers.

## Overview

The Troubleshooting Plugin provides a single powerful slash command:

**`/troubleshoot`** - Systematic Debugging Workflow

A 5-stage process (Context Gathering → Classification → Hypothesis Generation → Methodical Testing → Solution Documentation) with an "ask-for-help" mechanism that triggers after 3 failed attempts or when complex issues are detected.

## Quick Start

### Installation

```bash
# Install from marketplace
/plugin install troubleshooting@aws-claude-code-plugins
```

### Basic Usage

**When you encounter an error**:
```bash
/troubleshoot "TypeError: Cannot read property 'name' of undefined"
```

**Or start interactively**:
```bash
/troubleshoot
```

The command will:
1. Gather complete context (error messages, logs, recent changes)
2. Classify the problem (syntax, logic, performance, etc.)
3. Form specific, testable hypotheses
4. Test one hypothesis at a time
5. Document the solution in `TROUBLESHOOT.md`

**Key Feature**: If stuck after 3 attempts or facing complex issues (race conditions, architecture), it **asks for your help** rather than spinning wheels.

## Command

### `/troubleshoot` - Systematic Debugging Workflow

**Purpose**: Debug problems methodically with built-in ask-for-help mechanism.

**Usage**:
```bash
/troubleshoot [error-description-or-empty-for-interactive]
```

**What it does**:
- **Stage 1**: Context Gathering (error message, stack trace, recent changes, logs, configuration)
- **Stage 2**: Problem Classification (syntax, logic, runtime, performance, config, security, network, architecture)
- **Stage 3**: Hypothesis Generation (specific, testable theories with evidence)
- **Stage 4**: Methodical Testing (one change at a time, record results)
- **Stage 5**: Solution Documentation (root cause, fix, prevention, lessons learned)

**Output**: `TROUBLESHOOT.md` documenting the entire debugging session

**Duration**: 5-60 minutes depending on complexity

---

## Core Principles

### 1. Gather Before Guessing
Never jump to solutions. Always collect:
- Full error message and stack trace
- Recent changes (git log, git diff)
- Configuration and environment variables
- System logs and related errors

### 2. One Change at a Time
- Make ONE specific change
- Test immediately
- Record result (success/failure)
- Revert if failed
- **Never stack multiple changes**

### 3. Ask for Help Early
**Triggers**:
- ✋ After 3 failed test attempts
- 🏗️ Complex issue detected (race condition, architectural)
- 🔐 Security-critical issue
- 🔥 Production system at risk
- ❓ Unfamiliar technology/domain

**What happens**:
- Presents what was tried and why
- Asks specific questions about domain knowledge or expected behavior
- Offers multiple paths forward
- **Stops spinning wheels silently**

### 4. Document Everything
All troubleshooting sessions saved in `TROUBLESHOOT.md`:
- Problem description and context
- All hypotheses tested
- What worked and what didn't
- Final solution and why it worked
- Prevention measures
- Lessons learned

## Features

### 🎯 Systematic 5-Stage Process

Never skip stages. Each stage has specific deliverables:

**Stage 1: Context Gathering (2-5 min)**
- Checklist of information to collect
- Ensures complete picture before attempting fixes

**Stage 2: Problem Classification (1-2 min)**
- Categorizes into 8 types (syntax, logic, runtime, performance, config, security, network, architecture)
- Determines complexity and approach
- Estimates fix time

**Stage 3: Hypothesis Generation (2-3 min)**
- Forms specific, testable hypotheses (not vague guesses)
- Prioritizes by likelihood
- Defines exact tests to validate each

**Stage 4: Methodical Testing (Variable time)**
- Tests one hypothesis at a time
- Records result for each attempt
- Reverts if failed (no stacking changes)

**Stage 5: Solution Documentation (2-3 min)**
- Records root cause and fix
- Explains why solution worked
- Defines prevention measures
- Captures lessons learned

### ⚠️ Ask-for-Help Mechanism

**Immediate Triggers**:
- 🏗️ Architectural issues (race conditions, design flaws)
- 🔐 Security-critical issues
- 🔥 Production impact
- ❓ Unfamiliar territory

**After 3 Attempts**:
- Tested 3 hypotheses without progress
- Error persists or worsens

**What You Get**:
```markdown
⚠️ ASKING FOR HELP

### What I've Tried
1. Attempt 1: [Summary and result]
2. Attempt 2: [Summary and result]
3. Attempt 3: [Summary and result]

### Current Understanding
[What I know so far]

### Why I'm Stuck
[Specific reason]

### Questions for You
1. [Specific question]
2. [Specific question]

### Possible Paths Forward
Option A: [Approach with pros/cons]
Option B: [Approach with pros/cons]
Option C: [Escalate to expert]

Which path should we take?
```

**Never Asks for Simple Issues**:
- ✅ Handles autonomously: Syntax errors, import errors, simple config issues, obvious logic errors

### 📊 Problem Classification

**8 Error Categories**:

| Category | Complexity | Example |
|----------|-----------|---------|
| 🔤 Syntax Error | Simple (< 5 min) | Missing semicolon, typo, incorrect syntax |
| 🧮 Logic Error | Medium (15-30 min) | Off-by-one error, wrong operator, incorrect algorithm |
| ⚡ Runtime Error | Medium (10-20 min) | Null reference, type mismatch, out of bounds |
| 🐌 Performance Issue | High (30-60 min) | N+1 queries, memory leak, inefficient algorithm |
| ⚙️ Configuration Issue | Simple-Medium (5-15 min) | Wrong env var, missing dependency, incorrect settings |
| 🔐 Security Issue | High (30+ min) | Exposed secrets, SQL injection, XSS vulnerability |
| 🌐 Network/Integration | Medium-High (20-40 min) | API failures, timeout errors, CORS issues |
| 🏗️ Architectural Issue | Very High (hours-days) | Race conditions, circular dependencies, design flaws |

### 📝 Comprehensive Documentation

**TROUBLESHOOT.md Structure**:
```markdown
# Troubleshooting Session: [Date/Time]

## Problem Description
[Error and context]

## Context Gathered
- Error message
- Recent changes
- Environment state

## Problem Classification
- Category, Complexity, Approach

## Hypotheses Tested
### Attempt 1: [Hypothesis]
- Change Made
- Expected vs Actual
- Result

[... more attempts ...]

## Solution Found
- Root Cause
- Fix Applied
- Why It Worked
- Prevention Measures
- Lessons Learned

## Next Steps
- Commit fix
- Update tests
- Monitor for recurrence
```

## Use Cases

### Debugging Production Error
```bash
/troubleshoot "500 Internal Server Error in /api/users endpoint"
```

**What happens**:
- Gathers: Server logs, recent deployments, error rate
- Classifies: Runtime error (null reference)
- Hypothesis: User object is null due to missing database migration
- Tests: Check database schema, verify migration status
- Solution: Run missing migration, add null check
- Documents: In TROUBLESHOOT.md for team reference

### Intermittent Test Failure
```bash
/troubleshoot "Test suite passes locally but fails in CI 30% of the time"
```

**What happens**:
- Gathers: CI logs, timing differences, parallel execution setup
- Classifies: Architectural issue (race condition)
- **Asks for help immediately** (complex issue detected)
- Collaborates: Discusses isolation strategy
- Solution: Fix shared state, add test isolation
- Documents: Prevention measures for future tests

### Performance Degradation
```bash
/troubleshoot "API response time increased from 200ms to 2s"
```

**What happens**:
- Gathers: APM data, database query logs, recent changes
- Classifies: Performance issue (database query)
- Hypothesis 1: Missing index on new query
- Tests: Analyze query execution plan
- Solution: Add database index, optimize query
- Documents: Before/after metrics, monitoring alerts

### Configuration Issue
```bash
/troubleshoot "Application can't connect to database after deployment"
```

**What happens**:
- Gathers: Environment variables, connection string, network config
- Classifies: Configuration issue
- Hypothesis: Database URL env var not set in production
- Tests: Check environment variable in production
- Solution: Set DATABASE_URL environment variable
- Quick win: Resolved in < 5 min

## Documentation

Comprehensive documentation following the Diataxis framework:

### 📘 Tutorials (Learning-Oriented)
- [Systematic Troubleshooting Tutorial](docs/tutorials/systematic-troubleshooting.md) - 15 min hands-on walkthrough

### 📗 How-To Guides (Task-Oriented)
- [Debug Common Errors](docs/how-to/debug-common-errors.md) - Patterns for frequent issues

### 📙 Explanation (Understanding-Oriented)
- [Systematic Debugging Philosophy](docs/explanation/systematic-debugging-philosophy.md) - Why ask-for-help prevents spinning wheels

### 📕 Reference
- This README serves as quick reference

## Agents

The Troubleshooting Plugin leverages two specialized agents:

### `@code-archaeologist`
- **Purpose**: Analyzes complex code issues and traces data flows
- **When Used**: During complex debugging (architectural issues, race conditions)
- **Capabilities**: Reverse-engineering, dependency analysis, data flow tracing

### `@qa-engineer`
- **Purpose**: Validates fixes and suggests testing strategies
- **When Used**: After solution found, to ensure comprehensive validation
- **Capabilities**: Test case generation, edge case identification, regression prevention

## Best Practices

### ✅ DO:

1. **Gather Complete Context First**
   - Read full error messages (don't skim)
   - Check recent changes (git diff, git log)
   - Review configuration and environment
   - Check logs for related errors

2. **Form Specific Hypotheses**
   - "I think X is causing Y because Z"
   - Not vague guesses like "maybe it's the database"

3. **Test One Thing at a Time**
   - Make ONE change
   - Test immediately
   - Revert if doesn't work
   - Never stack multiple changes

4. **Ask for Help Early**
   - After 3 failed attempts
   - For complex/architectural issues
   - When unfamiliar with technology
   - For security-critical problems

### ❌ DON'T:

1. **Don't Skip Context Gathering**
   - Rushing to fix wastes more time

2. **Don't Make Multiple Changes at Once**
   - You won't know which change fixed it (or broke it)

3. **Don't Guess Randomly**
   - Form testable hypotheses based on evidence

4. **Don't Spin Wheels Silently**
   - If stuck after 3 attempts, ask for help
   - Don't keep trying random things

5. **Don't Make Aggressive Changes**
   - For architectural issues, ask first
   - Don't refactor during debugging

## Examples

### Example 1: Simple Syntax Error

**Input**:
```bash
/troubleshoot "SyntaxError: Unexpected token ';'"
```

**Process**:
- **Stage 1**: Error in src/utils/parser.js:42
- **Stage 2**: Syntax Error (Simple, < 5 min)
- **Stage 3**: Hypothesis - Extra semicolon or typo
- **Stage 4**: Found `return JSON.parse(data);;` (double semicolon)
- **Stage 5**: Removed extra semicolon, error resolved

**Time**: 2 minutes (no ask-for-help needed)

### Example 2: Complex Race Condition

**Input**:
```bash
/troubleshoot "AssertionError: Expected 1 pending order, got 0 (intermittent in CI)"
```

**Process**:
- **Stage 1**: Intermittent test failure, only in parallel runs
- **Stage 2**: Architectural Issue (race condition, very high complexity)
- **Stage 3**: Hypothesis 1 - Database isolation issue
- **Stage 4**: Attempt 1 - Test isolation level → Still fails
- **Stage 4**: Attempt 2 - Add transaction locks → Still fails
- **Stage 4**: Attempt 3 - Check async/await → All correct
- **⚠️ ASK FOR HELP TRIGGERED** (3 attempts, complex issue)
- Collaboration: User identifies shared test database state
- **Stage 5**: Solution - Separate database per test, fixed

**Time**: 15 minutes (asked for help appropriately)

### Example 3: Performance Issue

**Input**:
```bash
/troubleshoot "Dashboard page loading very slowly (8 seconds)"
```

**Process**:
- **Stage 1**: APM shows database query taking 7.5s, recent feature added user stats
- **Stage 2**: Performance Issue (high complexity)
- **Stage 3**: Hypothesis 1 - N+1 query problem in user stats
- **Stage 4**: Analyze query log - confirmed N+1 (1 query + 500 queries for users)
- **Stage 5**: Add eager loading (.include(:stats)), response time now 200ms

**Time**: 25 minutes, documented metrics for monitoring

## Troubleshooting Patterns

### Pattern 1: "Works on My Machine"
**Cause**: Environment differences
**Check**: Compare env vars, dependencies, OS differences, caches

### Pattern 2: "Intermittent Failures"
**Cause**: Race condition, timing, external service
**Approach**: Run multiple times, check concurrent operations, timing-dependent code

### Pattern 3: "After Update It Broke"
**Cause**: Breaking change in dependency
**Check**: Dependency changelog, git diff, migration guides

### Pattern 4: "Misleading Error Message"
**Examples**:
- "Module not found" → Often wrong path/typo, not missing
- "Permission denied" → Could be file, user, or SELinux

**Approach**: Read full stack trace, check underlying cause 2-3 levels deep

## Quick Win Checks (Before Deep Debugging)

**2-minute checks before spending hours**:

### Basic Checks
- [ ] Server/process running?
- [ ] Right directory/branch?
- [ ] Restarted after config changes?
- [ ] File saved?

### Dependency Checks
- [ ] Run install command (npm install, pip install)
- [ ] Check version mismatches
- [ ] Clear and reinstall if suspicious

### Environment Checks
- [ ] Environment variables set?
- [ ] Using right environment (dev vs prod)?
- [ ] Secrets/API keys valid?

### Cache Checks
- [ ] Clear application cache
- [ ] Delete build artifacts and rebuild
- [ ] Clear browser cache
- [ ] Restart dev server

## Workflow Integration

### Standalone Troubleshooting
```
Error occurs → /troubleshoot → Fix → Test → Done
```

### Integrated with EPCC
```
Error during /epcc-code → /troubleshoot → Fix → /epcc-commit
```

### Team Troubleshooting
```
/troubleshoot → Ask-for-help triggered → Team collaboration → Solution → TROUBLESHOOT.md shared
```

## Version History

- **v1.0.0** (2025-01-21): Initial release
  - `/troubleshoot` command with 5-stage systematic workflow
  - Ask-for-help mechanism (after 3 attempts or complex issues)
  - 8 error category classification
  - TROUBLESHOOT.md documentation output

## Contributing

See [CONTRIBUTING.md](../../CONTRIBUTING.md) for guidelines.

## License

MIT-0 - See [LICENSE](../../LICENSE) for details.

## Support

- **Issues**: [GitHub Issues](https://github.com/aws-samples/guidance-for-claude-code-with-amazon-bedrock/issues)
- **Discussions**: [GitHub Discussions](https://github.com/aws-samples/guidance-for-claude-code-with-amazon-bedrock/discussions)

## Related Plugins

- **requirements**: Product and technical requirements gathering before implementation
- **epcc-workflow**: Explore → Plan → Code → Commit systematic development workflow
- **documentation**: Generate documentation after implementation
