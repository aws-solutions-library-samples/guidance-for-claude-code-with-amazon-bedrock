---
name: trd
description: Technical Requirements Document generation through interactive interview
version: 3.1.0
argument-hint: "[initial-technical-context-or-project-name]"
---

# Technical Requirements Document (TRD) Generator

Generate comprehensive **TECH_REQ.md** through collaborative technical discovery. This command transforms architectural ambiguity into clear technical decisions that feed directly into the EPCC plan phase.

**Opening Principle**: High-quality TRDs transform architectural ambiguity into clear technical decisions through collaborative discovery, enabling confident implementation with the right technology choices.

@../docs/EPCC_BEST_PRACTICES.md - Comprehensive guide covering sub-agent delegation, clarification strategies, error handling patterns, and technical requirements workflow optimization

## What This Command Does

**Purpose**: Create Technical Requirements Document (TECH_REQ.md) that defines:
- Architecture patterns and component structure
- Technology stack with justified choices
- Data models and storage strategies
- Integration points and API design
- Security and compliance approach
- Performance and scalability plan

**Output**: `TECH_REQ.md` file

**Position in workflow**:
- **Optional input**: PRD.md (product requirements, if available)
- **This command**: Generate TECH_REQ.md through technical interview
- **Feeds into**: `/epcc-plan` (strategic implementation planning)

## TRD Discovery Philosophy

**Opening Principle**: Discover technical requirements through **structured questions and collaborative dialogue**, not assumptions.

### Core Approach

**✅ Do (Default Behavior)**:
- **Use AskUserQuestion proactively** for all technical decisions with 2-4 clear options
- Read PRD.md if available to understand product context
- Ask about architecture, stack, infrastructure aligned with product needs
- Present technology options with tradeoffs (not recommendations as facts)
- Match technical depth to project complexity
- Document rationale for every technical decision

**❌ Don't**:
- Assume tech stack without asking ("I'll use React and PostgreSQL" → Ask first!)
- Make technology recommendations without presenting alternatives and tradeoffs
- Skip reading PRD.md if it exists (product context informs technical decisions)
- Ask about implementation details (belongs in CODE phase)
- Force comprehensive TRD for simple projects (CRUD app ≠ distributed systems design)

**Remember**: You're discovering technical requirements, not implementing. Focus on WHAT technologies and WHY, defer HOW to CODE phase.

## Discovery Objectives

**What we're discovering**:

1. **Architecture** (Patterns, service boundaries, component structure)
   - Monolith? Microservices? Serverless? JAMstack? Hybrid?
   - Design patterns to follow
   - How components fit together

2. **Technology Stack** (Languages, frameworks, tools, libraries)
   - Backend: Language + framework
   - Frontend: Framework/library or vanilla
   - Infrastructure: Hosting, deployment, orchestration
   - Tooling: Build tools, testing frameworks, CI/CD

3. **Data Models** (Storage, schemas, relationships)
   - Database choice with rationale
   - Schema design approach
   - Data relationships and migrations
   - Caching strategy

4. **Integrations** (APIs, third-party services, authentication)
   - API design (REST? GraphQL? gRPC? tRPC?)
   - Authentication method (JWT? OAuth2? Session? Auth0?)
   - Third-party services (payment, email, analytics, etc.)
   - Webhooks and event handling

5. **Security** (Auth, compliance, data protection)
   - Authentication & authorization approach
   - Data protection and encryption
   - OWASP considerations
   - Compliance requirements (GDPR, HIPAA, SOC2, etc.)

6. **Performance** (Scalability, caching, optimization)
   - Expected load and scaling strategy
   - Caching layers (CDN, application, database)
   - Performance budgets and monitoring
   - Optimization priorities

**Depth adaptation**:
- **Simple project** → Focus on stack + data + basic security
- **Medium project** → Add integrations + performance + detailed security
- **Complex project** → Comprehensive architecture + compliance + high-scale design

## Clarification Strategy

### When to Use AskUserQuestion (PRIMARY METHOD)

**✅ Use AskUserQuestion for** (default for all technical decisions):
- **Architecture decisions**: "Monolith vs Microservices vs Serverless?"
- **Technology choices**: "Database: PostgreSQL vs MongoDB vs MySQL?"
- **Infrastructure decisions**: "Hosting: AWS vs GCP vs Azure vs Vercel?"
- **Authentication methods**: "Auth: JWT vs OAuth2 vs Session vs Auth0?"
- **API design**: "API style: REST vs GraphQL vs gRPC?"
- **Any decision with 2-4 clear options**

**Pattern**:
```typescript
AskUserQuestion({
  questions: [{
    question: "What database technology fits your needs?",
    header: "Database",
    multiSelect: false,
    options: [
      {
        label: "PostgreSQL",
        description: "Relational, ACID compliant, complex queries, JSON support, mature ecosystem"
      },
      {
        label: "MongoDB",
        description: "Document store, flexible schema, good for JSON-heavy data, horizontal scaling"
      },
      {
        label: "MySQL",
        description: "Relational, widely supported, proven at scale, simpler than PostgreSQL"
      },
      {
        label: "DynamoDB",
        description: "AWS managed NoSQL, serverless, auto-scaling, simple key-value or documents"
      }
    ]
  }]
})
```

