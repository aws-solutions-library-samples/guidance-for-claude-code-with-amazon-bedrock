# Claude Code Quota Monitoring

Quota monitoring tracks user token consumption and sends automated alerts when usage thresholds are exceeded, helping administrators manage costs and prevent unexpected overages.

## Overview

The quota monitoring system is an optional CloudFormation stack that integrates with the dashboard stack to track monthly token consumption per user and send SNS alerts at configurable thresholds.

### Key Features

- **Per-user token tracking**: Monthly consumption monitoring for each authenticated user
- **Configurable thresholds**: Alerts at 80%, 90%, and 100% of monthly limits
- **Automated alerting**: SNS notifications with usage projections and cost estimates
- **Alert deduplication**: One alert per threshold per user per month
- **DynamoDB storage**: Efficient tracking with automatic TTL cleanup

### Architecture Components

- **UserQuotaMetrics Table**: DynamoDB table storing monthly usage totals
- **Quota Monitor Lambda**: Scheduled function checking thresholds every 15 minutes
- **SNS Topic**: Alert delivery to administrators
- **EventBridge Rule**: Lambda scheduling
- **Metrics Aggregator Integration**: Updates quota table during metric processing

## Configuration

> **Prerequisites**: Monitoring must be enabled and the dashboard stack deployed. See the [CLI Reference](CLI_REFERENCE.md#deploy---deploy-infrastructure) for deployment details.

During `ccwb init`, configure quota monitoring when prompted:
- Monthly token limit per user (default: 300 million)
- Automatic threshold calculation (80% warning, 90% critical)

Deploy using `poetry run ccwb deploy quota`. For complete deployment instructions, see the [CLI Reference](CLI_REFERENCE.md#deploy---deploy-infrastructure).

## Configuration Settings

| Parameter          | Default     | Description                            |
| ------------------ | ----------- | -------------------------------------- |
| MonthlyTokenLimit  | 300M tokens | Maximum per user per month             |
| Warning Threshold  | 80% (240M)  | First alert level                      |
| Critical Threshold | 90% (270M)  | Second alert level                     |
| Check Frequency    | 15 minutes  | Lambda execution interval              |
| Alert Retention    | 60 days     | DynamoDB TTL for deduplication        |

To update limits: Re-run `ccwb init` and redeploy with `ccwb deploy quota`.

## Alert Management

After deployment, subscribe to the SNS topic for notifications:

```bash
# Get topic ARN from stack outputs
aws cloudformation describe-stacks --stack-name <quota-stack-name> \
  --query 'Stacks[0].Outputs[?OutputKey==`QuotaAlertTopicArn`].OutputValue' \
  --output text

# Subscribe (email, SMS, HTTPS webhook, etc.)
aws sns subscribe --topic-arn <arn> --protocol email --notification-endpoint admin@company.com
```

### Alert Types

The system sends three types of alerts based on usage levels:

#### Warning Alert (80% threshold)

Sent when a user exceeds 80% of their monthly quota. Contains:

- Current usage and percentage
- Projected monthly total based on daily average
- Days remaining in the month
- Estimated costs

#### Critical Alert (90% threshold)

Sent when a user exceeds 90% of their monthly quota. Includes all warning information plus:

- Projected overage amount
- Urgency indicators in subject line

#### Exceeded Alert (100% threshold)

Sent when a user exceeds their monthly quota. Contains:

- Actual overage amount
- Updated cost estimates
- Recommended actions

### Sample Alert Content

```
Subject: Claude Code CRITICAL - 92.3% of Monthly Quota

Claude Code Usage Alert

User: john.doe@company.com
Alert Level: CRITICAL
Month: September 2024

Current Usage: 276,900,000 tokens
Monthly Limit: 300,000,000 tokens
Percentage Used: 92.3%

Days Remaining in Month: 8
Daily Average: 12,586,364 tokens
Projected Monthly Total: 377,454,552 tokens
Projected Overage: 77,454,552 tokens

Estimated Cost: $4,153.50
Estimated Monthly Cost: $5,661.82

Action Required: Monitor usage closely
```

Alerts are deduplicated - each threshold triggers only once per user per month, with history stored in DynamoDB (60-day TTL).

## Troubleshooting

### Quick Checks

```bash
# View Lambda logs
aws logs tail /aws/lambda/claude-code-quota-monitor --follow

# Query user quotas
aws dynamodb scan --table-name UserQuotaMetrics \
  --projection-expression "email, total_tokens"
```

### Common Issues

- **No alerts**: Verify SNS subscriptions are confirmed and EventBridge rule is enabled
- **Missing users**: Check JWT tokens include email claim
- **Wrong calculations**: Ensure QUOTA_TABLE environment variable is set on metrics aggregator

For detailed monitoring setup, see the [Monitoring Guide](MONITORING.md).

## Cost Considerations

**Estimated monthly costs for <1000 users: $1-5**
- Lambda: ~2,880 invocations × $0.0000002 = $0.58
- DynamoDB: Pay-per-request for user count × 2,880 operations
- SNS: $0.50 per million notifications
- CloudWatch Logs: Standard retention pricing

## Data Schema

### DynamoDB Structure

**User Totals**: `PK: USER#{email}`, `SK: MONTH#{YYYY-MM}`
- Attributes: `total_tokens`, `last_updated`, `email`
- TTL: End of following month

**Alert History**: `PK: ALERTS`, `SK: {YYYY-MM}#ALERT#{email}#{level}`
- Attributes: `sent_at`, `alert_level`, `usage_at_alert`
- TTL: 60 days

## Current Limitations

- Quotas reset on calendar month (1st of each month)
- Single limit applies to all users
- Alert-only (no access blocking)
- Requires email claim in JWT tokens

## Integration Points

- **Dashboard**: Shares DynamoDB metrics table and OTEL pipeline
- **Analytics**: Quota data available in Athena queries (see [Analytics Guide](ANALYTICS.md))
- **External Systems**: SNS topic supports webhooks, Lambda triggers, and third-party integrations

For complete monitoring setup and general telemetry information, see the [Monitoring Guide](MONITORING.md).
