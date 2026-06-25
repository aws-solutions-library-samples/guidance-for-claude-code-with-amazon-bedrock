# Claude Code Monitoring Implementation

This guide explains how to deploy and use the optional monitoring system for tracking Claude Code usage through Amazon Bedrock.

When you enable monitoring during deployment, the system collects and visualizes usage metrics from Claude Code using an OpenTelemetry (OTEL) Collector that forwards metrics to CloudWatch. You can choose between two monitoring modes depending on your infrastructure needs and budget.

## Monitoring Modes

| | Central | Sidecar |
|---|---|---|
| **Cloud infrastructure** | VPC + ECS Fargate + ALB | None |
| **AWS cost** | ~$30-50/month | $0 |
| **Athena SQL queries** | Yes | No |
| **PromQL dashboards** | Yes | Yes |
| **Client reports to** | ALB endpoint | CloudWatch OTLP directly |

**Sidecar mode** requires no cloud collector infrastructure — each client sends metrics directly to the CloudWatch OTLP endpoint (`monitoring.<region>.amazonaws.com`) using SigV4 auth. Only the CloudWatch dashboard stack is deployed on the AWS side.

**Central mode** deploys a shared ECS Fargate collector behind an ALB. Required if you need the Athena SQL analytics pipeline (EMF logs → Firehose → S3 → Athena).

## Central Collector (ECS Fargate)

- Server-side OpenTelemetry collector running on ECS Fargate behind an ALB
- Supports optional Athena SQL pipeline (EMF logs → Kinesis Firehose → S3 → Athena) for ad-hoc SQL queries
- Requires VPC and networking infrastructure
- Requires the `AWSServiceRoleForECS` service-linked role (created automatically by `ccwb deploy`; if deploying templates manually, create it first: `aws iam create-service-linked-role --aws-service-name ecs.amazonaws.com`)

### Central mode deployment

```bash
# During ccwb init, select "Central" when prompted for monitoring mode
poetry run ccwb init

# Deploy (creates VPC, ECS, ALB, dashboard)
poetry run ccwb deploy
```

## Sidecar Collector (Local)

- Lightweight (~15-20MB) Go binary (`otel-helper`) runs on each developer's machine
- Sends metrics directly to CloudWatch OTLP endpoint using SigV4 auth from federated credentials
- No server-side infrastructure required — only the CloudWatch dashboard stack is deployed

### Sidecar mode deployment

```bash
# During ccwb init, select "Sidecar" when prompted for monitoring mode
poetry run ccwb init

# Deploy (creates only the dashboard stack — no VPC, no ECS)
poetry run ccwb deploy

# Package includes otel-helper binary automatically
poetry run ccwb package --go --target-platform all
```

End users receive the `otel-helper` binary in their install package. It starts automatically when Claude Code launches and sends metrics to CloudWatch using the same federated credentials.

## Architecture (Central Collector)

The following describes the Central Collector (ECS Fargate) architecture. The Sidecar Collector uses the same metric format but sends directly from the developer's machine to the CloudWatch OTLP endpoint — no ALB, ECS, or VPC required.

The collector's export behavior depends on whether analytics is enabled:

- **Analytics disabled** (default): The collector exports metrics only to the CloudWatch OTLP endpoint (`monitoring.<region>.amazonaws.com`) using SigV4 authentication. These metrics are queryable via PromQL in CloudWatch dashboards and alarms. No EMF logs or classic CloudWatch metrics are published.

- **Analytics enabled**: The collector dual-exports — OTLP for real-time PromQL dashboards, plus EMF (Embedded Metric Format) logs to a CloudWatch Log Group (`/aws/claude-code/metrics`). The EMF stream feeds the optional analytics pipeline (Kinesis Firehose → S3 → Athena) for long-term historical SQL analysis.

This is controlled by the `EnableAnalytics` parameter on the `otel-collector.yaml` CloudFormation stack, which `ccwb deploy` sets automatically based on your `analytics_enabled` profile setting.

The CloudWatch Dashboard uses native PromQL chart widgets — no Lambda functions or DynamoDB tables required. All dashboard queries run directly against OTLP-ingested metrics.

## Implementation Details

The core component runs as an ECS Fargate service using the AWS Distro for OpenTelemetry (ADOT) Collector image. The service runs with minimal resources (0.25 vCPU and 0.5 GB memory). An Application Load Balancer sits in front of the ECS service, receiving OTLP metrics on port 4318.