### When to Converse Naturally (FALLBACK)

**✅ Use conversation for**:
- Open-ended exploration ("Tell me about your data model")
- Clarifying context ("What scale are we targeting?")
- Following up on answers ("You mentioned real-time features - how critical is sub-second latency?")
- Discussing custom/hybrid approaches not fitting 2-4 options

**❌ Don't use conversation for**:
- Standard technology choices (database, hosting, auth → use AskUserQuestion)
- Decisions already answered in PRD.md (read it first)
- Implementation details (defer to CODE phase)

### Check PRD.md First

**Before asking questions**:
```bash
if [ -f "PRD.md" ]; then
    # Read PRD.md to understand:
    # - Features (what needs technical support?)
    # - Users (scale, geography, access patterns)
    # - Constraints (timeline, budget, compliance)
    # - Success criteria (performance targets, uptime, etc.)

    # Then ask technical questions informed by product context
fi
```

**Reference PRD dynamically**:
- "Based on the real-time collaboration feature in PRD.md, we need to consider WebSocket vs polling..."
- "Given the 100K user target in PRD.md, let's discuss caching strategy..."
- "The GDPR compliance mentioned in PRD.md means we need..."

**If PRD.md missing**: Ask about product context first (users, features, scale) to inform technical decisions.

**Research & Exploration**:
- **WebSearch/WebFetch**: Use for technology comparisons, best practices, domain standards, official docs when unfamiliar
- **/epcc-explore**: Use for brownfield projects to discover existing architecture, tech stack, patterns
- **Skip**: When user has complete technical vision or simple feature

**Decision heuristic**: Research when comparing options or learning domain; explore brownfield for existing patterns; skip if user provided sufficient context.

## Interview Mode Selection

Present mode choice to user with clear time/depth tradeoffs:

### Quick TRD (20-30 minutes)

**When to use**:
- Simple architecture (monolith or simple SPA)
- Well-known tech stack (standard CRUD with common tools)
- Minimal integrations (0-2 third-party services)
- Clear technical path (no major unknowns)

**Coverage**:
- Core stack decisions (language, framework, database, hosting)
- Basic security (auth method)
- Simple data model
- Essential integrations only

**Question count**: ~8-12 structured questions focused on essentials

### Comprehensive TRD (60-90 minutes)

**When to use**:
- Complex architecture (microservices, event-driven, distributed)
- Multiple technology decisions (polyglot, multiple services)
- Many integrations (payment, email, analytics, webhooks, etc.)
- Compliance requirements (GDPR, HIPAA, SOC2)
- High scale or performance critical (millions of users, sub-second latency)

**Coverage**:
- Deep architecture exploration across all 6 discovery phases
- Detailed technology evaluation with tradeoffs
- Comprehensive security and compliance planning
- Performance and scalability design
- Migration and deployment strategy

**Question count**: ~25-35 structured questions + conversational deep-dives

### Mode Selection Pattern

```
I can help create your Technical Requirements Document.

Based on [initial context], this appears to be a [simple/medium/complex] technical scope.

I can create either:
1. **Quick TRD** (20-30 min) - Core stack and architecture for straightforward projects
2. **Comprehensive TRD** (60-90 min) - Deep technical exploration for complex systems

Which approach works better for your project?
```

**Adapt mode during interview**: If complexity emerges (user mentions compliance, high scale, many integrations), suggest switching to comprehensive.

## Discovery Phases

### Phase 1: Architecture & Patterns

**Goal**: Define high-level structure and component organization.

**Context**: Research with WebSearch/WebFetch("[architecture] patterns 2025"), explore with /epcc-explore (brownfield).

**Use AskUserQuestion for**:
```typescript
// Architecture Pattern
{
  question: "What architectural pattern fits your project?",
  header: "Architecture",
  options: [
    {
      label: "Monolith",
      description: "Single codebase, simpler deployment, good for small teams, faster initial development"
    },
    {
      label: "Microservices",
      description: "Independent services, complex deployment, team autonomy, scales components independently"
    },
    {
      label: "Serverless",
      description: "Function-based, auto-scaling, pay-per-use, less infrastructure management"
    },
    {
      label: "JAMstack",
      description: "Static generation + APIs, excellent performance, simple hosting, limited dynamic features"
    }
  ]
}

// Design Patterns (if complex project)
{
  question: "What design patterns are important for your system?",
  header: "Patterns",
  multiSelect: true,
  options: [
    {label: "Event-driven", description: "Async communication, decoupled components, eventual consistency"},
    {label: "CQRS", description: "Separate read/write models, optimized queries, complex to implement"},
    {label: "Repository", description: "Data access abstraction, testable, clean architecture"},
    {label: "Factory", description: "Object creation patterns, dependency injection, flexible instantiation"}
  ]
}
```

**Converse about**:
- Component structure ("What are the main components/services?")
- Service boundaries (if microservices)
- Data flow between components

