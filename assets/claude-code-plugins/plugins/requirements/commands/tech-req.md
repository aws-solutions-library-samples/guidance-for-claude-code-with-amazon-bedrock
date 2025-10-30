---
name: tech-req
description: Technical requirements gathering - Evaluate technologies and architecture through focused questions and guided questionnaire
version: 2.0.0
argument-hint: "[existing-prd-file-or-project-name] [--process TECH_REQ_QUESTIONS.md]"
---

# Tech-Req Command - Technical Requirements Discovery (v2.0)

You are facilitating **TECHNICAL REQUIREMENTS DISCOVERY** using a hybrid approach: **Interactive critical questions** followed by a **self-paced questionnaire**.

⚠️ **IMPORTANT WORKFLOW**:
1. **Read PRD context** (if exists) to extract constraints
2. **Ask 2-3 critical questions** interactively (architecture, cloud, framework category)
3. **Generate questionnaire file** (TECH_REQ_QUESTIONS.md) for remaining decisions
4. **User fills questionnaire** at their own pace
5. **Process questionnaire** (`/tech-req --process TECH_REQ_QUESTIONS.md`) to generate TECH_REQ.md

⚠️ **KEY PRINCIPLES**:
- **Smart Filtering**: Show only 2-3 most relevant options per decision (filtered by PRD constraints)
- **Sequential Decisions**: Later questions depend on earlier answers
- **No Information Overload**: Never present 4+ options simultaneously
- **Strict Separation**: PRD = what/why/who, Tech-Req = how/with what

## Initial Input
$ARGUMENTS

