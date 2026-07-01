# High-Level Cost Estimates

This guide gives operations and finance teams a high-level estimate of what it costs to deploy and operate this solution, broken down into **fixed infrastructure costs** (independent of how much your developers use Claude Code) and **variable Amazon Bedrock costs** (driven by per-user token consumption).

> **Disclaimer:** All figures below are **approximate** and intended for planning only. Actual costs vary by AWS Region, usage patterns, and AWS pricing changes. Bedrock token rates change over time and differ by model — always confirm against the live pricing pages linked in [Pricing references](#pricing-references) before committing to a budget. Examples use **US East (N. Virginia)** on-demand pricing as of June 2026. Non-US regions (e.g. ap-southeast-2, eu-west-1) typically charge 10–20% more for Bedrock models.

## How costs break down

| Cost type | What drives it | Rough magnitude |
|---|---|---|
| **Fixed infrastructure** | The AWS resources deployed by the stacks (auth, optional monitoring, optional analytics, optional quota). Mostly independent of user count. | $0 to ~$60/month |
| **Variable Bedrock usage** | Input/output tokens each developer sends to Claude models. Scales linearly with the number of active developers and how heavily they use Claude Code. | Dominant cost — typically **>95% of the total bill** |

The key takeaway: **Bedrock token usage dwarfs infrastructure cost.** Infrastructure is a rounding error next to a team of active developers, so optimization effort is best spent on token usage (model choice, prompt caching) rather than trimming infrastructure.

---

## Fixed infrastructure costs

The solution is deployed in tiers. You only pay for the tiers you enable. The table below is cumulative — each row adds to the ones above it.

| Tier | AWS resources | Required? | Est. monthly cost |
|---|---|---|---|
| **Authentication** | Cognito Identity Pool, IAM OIDC provider, IAM roles/policies, a CloudWatch log group | **Required** | **~$0–$5** |
| **Monitoring — Sidecar mode** | CloudWatch dashboard + metrics ingested via the OTLP endpoint. No VPC, ECS, or ALB. | Optional | **~$0–$15** |
| **Monitoring — Central mode** | VPC (public subnets + Internet Gateway), 1× ECS Fargate task (0.5 vCPU / 1 GB, 24/7), 1× Application Load Balancer, CloudWatch logs/metrics | Optional (alternative to Sidecar) | **~$30–$55** |
| **Analytics add-on** | Kinesis Data Firehose, S3 data lake, Glue Data Catalog, Athena workgroup, transform Lambda | Optional (requires Central mode) | **~$5–$30** |
| **Quota monitoring** | 2× scheduled Lambda (every 15 min), 1× API Lambda, 2× DynamoDB tables (on-demand), HTTP API Gateway, SNS topic | Optional | **~$5–$15** |

### Notes on the infrastructure tiers

- **Authentication is effectively free at idle.** Cognito Identity Pools have no standing charge; you pay only negligible CloudWatch Logs costs. (If you use the Cognito **User Pool** identity path instead of an external IdP, Cognito bills per monthly active user — see the [Cognito pricing page](https://aws.amazon.com/cognito/pricing/).)

- **Monitoring is optional and comes in two modes** (see [MONITORING.md](./MONITORING.md)):
  - **Sidecar mode** runs no cloud collector. Each developer's machine sends metrics directly to the CloudWatch OTLP endpoint using SigV4 auth. The only AWS-side resource is the dashboard stack, so cloud infrastructure cost is essentially **$0** beyond CloudWatch metric/dashboard charges. This is the most cost-effective option and is recommended for dev/test or budget-conscious deployments.
  - **Central mode** deploys a shared OpenTelemetry collector on ECS Fargate behind an ALB. This is the ~24/7 fixed cost below, and it is required if you want the Athena SQL analytics pipeline.

- **There is no NAT Gateway.** The networking stack creates a VPC with **public subnets and an Internet Gateway only**; the Fargate task runs with a public IP. This avoids the ~$32+/month a NAT Gateway would add. The only related charge is a single public IPv4 address (~$3.65/month).

#### Central monitoring cost breakdown (~$30–$55/month)

| Component | Configuration | Est. monthly cost |
|---|---|---|
| ECS Fargate task | 0.5 vCPU / 1 GB, on-demand, 24/7 | ~$18 |
| Application Load Balancer | 1 ALB + LCUs | ~$18–$25 |
| Public IPv4 address | 1 address on the Fargate task | ~$4 |
| CloudWatch logs + metrics | Collector logs (7-day retention) + metric ingestion | ~$5–$10 |
| CloudWatch dashboard | First 3 dashboards free, then $3 each | ~$0–$3 |

---

## Variable Bedrock costs (per user)

This is the part that scales with your team. Token pricing follows a consistent ratio across model tiers: Haiku ≈ 1/3× Sonnet ≈ 1/5× Opus. The table below shows two usage profiles over **22 working days/month**.

On-demand pricing, US East (N. Virginia) — always confirm rates at the [Bedrock pricing page](https://aws.amazon.com/bedrock/pricing/):

| Model | Input ($/1M) | Output ($/1M) | Cache read ($/1M) | Moderate user/month | Heavy user/month |
|---|---|---|---|---|---|
| **Claude Haiku 4.5** | $1.00 | $5.00 | $0.10 | **~$25** | **~$99** |
| **Claude Sonnet 4.5 / 4.6** | $3.00 | $15.00 | $0.30 | **~$66** | **~$297** |
| **Claude Opus 4.5–4.8** | $5.00 | $25.00 | $0.50 | **~$110** | **~$495** |

> **Moderate user:** ~500K input + 100K output tokens/day (typical developer with standard coding sessions).  
> **Heavy user:** ~2M input + 500K output tokens/day (power user with extended context, large codebases, multi-hour sessions).

> **Prompt caching changes the math significantly.** Claude Code reuses large, stable context (system prompts, file contents, conversation history) on nearly every request. With caching, those repeated input tokens are billed at the **cache-read rate** — for Sonnet that's **$0.30/1M instead of $3.00/1M, a 90% reduction on cached input.** Because input tokens dominate coding workloads, effective per-user cost is often well below the on-demand figures above. See [Cost optimization levers](#cost-optimization-levers).

---

## Total estimated monthly cost by team size

Combining fixed infrastructure with variable Bedrock usage. Infrastructure adds ~$0 (sidecar) to ~$45 (central monitoring) — negligible at any team size. The dominant variable is model choice and usage intensity.

| Team size | Sonnet (moderate) | Sonnet (heavy) | Haiku (heavy) | Notes |
|---|---|---|---|---|
| **10 users** | ~$660 | ~$2,970 | ~$990 | Pilot team |
| **25 users** | ~$1,650 | ~$7,425 | ~$2,475 | Department |
| **50 users** | ~$3,300 | ~$14,850 | ~$4,950 | Division |
| **100 users** | ~$6,600 | ~$29,700 | ~$9,900 | Enterprise |

> Add ~$45/month for central monitoring infrastructure. Sidecar mode adds ~$0. Infrastructure is <1% of total cost at any scale.

**Model choice and prompt caching move the number far more than any infrastructure decision.** The same 50-user team costs ~$14,850/month (Sonnet heavy) vs ~$3,300/month (Sonnet moderate) vs ~$4,950/month (Haiku heavy) — a 3–4× spread driven purely by usage pattern and model tier.

---

## Cost optimization levers

Ordered by typical impact:

1. **Prompt caching** — Claude Code's repeated context is billed at the cache-read rate (e.g., $0.30/1M vs $3.00/1M for Sonnet — up to a 90% reduction on cached input tokens). This is the single largest lever for coding workloads and is automatic where supported.

2. **Right-size the model** — Route routine work to **Haiku 4.5** ($1/$5 per 1M) and reserve **Sonnet** or **Opus** for complex tasks. Haiku is roughly 1/3 the cost of Sonnet and ~1/5 the cost of Opus for the same token volume.

3. **Batch inference** — Non-interactive/asynchronous workloads qualify for **~50% off** input and output token rates (where batch pricing is available for the model).

4. **Use Sidecar monitoring** — Eliminates the ~$30–$55/month Central-mode ECS + ALB footprint where you don't need the Athena analytics pipeline.

5. **Set token quotas** — The optional [quota monitoring](./QUOTA_MONITORING.md) stack enforces per-user and per-group token budgets to prevent runaway spend.

6. **Skip optional tiers in non-prod** — Disable monitoring and analytics entirely for dev/test environments to land at the ~$0–$5/month auth-only floor.

For tracking actual spend per user and per team after deployment, see [COST_ATTRIBUTION.md](./COST_ATTRIBUTION.md).

---

## Pricing references

- [Amazon Bedrock pricing](https://aws.amazon.com/bedrock/pricing/) — authoritative source for current Claude token rates
- [AWS Fargate pricing](https://aws.amazon.com/fargate/pricing/)
- [Application Load Balancer pricing](https://aws.amazon.com/elasticloadbalancing/pricing/)
- [Amazon CloudWatch pricing](https://aws.amazon.com/cloudwatch/pricing/)
- [Amazon Kinesis Data Firehose pricing](https://aws.amazon.com/firehose/pricing/)
- [Amazon Athena pricing](https://aws.amazon.com/athena/pricing/)
- [Amazon Cognito pricing](https://aws.amazon.com/cognito/pricing/)
- [AWS Pricing Calculator](https://calculator.aws/) — build a tailored estimate for your Region and usage