**From PRD.md (if available)**: Features → Architectural needs (real-time? background jobs? file processing?)

### Phase 2: Technology Stack & Infrastructure

**Goal**: Select languages, frameworks, hosting, and deployment approach.

**Context**: Research with WebSearch/WebFetch("[tech-stack] best practices 2025"), explore with /epcc-explore (brownfield).

**Use AskUserQuestion for**:
```typescript
// Backend Language
{
  question: "What backend language/runtime fits your needs?",
  header: "Backend",
  options: [
    {label: "Node.js", description: "JavaScript/TypeScript, async I/O, npm ecosystem, good for APIs"},
    {label: "Python", description: "Django/Flask/FastAPI, AI/ML libraries, readable, slower than compiled"},
    {label: "Go", description: "Compiled, fast, simple concurrency, strong typing, smaller ecosystem"},
    {label: "Java/Kotlin", description: "Enterprise-grade, JVM, Spring ecosystem, verbose, battle-tested"}
  ]
}

// Frontend Framework
{
  question: "What frontend approach do you want?",
  header: "Frontend",
  options: [
    {label: "React", description: "Popular, large ecosystem, component-based, JSX syntax, flexible"},
    {label: "Vue", description: "Simpler than React, good docs, template syntax, smaller ecosystem"},
    {label: "Svelte", description: "Compile-time framework, fast, less boilerplate, newer ecosystem"},
    {label: "Vanilla JS", description: "No framework, full control, smaller bundle, more manual work"}
  ]
}

// Hosting Infrastructure
{
  question: "Where will you host this application?",
  header: "Hosting",
  options: [
    {label: "AWS", description: "Full service suite, complex, powerful, enterprise-ready, higher cost"},
    {label: "Google Cloud", description: "Good for AI/ML, Kubernetes native, competitive pricing"},
    {label: "Azure", description: "Enterprise integration, Microsoft stack, hybrid cloud"},
    {label: "Vercel/Netlify", description: "Simple deployment, great DX, limited backend, good for JAMstack"}
  ]
}
```

**Converse about**:
- Framework choices within language (Express vs Fastify? Django vs FastAPI?)
- Build tools and CI/CD pipeline
- Deployment strategy (containers? serverless? VMs?)

**From PRD.md (if available)**: Budget → Hosting costs, Timeline → Deployment complexity

### Phase 3: Data Models & Storage

**Goal**: Define data storage strategy, schemas, and caching.

**Context**: Research with WebSearch/WebFetch("[database] best practices 2025"), explore with /epcc-explore (brownfield).

**Use AskUserQuestion for**:
```typescript
// Database Selection
{
  question: "What database technology fits your data model?",
  header: "Database",
  options: [
    {label: "PostgreSQL", description: "Relational, ACID, complex queries, JSON support, mature"},
    {label: "MongoDB", description: "Document store, flexible schema, good for JSON, horizontal scaling"},
    {label: "MySQL", description: "Relational, widely supported, proven at scale, simpler than Postgres"},
    {label: "DynamoDB", description: "AWS NoSQL, serverless, auto-scaling, key-value or documents"}
  ]
}

// Caching Strategy (if medium/complex)
{
  question: "What caching approach do you need?",
  header: "Caching",
  multiSelect: true,
  options: [
    {label: "Redis", description: "In-memory, fast, pub/sub, session storage, requires management"},
    {label: "CDN", description: "Edge caching, static assets, global distribution, reduces origin load"},
    {label: "Application cache", description: "In-process, simple, no network, lost on restart"},
    {label: "Database query cache", description: "Built-in, automatic, limited control"}
  ]
}
```

**Converse about**:
- Data model structure (entities, relationships)
- Schema design approach (migrations? versioning?)
- Data access patterns (read-heavy? write-heavy? analytics?)

**From PRD.md (if available)**: Features → Data entities, Users → Access patterns

### Phase 4: Integrations & APIs

**Goal**: Define API design, authentication, and third-party integrations.

**Context**: Research with WebSearch/WebFetch("[API/auth] best practices 2025"), explore with /epcc-explore (brownfield).

**Use AskUserQuestion for**:
```typescript
// API Style
{
  question: "What API style fits your needs?",
  header: "API",
  options: [
    {label: "REST", description: "Standard HTTP, widely understood, simple, over-fetching/under-fetching"},
    {label: "GraphQL", description: "Flexible queries, precise data fetching, complex setup, learning curve"},
    {label: "gRPC", description: "High performance, typed, binary protocol, requires code generation"},
    {label: "tRPC", description: "Type-safe, TypeScript end-to-end, simple, ecosystem smaller"}
  ]
}

// Authentication Method
{
  question: "How will users authenticate?",
  header: "Auth",
  options: [
    {label: "JWT", description: "Stateless, scalable, client stores token, can't revoke easily"},
    {label: "Session", description: "Server-side state, easy to revoke, requires session store"},
    {label: "OAuth2", description: "Third-party login (Google, GitHub), complex setup, better UX"},
    {label: "Auth0/Clerk", description: "Managed service, fast setup, monthly cost, less control"}
  ]
}

// Third-Party Services (multiSelect)
{
  question: "What third-party services do you need?",
  header: "Services",
  multiSelect: true,
  options: [
    {label: "Payment", description: "Stripe, PayPal, Square - transaction processing"},
    {label: "Email", description: "SendGrid, Mailgun, AWS SES - transactional emails"},
    {label: "Storage", description: "S3, Cloudinary, Uploadcare - file uploads and CDN"},
    {label: "Analytics", description: "Mixpanel, Amplitude, PostHog - user behavior tracking"}
  ]
}
```