If `--process TECH_REQ_QUESTIONS.md` flag detected:
- Skip to [Questionnaire Processing](#questionnaire-processing) section
- Read answers from file and generate TECH_REQ.md

Otherwise, proceed with interactive discovery.

---

## Step 1: Extract PRD Context

If PRD.md exists, read it and extract:
- **Deployment Preference**: Cloud (AWS/Azure/GCP) / Local / Hybrid
- **Scale**: Expected users/traffic
- **Budget**: Infrastructure cost constraints
- **Team Technical Comfort**: Beginner / Intermediate / Advanced
- **Must Use/Avoid**: Required or forbidden technologies
- **Performance Requirements**: Response time targets
- **Data Needs**: Storage type and volume

**Document Extracted Constraints**:
```markdown
## PRD Constraints Extracted

- **Deployment**: [Cloud provider or preference]
- **Scale**: [User count, traffic estimates]
- **Budget**: [Monthly infrastructure budget]
- **Team Comfort**: [Technical skill level]
- **Must Use**: [Required technologies]
- **Must Avoid**: [Technologies to avoid]
- **Performance**: [Targets if specified]
- **Data**: [Storage needs]
```

If no PRD exists, ask user:
"I don't see a PRD.md file. Would you like me to:
1. Ask a few constraint questions now
2. Generate a PRD first using `/prd`
3. Proceed with general recommendations (no filtering)"

---

## Step 2: Interactive Critical Questions (2-3 questions only)

Ask **ONE question at a time**, wait for answer, adapt next question.

### Question 1: Architecture Pattern (ALWAYS ASK)

**Apply Smart Filtering** based on PRD constraints:

**Filtering Logic**:
- If "single author blog" or "documentation site" → Show only SSG + JAMstack (skip SSR, microservices)
- If "< 10 users" or "internal tool" → Show only Monolithic + Serverless (skip microservices)
- If "need real-time features" → Show SSR + Serverless (skip pure SSG)
- If "> 100 users" and "multiple teams" → Show Microservices + Hybrid
- **Default** (no constraints): Show Monolithic + Serverless + JAMstack (skip microservices unless scale justifies)

**Present Only 2-3 Filtered Options**:

"Based on your requirements [cite PRD constraints], here are the most suitable architecture patterns:

---

### Option 1: [Most Suitable Architecture for Constraints]

**What it is**: [One sentence description]

**Pros**:
- ✅ [Key advantage 1]
- ✅ [Key advantage 2]
- ✅ [Key advantage 3]

**Cons**:
- ❌ [Key limitation 1]
- ❌ [Key limitation 2]

**Best for**: [Specific use case]
**Matches your**: [How it aligns with PRD constraints]
**Cost**: [Monthly estimate]

---

### Option 2: [Second Most Suitable Architecture]

[Same structure as Option 1...]

---

[Optional Option 3 only if legitimately applicable]

---

**My Recommendation**: [Architecture] because [2-3 specific reasons tied to PRD constraints].

**Question**: Which architecture pattern aligns with your vision?"

**Wait for user answer before proceeding.**

---

### Question 2: Cloud Provider (CONDITIONAL)

**Only ask if**:
- PRD deployment preference is "Cloud"
- PRD didn't specify cloud provider preference

**Skip if**:
- PRD says "AWS only" → Auto-select AWS, document decision
- Deployment is Local/Hybrid → Skip to framework question

**Apply Smart Filtering**:
- If Budget < $10/month → Skip Azure/GCP, show AWS (best free tier)
- If "Must Use: Microsoft stack" → Show only Azure
- If no constraints → Show AWS + 1 alternative (GCP if focus is data/ML, Vercel if SSG architecture chosen)

**Present Only 2 Filtered Options**:

"For cloud hosting, here are your best options based on [architecture choice] and [budget/constraints]:

---

### Option 1: AWS
**Why for you**: [Specific reason based on architecture + constraints]
**Monthly Cost**: ~$[X] (for your scale)
**Key Services**: [3-4 services you'd use]

---

### Option 2: [GCP / Azure / PaaS]
**Why for you**: [Specific reason]
**Monthly Cost**: ~$[X]
**Key Services**: [3-4 services you'd use]

---

**My Recommendation**: [Provider] because [reason tied to your constraints].

**Question**: Which cloud provider do you prefer?"

**Wait for user answer before proceeding.**

---

### Question 3: Framework Category (CONDITIONAL)

**Question depends on architecture answer**:

**If SSG architecture chosen** → Ask about static site generators
**If SSR/Monolithic chosen** → Ask about full-stack frameworks
**If Serverless chosen** → Ask about serverless framework preferences

**Apply Smart Filtering** (example for SSG):
- If "performance critical" → Show Astro + Hugo (skip heavier options)
- If "familiar with React" → Show Next.js + Astro
- If "beginner" → Show Hugo + 11ty (skip React-based)
- **Always limit to 2-3 options**

**Example for SSG Architecture**:

"For static site generation with [your requirements], here are the best frameworks:

---

### Option 1: Astro
**Pros**:
- ✅ Excellent performance (zero JS by default)
- ✅ Component flexibility (can use React/Vue/Svelte)
- ✅ Perfect for blogs and content sites

**Cons**:
- ❌ Newer ecosystem (fewer themes than Hugo)

**Best for**: Modern blogs, performance-first
**Learning curve**: Medium
**Matches your**: [Performance requirements, modern tooling preference]

---

### Option 2: Hugo
**Pros**:
- ✅ Extremely fast builds (fastest static generator)
- ✅ Simple setup (single binary, no dependencies)
- ✅ Great for blogs (built-in features)

**Cons**:
- ❌ Go templating (less familiar than JavaScript)

**Best for**: Simple, fast blogs with minimal maintenance
**Learning curve**: Easy-Medium
**Matches your**: [Simplicity preference, performance needs]

---

**My Recommendation**: [Framework] because [specific reason].

**Question**: Which framework appeals to you?"

**Wait for user answer.**

---

## Step 3: Generate Questionnaire File

After 2-3 critical questions answered, generate `TECH_REQ_QUESTIONS.md` for remaining decisions.

**Inform User**:
"Great! Based on your choices:
- Architecture: [Choice]
- Cloud: [Choice]
- Framework: [Choice]

I'll now generate a questionnaire for the remaining technical decisions. You can answer these at your own pace.

**Generating**: `TECH_REQ_QUESTIONS.md`..."

**Generate Questionnaire**:

```markdown
# Technical Requirements Questionnaire

**Project**: [Project name from PRD]
**Date**: [Current date]
**Your Decisions So Far**:
- Architecture: [Architecture choice]
- Cloud Provider: [Cloud choice]
- Framework: [Framework choice]

---

## Instructions

- Replace `[YOUR ANSWER]` with your response
- For multiple choice, select one option or write your own
- Feel free to add notes/context
- **Save this file and run**: `/tech-req --process TECH_REQ_QUESTIONS.md`

---

## Section 1: Styling Approach

Based on your [framework choice], here's what works well:

**Q1.1: CSS Framework**
- [ ] Tailwind CSS - Utility-first, rapid development, great for clean designs
- [ ] Custom CSS - Full control, more time-consuming, learning opportunity
- [ ] [Other]: [Specify if you have a preference]

**Your Choice**: [YOUR ANSWER]

**Q1.2: Why this choice?**
[YOUR ANSWER - Optional]

---

## Section 2: Content Management

**Q2.1: How will you manage content?**

Based on [single author/team size]:
- [ ] Git-based (Markdown files) - Version controlled, developer-friendly
- [ ] Headless CMS (Contentful, Strapi) - Web interface, $20-50/month
- [ ] [Other]: [Specify]

**Your Choice**: [YOUR ANSWER]

**Q2.2: Content workflow preference**
If Git-based: Will you write locally and push, or prefer a web editor?
[YOUR ANSWER]

---

## Section 3: Infrastructure Details

**Q3.1: Specific [Cloud] Services**

For [architecture] on [cloud provider], recommend:
- [ ] [Recommended service stack A] - Simple, managed, ~$[X]/month
- [ ] [Recommended service stack B] - More control, ~$[Y]/month
- [ ] [Other]: [Specify if you have preferences]

**Your Choice**: [YOUR ANSWER]

**Q3.2: Domain Setup**
- [ ] I have a domain: [YOUR DOMAIN NAME]
- [ ] Need to register a domain
- [ ] Will decide later

**Your Choice**: [YOUR ANSWER]

---

## Section 4: Database (if data storage needed)

[Only include if PRD indicated data storage needs]

Based on your data needs ([type and volume from PRD]):
- [ ] [Recommended DB option 1] - [Why it fits]
- [ ] [Recommended DB option 2] - [Alternative if X]
- [ ] [Other]: [Specify]

**Your Choice**: [YOUR ANSWER]

---

## Section 5: Authentication (if needed)

[Only include if PRD indicated auth needs]

For [single/multiple users]:
- [ ] [Managed auth provider] - $0-50/month, handles complexity
- [ ] [Simple auth approach] - Build yourself, more control
- [ ] [Other]: [Specify]

**Your Choice**: [YOUR ANSWER]

---

## Section 6: CI/CD & Deployment

**Q6.1: Deployment Automation**
- [ ] Automated (GitHub Actions deploys on git push) - Recommended
- [ ] Manual (run deploy script when ready) - Simple, more control
- [ ] [Other]: [Specify]

**Your Choice**: [YOUR ANSWER]

**Q6.2: Deployment frequency**
How often will you deploy updates?
- [ ] Multiple times per day
- [ ] Few times per week
- [ ] Once per week or less

**Your Choice**: [YOUR ANSWER]

---

## Section 7: Monitoring & Analytics (Optional)

**Q7.1: Do you need analytics/monitoring?**
- [ ] Yes - Basic (page views, visitors)
- [ ] Yes - Advanced (user behavior, funnels, performance)
- [ ] No - Not needed initially
- [ ] Undecided

**Your Choice**: [YOUR ANSWER]

If yes, any preferences?
[YOUR ANSWER]

---

## Section 8: Additional Requirements

**Q8.1: Any other technical requirements or concerns?**
Examples: SEO needs, accessibility requirements, integrations, etc.

[YOUR ANSWER]

---

## Ready to Generate Tech-Req!

Once you've answered these questions, run:
```bash
/tech-req --process TECH_REQ_QUESTIONS.md
```

This will generate your comprehensive `TECH_REQ.md` document with all technology decisions documented and explained.
```

**Save file as**: `TECH_REQ_QUESTIONS.md`

**Tell User**:
"✅ Generated `TECH_REQ_QUESTIONS.md` with [N] questions.

Take your time answering these. When ready, run:
`/tech-req --process TECH_REQ_QUESTIONS.md`

This will generate your final `TECH_REQ.md` document."

---

## Questionnaire Processing

When user runs: `/tech-req --process TECH_REQ_QUESTIONS.md`

### Step 1: Read and Parse Answers

Read `TECH_REQ_QUESTIONS.md` and extract all `[YOUR ANSWER]` responses.

**Validation**:
- Check all required questions are answered
- If any missing, prompt: "Please answer Question X.Y before I can proceed."

### Step 2: Generate TECH_REQ.md

Create comprehensive technical requirements document:

```markdown
# Technical Requirements Document: [Project Name]

**Created**: [Date]
**Version**: 1.0
**Status**: Ready for Implementation
**Related Documents**: PRD.md

---

## Executive Summary

[2-3 sentence overview of technical approach based on architecture, cloud, and framework choices]

**Key Decisions**:
- Architecture: [Architecture] - [One line rationale]
- Cloud: [Provider] - [One line rationale]
- Framework: [Framework] - [One line rationale]
- Estimated Monthly Cost: ~$[X]

---

## Architecture Decision

### Pattern Chosen: [Architecture]

**Rationale**:
[2-3 paragraphs explaining why this architecture was chosen based on PRD requirements and user answers]

**Key characteristics**:
- [Characteristic 1 relevant to their project]
- [Characteristic 2]
- [Characteristic 3]

**System Components**:
```
[Simple ASCII diagram or description of main components]
Example for SSG:
User → CloudFront (CDN) → S3 (Static Files)
Developer → Git Push → GitHub Actions → Build → S3
```

**Trade-offs Accepted**:
- ✅ Gaining: [What this architecture provides]
- ⚠️ Accepting: [What limitations we're accepting and why they're okay]

---

## Technology Stack

### [Framework Category]: [Chosen Framework]

**Rationale**: [Why this framework based on requirements]

**Alternatives Considered**:
- [Alt 1]: Not chosen because [reason]
- [Alt 2]: Not chosen because [reason]

**Key Features We'll Use**:
- [Feature 1]: [How it helps the project]
- [Feature 2]: [How it helps the project]

### Styling: [Choice]

**Rationale**: [Why this styling approach]

### Content Management: [Choice]

**Workflow**: [Describe the content creation workflow based on answer]

**Tools Needed**:
- [Tool 1]: [Purpose]
- [Tool 2]: [Purpose]

---

## Infrastructure

### Cloud Platform: [Provider]

**Services to Use**:
- **[Service 1]**: [Purpose and configuration]
- **[Service 2]**: [Purpose and configuration]
- **[Service 3]**: [Purpose and configuration]

**Architecture Diagram**:
```
[Service-level architecture showing how cloud services connect]
```

### Domain: [Status from questionnaire]

[If domain exists]: Using [domain name]
[If needs registration]: Will register through [recommended registrar]

### CI/CD Pipeline

**Approach**: [Automated/Manual from questionnaire]

[If automated]:
**Pipeline Steps**:
1. Developer commits code → Git push
2. GitHub Actions triggered
3. Build [framework] site
4. Run tests (if applicable)
5. Deploy to [cloud service]
6. Invalidate cache (if CDN)
7. Verify deployment

**Estimated Deploy Time**: [X] minutes per deployment

[If manual]:
**Deployment Process**:
1. Run build locally: `[build command]`
2. Deploy via CLI: `[deploy command]`
3. Verify in browser

---

## Data & Authentication

[Only include sections if applicable based on PRD and questionnaire]

### Database: [If applicable]
**Choice**: [Database]
**Rationale**: [Why this database for their data needs]
**Schema Overview**: [Key tables/collections]

### Authentication: [If applicable]
**Approach**: [Chosen auth method]
**Provider**: [If using managed service]
**Rationale**: [Why this approach]

---

## Monitoring & Analytics

[Based on questionnaire answer]

**Approach**: [Choice from questionnaire]

[If selected analytics]:
**Tools**:
- [Tool]: [Purpose]

**Key Metrics to Track**:
- [Metric 1]
- [Metric 2]

---

## Performance & Scalability

### Performance Targets

Based on PRD requirements:
- **Page Load Time**: [Target from PRD or < 2s default]
- **Time to First Byte**: [Target]
- **API Response Time**: [Target if applicable]

### Scalability Plan

**Phase 1** (Launch - [X] users):
[Initial setup sufficient for early users]

**Phase 2** ([X-Y] users):
[What changes when traffic increases]

**Phase 3** ([Y+] users):
[Scaling approach for higher traffic]

**Cost Projection**:
- Phase 1: ~$[X]/month
- Phase 2: ~$[Y]/month
- Phase 3: ~$[Z]/month

---

## Cost Estimation

### Monthly Infrastructure Costs

**Itemized Breakdown**:
- [Service/Component 1]: $[X]
- [Service/Component 2]: $[Y]
- [Service/Component 3]: $[Z]
- **Total**: ~$[Sum]/month

**Cost Variables**:
- Traffic-dependent: [What costs scale with traffic]
- Fixed: [What costs are constant]

**Optimization Opportunities**:
- [Way to reduce costs if needed]
- [Alternative if budget changes]

---

## Technology Decision Summary

| Decision Category | Chosen Technology | Rationale | Alternatives Considered |
|------------------|-------------------|-----------|------------------------|
| Architecture | [Choice] | [One sentence] | [List] |
| Cloud Provider | [Choice] | [One sentence] | [List] |
| Framework | [Choice] | [One sentence] | [List] |
| Styling | [Choice] | [One sentence] | [List] |
| Content Mgmt | [Choice] | [One sentence] | [List] |
| Database | [Choice/N/A] | [One sentence] | [List] |
| Authentication | [Choice/N/A] | [One sentence] | [List] |
| CI/CD | [Choice] | [One sentence] | [List] |

---

## Implementation Roadmap

### Phase 1: Foundation (Week 1-2)
- [ ] Set up [cloud] account and configure services
- [ ] Initialize [framework] project
- [ ] Configure [styling approach]
- [ ] Set up development environment
- [ ] Create hello-world deployment

### Phase 2: Core Features (Week 3-4)
- [ ] Implement [key feature 1 from PRD]
- [ ] Implement [key feature 2 from PRD]
- [ ] Set up [content management]
- [ ] Configure CI/CD pipeline

### Phase 3: Polish & Launch (Week 5-6)
- [ ] Performance optimization
- [ ] SEO configuration
- [ ] Testing and bug fixes
- [ ] Domain setup and SSL
- [ ] Launch! 🚀

---

## Risks & Mitigation

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| [Tech Risk 1] | [H/M/L] | [H/M/L] | [How to mitigate] |
| [Cost Risk] | [H/M/L] | [H/M/L] | [How to mitigate] |
| [Scaling Risk] | [H/M/L] | [H/M/L] | [How to mitigate] |

---

## Open Questions

- [ ] [Any remaining technical questions]
- [ ] [Decisions that need prototyping]

---

## Next Steps

1. **Review this document** - Does everything make sense? Any concerns?
2. **Prototype (Optional)** - Try [framework] with a hello-world if unfamiliar
3. **Begin Implementation**:
   - Option A: Direct implementation
   - Option B: Use EPCC workflow - `/epcc-explore` to analyze patterns and start coding
4. **Set up infrastructure** - Follow Phase 1 of Implementation Roadmap

---

## Appendix: Useful Resources

### Documentation Links
- [Framework]: [Official docs URL]
- [Cloud Provider]: [Getting started guide]
- [Key Tool/Service]: [Tutorial]

### Example Projects
- [Similar project 1]: [Why it's relevant]
- [Similar project 2]: [Why it's relevant]

### Community Resources
- [Forum/Discord]: [Link]
- [Stack Overflow Tag]: [Link]

---

**Technical Requirements Complete!** Ready to build 🚀
```

**Save as**: `TECH_REQ.md`

---

## After Generation

**Tell User**:
"✅ **Tech-Req Complete!** Generated `TECH_REQ.md` with your complete technical specification.

**Key Decisions**:
- Architecture: [Choice]
- Cloud: [Provider]
- Framework: [Framework]
- Estimated Cost: ~$[X]/month

**Next Steps**:

1. **Review TECH_REQ.md** - Make sure everything aligns with your vision
2. **Start Building**:
   - Direct implementation using the roadmap in TECH_REQ.md
   - OR use `/epcc-explore` to analyze existing patterns and start EPCC workflow

The technical foundation is set - time to build!"

---

## Smart Filtering Rules Reference

### Budget-Based Filtering
- **< $10/month**: Show managed/PaaS options, skip enterprise services
- **$10-50/month**: Show PaaS + basic cloud setups
- **> $50/month**: Show all options including complex architectures

### Scale-Based Filtering
- **< 1k users**: Skip microservices, show monolithic/serverless/SSG
- **1k-10k users**: Show most architectures except microservices
- **> 10k users**: Show all including microservices

### Complexity-Based Filtering
- **Beginner**: Show managed services, simple frameworks, PaaS
- **Intermediate**: Show most options
- **Advanced**: Show all including custom infrastructure

### Use Case-Based Filtering
- **Blog/Documentation**: Show only SSG + JAMstack
- **Internal Tool (< 10 users)**: Show monolithic + serverless
- **SaaS Application**: Show SSR + Microservices + Hybrid
- **E-commerce**: Show SSR + Hybrid (need dynamic + static)

---

## Example Filtered Question

**Bad** (Information Overload):
```
Here are 5 architecture options: Monolithic (pros: A, B, C, cons: D, E, F),
Microservices (pros: G, H, I, cons: J, K, L), Serverless (pros: M, N, O, cons: P, Q, R),
JAMstack (pros: S, T, U, cons: V, W, X), Hybrid (pros: Y, Z, AA, cons: BB, CC, DD)...
```
👎 User has to process 15 pros + 15 cons = 30 points before answering

**Good** (Smart Filtered):
```
Based on your single-author blog with < 1k users, here are the 2 best options:

Option 1: Static Site Generator
✅ Maximum performance, ✅ Minimal cost ($2-5/month), ✅ Perfect for blogs
❌ No dynamic features

Option 2: JAMstack
✅ Static performance + some dynamic features, ✅ Cost-effective
❌ More complex than pure SSG

Recommendation: SSG - matches your use case perfectly.
Which appeals to you?
```
👍 User processes 4 pros + 2 cons = 6 points, makes decision quickly
