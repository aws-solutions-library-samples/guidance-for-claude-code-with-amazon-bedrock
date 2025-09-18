# Claude Code Monitoring Implementation

This guide explains how to deploy and use the optional monitoring system for tracking Claude Code usage through Amazon Bedrock.

When you enable monitoring during deployment, the system creates infrastructure to collect and visualize usage metrics from Claude Code. The monitoring stack deploys an OpenTelemetry (OTEL) Collector on AWS ECS Fargate that receives metrics from Claude Code and forwards them to CloudWatch for visualization and analysis.

## Architecture

The monitoring system consists of several components working together. Claude Code sends metrics using the OpenTelemetry Protocol (OTLP) to an Application Load Balancer. The ALB forwards these metrics to an OTEL Collector running on ECS Fargate. The collector then converts the metrics to CloudWatch's Embedded Metric Format (EMF) and sends them to CloudWatch Metrics and Logs. Finally, a CloudWatch Dashboard visualizes these metrics.

## Implementation Details

The monitoring infrastructure deploys several AWS resources to handle metric collection and visualization.

The core component runs as an ECS Fargate service using the AWS Distro for OpenTelemetry (ADOT) Collector image. The service runs with minimal resources (0.25 vCPU and 0.5 GB memory) in private subnets within your VPC. While the CloudFormation template includes auto-scaling configuration for 1-3 tasks based on CPU utilization, this feature requires the ECS service-linked role to be created in your account.

An Application Load Balancer sits in front of the ECS service, receiving OTLP metrics on port 4318. The ALB supports both HTTP and HTTPS protocols. When you provide a custom domain name during deployment, the system automatically creates an ACM certificate and configures HTTPS. Health checks monitor the collector's availability through the root endpoint.

The CloudWatch Dashboard provides comprehensive visualization of your Claude Code usage. The dashboard uses Lambda functions and DynamoDB for efficient metrics collection and display, presenting real-time and historical usage data through custom widgets.

### Configuration

The OTEL Collector configuration defines how metrics flow through the system. The collector listens for OTLP traffic on port 4318 and processes metrics in batches every 60 seconds before sending them to CloudWatch.

The configuration includes an attributes processor that extracts user information from HTTP headers sent by the OTEL helper binary. These headers contain user details from the JWT token, including email, user ID, department, team, cost center, and other organizational attributes. The collector maps these headers to resource attributes that become dimensions in CloudWatch.

Claude Code sends several metric types that the collector processes:

- `claude_code.token.usage` - Tracks input and output token consumption
- `claude_code.session.count` - Counts active sessions
- `claude_code.active_time.total` - Measures time spent actively using Claude Code
- `claude_code.cost.usage` - Estimates costs based on token usage
- `claude_code.code_edit_tool.decision` - Records code editing decisions

## Usage Quota Monitoring

The monitoring system supports optional quota tracking to alert administrators when users approach or exceed token usage limits. This helps manage costs and prevent unexpected overages.

Quota monitoring deploys as a separate CloudFormation stack that integrates with the dashboard infrastructure. When enabled, it tracks monthly token consumption per user and sends automated alerts through Amazon SNS when usage thresholds are exceeded.

> **Detailed Information**: For complete quota monitoring setup, configuration, and usage instructions, see the [Quota Monitoring Guide](QUOTA_MONITORING.md).


## Analytics Pipeline (Optional)

Beyond real-time monitoring through CloudWatch, you can enable an analytics pipeline for advanced reporting and historical analysis. The analytics stack creates a data lake for long-term metric storage and analysis.

The analytics pipeline streams CloudWatch Logs to S3 using Kinesis Data Firehose, converting metrics to Parquet format for efficient querying. The S3 data lake automatically archives older data to Glacier for cost-effective long-term storage. AWS Athena provides SQL query capabilities over your metrics data, with automatic partition projection that eliminates the need for Glue crawlers.

This architecture enables several powerful capabilities. You can track individual user token usage over time, query months of historical data efficiently, allocate costs by user, department, or project, and create custom reports using standard SQL. The system includes pre-built queries for common analytics tasks like identifying top users by token consumption, analyzing token usage by model and type, understanding user activity patterns by hour, and forecasting costs based on usage trends.

## Deployment Process

Monitoring deployment happens during the initial setup when you run `poetry run ccwb init`. The interactive wizard prompts you to enable monitoring and configure the necessary infrastructure.

```bash
poetry run ccwb init
```

When prompted about monitoring, answering yes triggers additional configuration options. You can either let the system create a new VPC or use an existing one. For existing VPCs, you'll select the VPC ID and at least two subnets for the Application Load Balancer.

The deployment creates the complete monitoring infrastructure: a VPC with public and private subnets (if not using an existing VPC), an ECS cluster and task definition for the OTEL Collector, the collector service itself, an Application Load Balancer to receive metrics, and CloudWatch log groups for storing logs and metrics.

If you provide a custom domain name and hosted zone ID during setup, the system automatically provisions an ACM certificate and configures HTTPS. This ensures encrypted transmission of metrics from Claude Code to your collector.

The dashboard stack creates the metrics aggregation infrastructure that supports quota monitoring. If you choose to deploy quota monitoring as a separate stack, it integrates with the dashboard's metrics table to track user consumption.

## Claude Code Configuration

The package command generates a `claude-settings/settings.json` file in the distribution package that configures Claude Code for telemetry collection. During installation, this file gets copied to `~/.claude/settings.json` in the user's home directory and contains all the settings needed for monitoring.