**Converse about**:
- API versioning strategy
- Webhook handling (if needed)
- Rate limiting and API security

**From PRD.md (if available)**: Features → Required integrations (payments, notifications, etc.)

### Phase 5: Security & Compliance

**Goal**: Define authentication, authorization, data protection, and compliance.

**Context**: Research with WebSearch/WebFetch("[security/compliance] requirements 2025"), explore with /epcc-explore (brownfield).

**Use AskUserQuestion for**:
```typescript
// Authorization Model
{
  question: "What authorization model do you need?",
  header: "Authz",
  options: [
    {label: "RBAC", description: "Role-based, simple, roles assigned to users, good for most apps"},
    {label: "ABAC", description: "Attribute-based, flexible, complex policies, enterprise use cases"},
    {label: "Simple ownership", description: "Users own resources, basic access control, simplest"},
    {label: "Multi-tenancy", description: "Isolated data per tenant, complex, SaaS products"}
  ]
}

// Compliance Requirements (multiSelect, if applicable)
{
  question: "What compliance standards apply?",
  header: "Compliance",
  multiSelect: true,
  options: [
    {label: "GDPR", description: "EU data privacy, right to deletion, consent management"},
    {label: "HIPAA", description: "Healthcare data, strict security, audit logs, encryption"},
    {label: "SOC2", description: "Security controls, audit reports, enterprise customers"},
    {label: "PCI DSS", description: "Payment card data, strict requirements, third-party audits"}
  ]
}
```

**Converse about**:
- Data encryption (at rest? in transit?)
- OWASP Top 10 considerations
- Security testing approach

**From PRD.md (if available)**: Constraints → Compliance requirements, Data sensitivity

### Phase 6: Performance & Scalability

**Goal**: Define performance targets, scaling strategy, and optimization priorities.

**Context**: Research with WebSearch/WebFetch("[performance/scaling] patterns 2025"), explore with /epcc-explore (brownfield).

**Use AskUserQuestion for**:
```typescript
// Expected Scale
{
  question: "What scale are you targeting?",
  header: "Scale",
  options: [
    {label: "Small (<1K users)", description: "Single server, minimal caching, simple deployment"},
    {label: "Medium (1K-100K users)", description: "Load balancer, caching layer, horizontal scaling"},
    {label: "Large (100K-1M users)", description: "Multi-region, CDN, advanced caching, auto-scaling"},
    {label: "Massive (>1M users)", description: "Global infrastructure, edge computing, complex architecture"}
  ]
}

// Performance Priorities (multiSelect)
{
  question: "What performance aspects are most critical?",
  header: "Performance",
  multiSelect: true,
  options: [
    {label: "Page load speed", description: "Initial render, time to interactive, Core Web Vitals"},
    {label: "API latency", description: "Response times, database query optimization"},
    {label: "Real-time updates", description: "WebSocket, SSE, sub-second data freshness"},
    {label: "Background jobs", description: "Async processing, job queues, worker scaling"}
  ]
}
```

**Converse about**:
- Performance budgets (page load <2s? API <100ms?)
- Monitoring and observability strategy
- Optimization approach (optimize now vs later?)

**From PRD.md (if available)**: Success criteria → Performance targets, Users → Scale expectations

## Adaptive Interview Heuristics

**Match question depth to project complexity** (discovered dynamically):

### Simple Project Indicators
- Single service/application
- <10K users
- Standard CRUD operations
- 0-2 integrations
- No compliance requirements

**Adapt**: Focus on Stack + Data + Basic Security (~10-12 questions)

### Medium Project Indicators
- 2-3 services
- 10K-100K users
- Some real-time features
- 3-5 integrations
- Basic security needs

**Adapt**: All 6 phases with moderate depth (~20-25 questions)

### Complex Project Indicators
- Microservices/distributed
- >100K users
- Compliance requirements
- >5 integrations
- High performance/availability needs

**Adapt**: Comprehensive exploration of all 6 phases (~30-40 questions)

**Dynamic adjustment**: If user mentions compliance/high-scale/many integrations during simple TRD → offer to switch to comprehensive mode.

## TECH_REQ.md Output Structure

**Forbidden patterns**:
- ❌ Comprehensive TRD for simple CRUD app (violates complexity matching)
- ❌ Technology choices without rationale ("Use PostgreSQL" → WHY PostgreSQL vs alternatives?)
- ❌ Implementation details (exact API endpoints, function signatures → belongs in CODE phase)
- ❌ Assuming tech stack without asking (you discover, not prescribe)
- ❌ Rigid template sections for minimal projects (simple project = simple TRD)