### Configuration

The OTEL Collector configuration defines how metrics flow through the system:

- **Receivers**: OTLP on ports 4317 (gRPC) and 4318 (HTTP) with metadata extraction
- **Processors**: Attributes processor extracts user info from HTTP headers (email, department, team, etc.), resource processor adds AWS account ID
- **Exporters**:
  - `otlphttp` — sends to CloudWatch OTLP endpoint with SigV4 auth (for PromQL dashboards)
  - `awsemf` — writes EMF logs to `/aws/claude-code/metrics` (for analytics pipeline)

### Metrics

Claude Code sends several metric types:

- `claude_code.token.usage` — Input/output/cache token consumption (dimensions: type, model, user.email)
- `claude_code.session.count` — Active sessions
- `claude_code.active_time.total` — Time spent actively using Claude Code
- `claude_code.cost.usage` — Estimated costs based on token usage
- `claude_code.code_edit_tool.decision` — Code editing decisions (dimensions: language, tool_name, decision)
- `claude_code.lines_of_code.count` — Lines added/removed
- `claude_code.commit.count` — Commits
- `claude_code.pull_request.count` — Pull requests

### Dashboard

The CloudWatch Dashboard uses PromQL queries over OTLP-ingested metrics. Sections include:

- **Overview** — Total tokens, active users, sessions, cache hit rate
- **Token Usage** — Usage over time, by type, by model, top users, cost by user
- **Developer Productivity** — Lines of code, commits, active hours, pull requests, code generation by language
- **Organizational Breakdown** — Token usage by department and team
- **Bedrock API Health** — Throttles, client errors, server errors by model

### Per-user attribution (`user.email`)

The collector sets the `user.email` dimension from the `x-user-email` request
header, which Claude Code sends only when `otelHeadersHelper` (the `otel-helper`
binary) is configured in `settings.json`. How the email is resolved depends on
the auth type:

- **OIDC** — extracted from the JWT `email` claim.
- **IDC (with the credential-process binary, e.g. when quota is enabled)** —
  resolved from the IAM ARN session name (`assumed-role/Role/user@company.com`)
  and cached by the credential process; the helper serves it. Per-user dashboard
  attribution works the same as OIDC. *(Requires repackaging with a build that
  wires `otelHeadersHelper` for IDC — older packages attributed all IDC users to
  one static identity.)*
- **IDC zero-binary (no credential-process)** — there is no runtime identity
  resolver, so a single static identity is baked into the collector config at
  package time; all telemetry is attributed to that one identity.

Note: richer OTEL dimensions (department, team, project) come from JWT claims and
are only populated for OIDC. IDC attributes `user.email` only. See
[Cost Attribution](COST_ATTRIBUTION.md#idc-limitation) for the CUR/ABAC path to
per-user team/department breakdowns under IDC.

## Usage Quota Monitoring

Quota monitoring uses the CloudWatch Prometheus-compatible API (`monitoring.<region>.amazonaws.com/api/v1/query`) to query per-user token usage via PromQL. The quota monitor Lambda runs every 15 minutes, fetches usage data via PromQL, writes results to a DynamoDB table (`UserQuotaMetrics`), and checks against quota policies.

The quota check Lambda provides real-time allow/block decisions by reading the DynamoDB table (fast reads, at most 15 minutes stale).

Both Claude Code and CoWork 3P (Claude Desktop) usage are counted toward the same per-user quota when the CoWork dashboard stack is deployed. See [CoWork 3P Quota Enforcement](COWORK_3P.md#quota-enforcement) for details.

> **Detailed Information**: See the [Quota Monitoring Guide](QUOTA_MONITORING.md).

## Analytics Pipeline (Optional)

The analytics pipeline streams EMF logs from CloudWatch Logs to S3 using Kinesis Data Firehose, converting metrics to Parquet format. AWS Athena provides SQL query capabilities over months of historical data.

This is separate from the PromQL dashboard — PromQL has a 7-day query range limit, while the analytics pipeline provides unlimited historical lookback via Athena SQL.

> **Note**: The analytics pipeline requires `analytics_enabled=true` in your profile. This causes the collector to dual-export (OTLP + EMF). When analytics is disabled, the collector only exports via OTLP — no EMF logs are written and no classic CloudWatch metrics are published.
