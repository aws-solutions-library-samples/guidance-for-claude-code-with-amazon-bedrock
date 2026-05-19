# Claude Code Monitoring Implementation

This guide explains how to deploy and use the optional monitoring system for tracking Claude Code usage through Amazon Bedrock.

When you enable monitoring during deployment, the system collects and visualizes usage metrics from Claude Code using an OpenTelemetry (OTEL) Collector that forwards metrics to CloudWatch. You can choose between two monitoring modes depending on your infrastructure needs and budget.

## Monitoring Modes

### Central Collector (ECS Fargate)

- Server-side OpenTelemetry collector running on ECS Fargate behind an ALB
- Supports optional Athena SQL pipeline (EMF logs → Kinesis Firehose → S3 → Athena) for ad-hoc SQL queries
- Requires VPC and networking infrastructure
- ~$30-50/month server cost
- Best for: organizations wanting centralized metrics aggregation, IT-managed collector, or ad-hoc SQL queries via Athena

### Sidecar Collector (Local)

- Lightweight (~15-20MB) collector binary runs on each developer's machine
- Sends metrics directly to CloudWatch OTLP endpoint using SigV4 auth from federated credentials
- No server-side infrastructure required
- $0 server cost
- Athena SQL pipeline not available (PromQL dashboards and long-term CloudWatch metric storage are fully supported)
- Best for: small teams, cost-sensitive deployments, or quick evaluation

Both modes provide full analytics via the same PromQL-based CloudWatch dashboard with long-term metric storage. The Athena SQL pipeline (central-mode only) is an optional add-on for ad-hoc SQL queries against raw metric data.

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

## Usage Quota Monitoring

Quota monitoring uses the CloudWatch Prometheus-compatible API (`monitoring.<region>.amazonaws.com/api/v1/query`) to query per-user token usage via PromQL. The quota monitor Lambda runs every 15 minutes, fetches usage data via PromQL, writes results to a DynamoDB table (`UserQuotaMetrics`), and checks against quota policies.

The quota check Lambda provides real-time allow/block decisions by reading the DynamoDB table (fast reads, at most 15 minutes stale).

> **Detailed Information**: See the [Quota Monitoring Guide](QUOTA_MONITORING.md).

## Analytics Pipeline (Optional)

The analytics pipeline streams EMF logs from CloudWatch Logs to S3 using Kinesis Data Firehose, converting metrics to Parquet format. AWS Athena provides SQL query capabilities over months of historical data.

This is separate from the PromQL dashboard — PromQL has a 7-day query range limit, while the analytics pipeline provides unlimited historical lookback via Athena SQL.

> **Note**: The analytics pipeline requires `analytics_enabled=true` in your profile. This causes the collector to dual-export (OTLP + EMF). When analytics is disabled, the collector only exports via OTLP — no EMF logs are written and no classic CloudWatch metrics are published.