**TRD structure - 6 core dimensions**:

### Simple TRD (~400-600 tokens)
**When**: Single service, standard stack, minimal integrations, <10K users

```markdown
# Technical Requirements: [Project Name]

**Created**: [Date] | **Complexity**: Simple | **From PRD**: [Yes/No]

## Architecture
**Pattern**: [Monolith/SPA/JAMstack]
**Rationale**: [Why this pattern fits the project]

## Technology Stack
**Backend**: [Language + Framework] - [Rationale]
**Frontend**: [Framework/Vanilla] - [Rationale]
**Database**: [Database] - [Rationale]
**Hosting**: [Platform] - [Rationale]

## Data Model
**Core Entities**: [List 3-5 main entities]
**Relationships**: [Key relationships]
**Migrations**: [Strategy: tool/approach]

## Security
**Authentication**: [Method] - [Rationale]
**Authorization**: [Approach] - [Rationale]
**Data Protection**: [Encryption strategy]

## Integrations
[List essential integrations with rationale, or "None" if standalone]

## Performance
**Expected Scale**: [<1K users, load expectations]
**Caching**: [Strategy if needed, or "Not required initially"]

## PRD Alignment
[If PRD.md exists, reference how technical choices support product requirements]

## Next Steps
Technical requirements defined. Ready for:
- Brownfield: `/epcc-explore` then `/epcc-plan`
- Greenfield: `/epcc-plan` (skip explore)
```

### Medium TRD (~800-1,200 tokens)
**When**: Multiple services, moderate complexity, several integrations, 10K-100K users

Add to simple structure:
- **Architecture Diagram**: Component relationships, data flow
- **Detailed Stack Justification**: Compare alternatives with tradeoffs
- **API Design**: REST/GraphQL, versioning strategy, rate limiting
- **Caching Strategy**: Layers (CDN, application, database), invalidation
- **Monitoring**: Observability approach, key metrics
- **Deployment**: CI/CD pipeline, environment strategy

### Complex TRD (~1,500-2,500 tokens)
**When**: Distributed system, compliance requirements, high scale, many integrations

Add to medium structure:
- **Detailed Architecture**: Service boundaries, event flows, async patterns
- **Technology Evaluation**: Deep comparison of alternatives with scoring
- **Data Architecture**: Schema design, partitioning, replication, migrations
- **Security & Compliance**: OWASP checklist, compliance requirements (GDPR/HIPAA/SOC2), audit logging
- **Performance & Scale**: Load testing strategy, auto-scaling, multi-region, CDN strategy
- **Disaster Recovery**: Backup strategy, failover, RTO/RPO targets
- **Migration Plan**: If replacing existing system

**Depth heuristic**: TRD complexity should match technical complexity. Don't write distributed systems TRD for simple CRUD app.

### Full TRD Template (Adapt to Complexity)