```json
{
  "env": {
    "CLAUDE_CODE_USE_BEDROCK": "1",
    "AWS_PROFILE": "ClaudeCode",
    "AWS_REGION": "us-east-1",
    "CLAUDE_CODE_ENABLE_TELEMETRY": "1",
    "OTEL_METRICS_EXPORTER": "otlp",
    "OTEL_LOGS_EXPORTER": "otlp",
    "OTEL_EXPORTER_OTLP_PROTOCOL": "http/protobuf",
    "OTEL_EXPORTER_OTLP_ENDPOINT": "http://otel-collector-alb-xxxxx.us-east-1.elb.amazonaws.com",
    "OTEL_RESOURCE_ATTRIBUTES": "department=engineering,team.id=default,cost_center=default,organization=default"
  },
  "otelHeadersHelper": "~/claude-code-with-bedrock/otel-helper"
}
```

The configuration enables Bedrock usage and sets the AWS profile for authentication. It activates telemetry collection and configures the OTLP exporter to send metrics to your deployed collector endpoint. The OTEL resource attributes provide default organizational tags that can be overridden by environment variables.

The `otelHeadersHelper` points to the installed OTEL helper binary. This helper extracts user information from the JWT token stored by the authentication process and sends it as HTTP headers with each metric. The OTEL Collector then converts these headers into CloudWatch dimensions for user attribution.

## Metrics Collected

The monitoring system tracks comprehensive metrics about Claude Code usage, with each metric tagged with user and organizational attributes for detailed analysis.

For token usage, the system tracks `claude.tokens.input` for input tokens per request, `claude.tokens.output` for generated output tokens, and `claude.tokens.total` for combined token usage. These metrics help you understand consumption patterns and costs.

Request metrics include `claude.requests.count` to track the number of API calls, `claude.requests.duration` to measure response times in milliseconds, and `claude.requests.errors` to monitor failed requests. These help identify performance issues and error patterns.

Each metric includes multiple dimensions for filtering and grouping. The `UserEmail` dimension comes from the OIDC token, allowing you to track individual user consumption. The `Model` dimension shows which Claude model was used (like claude-3-sonnet or claude-3-opus). The `Region` dimension indicates the AWS region where Bedrock was accessed.

Organizational dimensions provide additional context. The `department` field groups users by their organizational department. `team.id` identifies specific teams within departments. `cost_center` enables cost allocation for billing purposes. Additional dimensions like `organization`, `location`, and `role` provide further categorization options for your metrics.

## CloudWatch Dashboard

The CloudWatch Dashboard named `ClaudeCodeMonitoring` provides comprehensive visualization of your Claude Code metrics.

![Claude Code Monitoring Dashboard](/assets/images/ClaudeCodeDashboard.png)
_Full dashboard view showing all metrics_

## End User Experience

From the end user perspective, monitoring works automatically without requiring any configuration or setup.

During installation, the `install.sh` script copies all necessary files including the Claude Code settings and OTEL helper binary. Users don't need to configure anything - the monitoring settings are pre-configured with your organization's collector endpoint.

When users work with Claude Code, metrics are sent in the background without affecting performance or user experience. The OTEL helper binary automatically extracts user information from their authentication token and includes it with metrics for attribution.

Privacy remains a priority in the monitoring implementation. The system collects only usage metrics like token counts and response times - conversation content is never transmitted or stored. While metrics include user email for attribution in organizational reports, the system also generates hashed user IDs for scenarios where email-based identification isn't appropriate.

## Bedrock API Monitoring

The authentication stack can optionally track Bedrock API calls through AWS CloudTrail, providing an audit trail and additional cost monitoring capabilities.

CloudTrail tracking captures every Bedrock model invocation, storing detailed logs in S3 with 90-day retention. These events also stream to CloudWatch Logs at `/aws/bedrock/cognito-access` for real-time analysis. This creates a complete audit trail of who accessed which models and when.

The monitoring dashboard includes several cost-related features. A separate Bedrock cost dashboard tracks AWS Billing charges for the Bedrock service. The main dashboard estimates costs based on token usage with configurable pricing (default $15 per million tokens). Real-time cost widgets show today's cost, this week's cost, and this month's total spending.

### Data Privacy

The system collects only usage metrics, never capturing or transmitting conversation content between users and Claude. User attribution works through the email address from the OIDC token, providing clear accountability without excessive data collection. CloudWatch retains metrics for 15 months by default, though you can adjust this based on your retention policies. Beyond the email address used for attribution, no personally identifiable information is transmitted or stored.

### Network Security

The monitoring infrastructure supports both HTTP and HTTPS protocols. For production deployments, provide a custom domain name during setup to automatically enable HTTPS with an ACM certificate. HTTP mode remains available for development or internal deployments where encryption isn't required.

The Application Load Balancer is internet-facing to receive metrics from Claude Code installations, while ECS tasks run in private subnets for enhanced security. Security groups restrict access to only necessary ports and protocols, following the principle of least privilege.

## Summary

The monitoring system provides comprehensive visibility into Claude Code usage across your organization. Deployment is automated through the `ccwb` CLI tools, creating all necessary infrastructure with minimal configuration. The OTEL Collector on ECS Fargate handles metric collection and transformation, while CloudWatch provides storage and visualization.

User attribution happens automatically through the OTEL helper binary that extracts information from authentication tokens. This enables detailed usage tracking by user, department, team, and other organizational dimensions without requiring manual configuration.

Quota monitoring provides proactive alerts when users approach or exceed token usage limits. The system sends detailed notifications through SNS, allowing organizations to manage costs and usage patterns effectively.