```markdown
# Technical Requirements Document: [Project Name]

**Created**: [Date]
**Version**: 1.0
**Complexity**: [Simple/Medium/Complex]
**PRD Reference**: [PRD.md if available, or "Standalone"]

---

## Executive Summary
[2-3 sentence technical overview]

## Research & Exploration

**Key Insights** (from WebSearch/WebFetch/exploration):
- **[Technology choice]**: [Research finding, benchmark, or rationale]
- **[Pattern/approach]**: [Best practice discovered or code pattern leveraged]
- **[Existing component]**: [Reusable code discovered from exploration]

**Documentation Identified**:
- **[Doc type]**: Priority [H/M/L] - [Why needed for this project]

## Architecture

### Pattern
[Monolith/Microservices/Serverless/JAMstack/Hybrid]

**Rationale**: [Why this pattern? Considered alternatives?]

### Component Structure
[List main components/services and their responsibilities]

### Data Flow
[How data moves through the system - simple description or diagram]

### Design Patterns
[Key patterns: Event-driven, CQRS, Repository, etc.]

## Technology Stack

### Backend
**Language/Runtime**: [Choice] - [Rationale vs alternatives]
**Framework**: [Choice] - [Rationale vs alternatives]

### Frontend
**Framework**: [React/Vue/Svelte/Vanilla] - [Rationale vs alternatives]
**Build Tools**: [Vite/Webpack/etc.] - [Rationale]

### Database
**Primary Database**: [PostgreSQL/MongoDB/MySQL/etc.] - [Rationale vs alternatives]
**Caching**: [Redis/CDN/Application cache] - [Strategy]

### Infrastructure
**Hosting**: [AWS/GCP/Azure/Vercel/etc.] - [Rationale vs alternatives]
**Deployment**: [Containers/Serverless/VMs] - [Rationale]
**CI/CD**: [GitHub Actions/GitLab CI/CircleCI/etc.] - [Strategy]

## Data Architecture

### Core Entities
1. **[Entity Name]**
   - Purpose: [What it represents]
   - Key attributes: [Essential fields]
   - Relationships: [Connections to other entities]

2. **[Entity Name]**
   - [Same structure]

### Schema Design
**Approach**: [Normalized/Denormalized/Hybrid] - [Rationale]
**Migrations**: [Tool: Prisma/TypeORM/Alembic/etc.] - [Strategy]

### Data Access Patterns
- [Read-heavy? Write-heavy? Analytics?]
- [Query optimization strategy]

## API Design

### API Style
**Choice**: [REST/GraphQL/gRPC/tRPC] - [Rationale vs alternatives]

### Endpoints (if REST)
[High-level endpoint groups, not exhaustive list]

### Authentication
**Method**: [JWT/Session/OAuth2/Auth0] - [Rationale vs alternatives]
**Token Storage**: [Where tokens stored, expiry strategy]

### Authorization
**Model**: [RBAC/ABAC/Ownership/Multi-tenancy] - [Rationale]

### Rate Limiting
[Strategy if needed]

## Integrations

### Third-Party Services
1. **[Service Name]** (e.g., Stripe for payments)
   - Purpose: [What it does]
   - Rationale: [Why this vs alternatives]
   - Integration approach: [API/SDK/Webhook]

2. **[Service Name]**
   - [Same structure]

### External APIs
[Any external APIs to consume]

### Webhooks
[If handling incoming webhooks]

## Security

### Authentication & Authorization
**Authentication**: [Detailed approach from API Design]
**Authorization**: [Detailed model from API Design]

### Data Protection
**Encryption at Rest**: [Yes/No - approach if yes]
**Encryption in Transit**: [TLS configuration]
**Sensitive Data**: [PII handling, secrets management]

### OWASP Considerations
[Key OWASP Top 10 items relevant to this project]

### Compliance (if applicable)
**Requirements**: [GDPR/HIPAA/SOC2/PCI DSS/etc.]
**Implementation**: [How compliance requirements are met]
**Audit Logging**: [What's logged, retention period]

## Performance & Scalability

### Scale Targets
**Users**: [Expected user count]
**Requests**: [Expected req/sec or req/day]
**Data Volume**: [Expected data growth]

### Performance Budgets
- **Page Load**: [Target: <2s]
- **API Latency**: [Target: <100ms p95]
- **Database Queries**: [Target: <50ms p95]

### Caching Strategy
**Layers**:
1. **CDN**: [Static assets, edge caching]
2. **Application Cache**: [Redis/in-memory, what's cached]
3. **Database Query Cache**: [If applicable]

**Invalidation**: [Strategy for cache freshness]

### Scaling Approach
**Horizontal vs Vertical**: [Choice and rationale]
**Auto-scaling**: [Triggers, min/max instances]
**Load Balancing**: [Strategy]

### Monitoring & Observability
**Metrics**: [What to track: latency, errors, throughput]
**Logging**: [Structured logging approach]
**Tracing**: [Distributed tracing if microservices]
**Tools**: [DataDog/New Relic/Prometheus/etc.]

## Deployment Strategy

### Environments
- **Development**: [Local/shared dev environment]
- **Staging**: [Pre-production testing]
- **Production**: [Live environment]

### CI/CD Pipeline
1. [Build step]
2. [Test step]
3. [Deploy step]

### Rollback Strategy
[How to revert if deployment fails]

### Zero-Downtime Deployment
[Blue-green? Rolling? Canary?]

## Disaster Recovery (Complex projects)

### Backup Strategy
**Frequency**: [Hourly/Daily/etc.]
**Retention**: [How long backups kept]
**Testing**: [Backup restore testing frequency]

### Failover
**RTO** (Recovery Time Objective): [Target downtime]
**RPO** (Recovery Point Objective): [Acceptable data loss]

## Migration Plan (If applicable)

[If replacing existing system or migrating data]

### Migration Strategy
- [Approach: Big bang? Phased? Strangler pattern?]

### Data Migration
- [Source → Target mapping]
- [Validation strategy]

### Rollback Plan
- [How to revert if migration fails]

## Risks & Mitigation

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| [Technical risk] | H/M/L | H/M/L | [How to address] |

## Assumptions

[Critical technical assumptions that could change the plan]

## Out of Scope

[Technical decisions deferred or explicitly excluded]

## PRD Alignment

[If PRD.md exists]

**Product Requirements Supported**:
- [Feature from PRD] → [Technical approach]
- [Constraint from PRD] → [How technical design respects it]
- [Success criteria from PRD] → [How architecture enables measurement]

**Technical Decisions Informing Product**:
- [Technology limitation] → [Product implication]
- [Performance characteristic] → [User experience impact]

## Next Steps

This TRD feeds into the EPCC workflow. Choose your entry point:

**For Greenfield Projects** (new codebase):
1. Review & approve this TRD
2. Run `/epcc-plan` to create implementation plan (can skip Explore)
3. Begin development with `/epcc-code`
4. Finalize with `/epcc-commit`

**For Brownfield Projects** (existing codebase):
1. Review & approve this TRD
2. Run `/epcc-explore` to understand existing codebase and patterns
3. Run `/epcc-plan` to create implementation plan based on exploration + this TRD
4. Begin development with `/epcc-code`
5. Finalize with `/epcc-commit`

**Note**: The core EPCC workflow is: **Explore → Plan → Code → Commit**. This TRD is the optional technical preparation step before that cycle begins.

---

**End of TRD**
```

**Completeness heuristic**: TRD is ready when you can answer:
- ✅ What's the architecture pattern and why?
- ✅ What's the technology stack with rationale for each choice?
- ✅ What's the data model and storage strategy?
- ✅ How are integrations and APIs designed?
- ✅ How is security and compliance handled?
- ✅ How does the system scale and perform?
- ✅ If PRD exists, how do technical choices support product requirements?

**Anti-patterns**:
- ❌ **Simple CRUD with 2,000-token distributed systems TRD** → Violates complexity matching
- ❌ **Complex platform with 500-token TRD** → Insufficient technical detail
- ❌ **"Use PostgreSQL" without explaining why vs MongoDB/MySQL** → No rationale
- ❌ **Implementation details** → "Create UserService class with getUserById method" belongs in CODE phase
- ❌ **Every section filled with "TBD"** → If unknown, document as assumption or open question
- ❌ **No security consideration** → All projects need auth/data protection discussion

---

**Remember**: Match TRD depth to technical complexity. Simple project = simple TRD. Focus on WHAT and WHY, defer HOW to CODE phase.

## After Generating TECH_REQ.md

**Confirm completeness:**
```
✅ TECH_REQ.md generated and saved

This document captures:
- Architecture: [Pattern chosen]
- Tech Stack: [Key technologies with rationale]
- Data Model: [Storage approach]
- Security: [Auth/compliance approach]
- Scalability: [Scale strategy]
[+ PRD Alignment if PRD.md existed]

Next steps - Enter the EPCC workflow:
- Review the TRD and let me know if anything needs adjustment
- When ready, begin EPCC cycle with `/epcc-explore` (brownfield) or `/epcc-plan` (greenfield)

Questions or changes to the TRD?
```

## Conversation Principles

### Be Technical, But Accessible

❌ **Don't dictate**: "You should use microservices for this"
✅ **Do guide**: "For your scale, we could use a monolith (simpler, faster to ship) or microservices (independent scaling, team autonomy). Given your timeline and team size, which sounds better?"

### Present Technology Tradeoffs

❌ **Don't guarantee**: "PostgreSQL will handle your scale perfectly"
✅ **Do qualify**: "PostgreSQL would handle your expected 10K users well, though we'd want monitoring to validate query performance as you grow"

### Use AskUserQuestion Proactively

**Pattern**:
```typescript
// Don't wait for user to ask "help me decide"
// Present structured questions for ALL technical decisions

AskUserQuestion({
  questions: [{
    question: "What hosting platform fits your needs?",
    header: "Hosting",
    options: [
      {label: "AWS", description: "Full suite, complex, powerful, higher cost"},
      {label: "Vercel", description: "Simple, great DX, limited backend, good for Next.js"},
      {label: "Railway", description: "Simple, good for full-stack, auto-deploy, newer platform"},
      {label: "Self-hosted", description: "Full control, more setup, lower ongoing cost"}
    ]
  }]
})
```

### Reference PRD Context When Available

If PRD.md exists:
- "Based on the real-time chat feature in PRD.md, we should consider WebSocket support..."
- "Given the 100K user target in PRD.md, let's discuss caching strategy..."
- "The GDPR requirement mentioned in PRD.md means we need audit logging for data access..."

### Ask Follow-ups When Vague

- "You mentioned high scale - can you quantify that? 10K users? 1M users?"
- "For the API, would your mobile app be the only consumer, or will third parties integrate?"
- "When you say 'real-time,' do you mean sub-second updates, or is 5-second polling acceptable?"

### Reflect Back Periodically

"So if I understand correctly, we're building a [architecture] with [stack] that [key technical capability]. The main technical challenges are [X] and [Y]. Does that sound right?"

## Usage Examples

### Basic Invocation

```bash
# With project context
/trd "Real-time collaboration platform"

# After creating PRD
/trd  # Will find and read PRD.md automatically

# Without context
/trd
# Will ask: "What technical project would you like to define requirements for?"
```

### Example Flow: Quick TRD (Greenfield)

**User**: `/trd "Simple blog platform"`

**Claude**: *Checks for PRD.md (not found)*
```
I can help create your Technical Requirements Document for the blog platform.

This appears to be a straightforward project. I can create:
1. **Quick TRD** (20-30 min) - Core stack and architecture
2. **Comprehensive TRD** (60-90 min) - Deep technical exploration

Which approach works better?
```

**User**: "Quick TRD"

**Claude**: *Uses AskUserQuestion for all key decisions*
- Architecture pattern (monolith selected)
- Backend stack (Node.js + Express selected)
- Frontend (React selected)
- Database (PostgreSQL selected)
- Hosting (Vercel selected)
- Auth (JWT selected)
- Conversational follow-ups about data model

**Claude**: *Generates Simple TRD (~500 tokens) matching complexity*

**Total time**: ~20 minutes

### Example Flow: Comprehensive TRD (With PRD)

**User**: `/trd` *[PRD.md exists in directory]*

**Claude**: *Reads PRD.md first*
```
✅ Found PRD.md - I'll use the product requirements to inform technical decisions.

From PRD.md I can see:
- Real-time collaboration features (needs WebSocket support)
- 100K user target (needs caching and scaling strategy)
- GDPR compliance (needs audit logging and data protection)

This appears to be a complex technical scope. I recommend:
**Comprehensive TRD** (60-90 min) - Deep technical exploration

Shall we proceed with comprehensive mode?
```

**User**: "Yes"

**Claude**: *Comprehensive exploration across all 6 phases*
- Architecture (microservices chosen for independent scaling)
- Tech stack (Node.js backend, React frontend, PostgreSQL + Redis)
- Data models (detailed entity design)
- Integrations (WebSocket, email, analytics)
- Security (OAuth2, RBAC, GDPR compliance)
- Performance (CDN, multi-layer caching, auto-scaling)

**Claude**: *Generates Complex TRD (~2,000 tokens) with PRD alignment section*

**Total time**: ~75 minutes

### Example Flow: Brownfield (Existing Codebase)

**User**: `/trd "Add payment processing to existing e-commerce platform"`

**Claude**: *Checks for PRD.md (found)*
```
✅ Found PRD.md - using product context for payment requirements.

Since you're adding to an existing codebase, I'll focus technical requirements on:
- Payment integration architecture
- Technology choices (payment processor, security)
- Data model changes
- Integration with existing stack

I recommend **Medium TRD** (30-45 min) for this integration scope.

Shall we proceed?
```

**User**: "Yes"

**Claude**: *Focused technical interview*
- Payment processor choice (Stripe selected)
- Integration architecture (webhook handling, idempotency)
- Data model (payment records, audit trail)
- Security (PCI DSS considerations, secrets management)
- Testing strategy (mock payments, sandbox)

**Claude**: *Generates Medium TRD (~900 tokens) focused on integration*

```
✅ TECH_REQ.md generated

Next steps:
1. Review this TRD
2. Run `/epcc-explore` to understand existing codebase patterns
3. Run `/epcc-plan` to create implementation plan that integrates with existing code

Ready to explore the existing codebase?
```

## Common Pitfalls (Anti-Patterns)

### ❌ Assuming Tech Stack Without Asking
**Don't**: "I'll use React and PostgreSQL for this" → **Do**: Ask using AskUserQuestion for all stack choices

### ❌ Making Technology Recommendations as Facts
**Don't**: "PostgreSQL is the best choice" → **Do**: Present options with tradeoffs, let user decide

### ❌ Following Template Rigidly
**Don't**: Generate comprehensive TRD for "add button" task → **Do**: Match depth to technical complexity

### ❌ Including Implementation Details
**Don't**: "Create UserService class with methods..." → **Do**: Focus on technology choices and architecture patterns

### ❌ Ignoring PRD.md When Present
**Don't**: Ask about scale/features already in PRD.md → **Do**: Read PRD.md first, reference context

### ❌ Using Conversation When AskUserQuestion Fits
**Don't**: "What database do you want?" (open-ended) → **Do**: AskUserQuestion with 4 database options + tradeoffs

## Second-Order Convergence Warnings

Even with this guidance, you may default to:

- ❌ **Assuming standard tech stack** (ask about stack choices, don't assume MERN/MEAN/etc.)
- ❌ **Following template rigidly** (simple project ≠ comprehensive TRD with all sections)
- ❌ **Making technology recommendations** (present options with tradeoffs, don't prescribe)
- ❌ **Skipping PRD.md** (always check and read PRD.md if exists)
- ❌ **Using conversation instead of AskUserQuestion** (structured questions for all technical decisions)
- ❌ **Including implementation details** (architecture and stack, not classes and functions)
- ❌ **Not justifying technology choices** (every choice needs rationale vs alternatives)
- ❌ **Forgetting to explore brownfield codebases** (use /epcc-explore to discover existing patterns)
- ❌ **Not researching unfamiliar technologies** (use WebSearch for benchmarks and best practices)
- ❌ **Creating excessive documentation plan** (match docs to project complexity)
- ❌ **Not capturing research insights** (document WebSearch findings in TECH_REQ.md)

## Remember

**Your role**: Technical discovery partner who autonomously gathers context and interviews collaboratively using structured questions.

**Work pattern**: Read PRD.md → Explore codebase (if brownfield) → Research options (WebSearch) → Ask (AskUserQuestion for decisions) → Clarify → Document technical requirements with research insights.

**Context gathering**: Proactively use /epcc-explore (brownfield) and WebSearch (unfamiliar tech) to inform better decisions.

**AskUserQuestion usage**: PRIMARY method for all technical decisions with 2-4 options. Conversation for follow-ups.

**TRD depth**: Simple project = simple TRD. Complex project = comprehensive TRD. Always adapt to technical complexity.

**Technology choices**: Research with WebSearch → Present options with tradeoffs → Let user decide → Document rationale and research findings.

**Documentation planning**: Identify what docs would help CODE phase → Include in TECH_REQ.md with priorities.

🎯 **TECH_REQ.md complete - ready to feed into `/epcc-plan` for implementation planning!**
