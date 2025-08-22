# Claude Code Monitoring Architecture

## Overview

This document describes the complete monitoring architecture for Claude Code, designed to scale efficiently to 10,000+ users while maintaining detailed analytics capabilities.

## Architecture Principles

1. **Separation of Concerns**: Real-time metrics vs. detailed analytics
2. **Cost Efficiency**: Minimize CloudWatch Metrics usage at scale
3. **Performance**: Sub-second dashboard loads
4. **Scalability**: Linear cost scaling with user growth
5. **Data Retention**: Short-term operational metrics, long-term analytics

## Three-Tier Architecture

### Tier 1: Data Collection

#### OpenTelemetry Collector
- **Deployment**: ECS Fargate with Application Load Balancer
- **Purpose**: Receive metrics from Claude Code instances
- **Configuration**: Optimized to reduce dimension explosion
  - Removed per-user CloudWatch Metrics dimensions
  - Reduced from 48 to 10 dimension combinations
  - Preserves full data in CloudWatch Logs

#### Data Outputs
1. **CloudWatch Logs** (`/aws/claude-code/metrics`)
   - Complete metric data with all attributes
   - Used by Kinesis Firehose for analytics
   - Source for metrics aggregation

2. **CloudWatch Metrics** (namespace: `ClaudeCode`)
   - Only aggregate dimensions (department, team, model)
   - No per-user metrics to prevent cost explosion

### Tier 2: Data Processing & Storage

#### Metrics Aggregator (Lambda)
- **Schedule**: Every 5 minutes via EventBridge
- **Functions**:
  - Query CloudWatch Logs for raw metrics
  - Aggregate by various dimensions
  - Store in DynamoDB for time-series queries
  - Publish to CloudWatch Metrics for native widgets

#### DynamoDB Storage
- **Table**: `ClaudeCodeMetrics`
- **Design**: Single-table with composite keys
- **Billing**: Pay-per-request (on-demand)
- **TTL**: 30-day retention

**Schema Design**:
```
Primary Key:
  pk: METRICS#YYYY-MM-DD
  sk: HH:MM:SS#TYPE#DETAIL

Global Secondary Indexes:
  GSI1 (UserActivityIndex):
    gsi1pk: USER#email or TYPE#WINDOW
    gsi1sk: timestamp-based sorting
  
  GSI2 (MetricTypeIndex):
    gsi2pk: TYPE#metricname
    gsi2sk: timestamp-based sorting
  
  GSI3 (MonthlyIndex):
    gsi3pk: MONTH#YYYY-MM
    gsi3sk: DD#HH:MM:SS#TYPE
```

#### Analytics Pipeline
- **Kinesis Firehose**: Streams CloudWatch Logs to S3
- **S3 Data Lake**: Parquet format, partitioned by date/time
- **AWS Glue**: Catalog and schema management
- **Athena**: SQL queries for detailed analytics

### Tier 3: Visualization & Analytics

#### CloudWatch Dashboard
- **20 Custom Widgets** using Lambda functions
- **Data Sources**:
  - 6 widgets query DynamoDB
  - 2 widgets query CloudWatch Metrics
  - 12 widgets use native CloudWatch features

#### Dashboard Widgets Categories

**Real-time Metrics**:
- Total Tokens Used
- Active Users
- Cache Efficiency
- Model Quota Usage

**Time Series Visualizations**:
- Lines Added/Removed Over Time
- Active Users Over Time
- Token Usage Over Time

**User Analytics**:
- Top Users by Token Usage
- Users Over Time

**Development Metrics**:
- Code Acceptance Rate
- Commits
- Operations by Type
- Code Generation by Language

## Data Flow

```
Claude Code Instance
        ↓
   OTEL Collector
        ↓
CloudWatch Logs (/aws/claude-code/metrics)
        ↓
    ┌───┴───┐
    ↓       ↓
Aggregator  Firehose
    ↓       ↓
DynamoDB    S3
    ↓       ↓
Dashboard  Athena
```

## Cost Optimization

### Before Optimization
- Per-user CloudWatch Metrics: 48 dimension combinations
- At 10,000 users: 480,000+ unique metrics
- Estimated cost: $144,000/month

### After Optimization
- Aggregate metrics only: ~100-200 metrics total
- User data in DynamoDB: Pay-per-request
- Estimated cost at 10,000 users: ~$100/month
- Cost reduction: 99.93%

## Performance Characteristics

### Dashboard Load Times
- DynamoDB queries: < 100ms
- CloudWatch Metrics: < 500ms
- Total widget render: < 1 second

### Data Freshness
- Metrics aggregation: 5-minute intervals
- Dashboard refresh: Real-time on load
- Athena queries: Near real-time (5-minute lag)

## Scalability Considerations

### Linear Scaling Components
- DynamoDB (pay-per-request)
- S3 storage
- Lambda executions

### Fixed Cost Components
- ECS Fargate (OTEL Collector)
- EventBridge rules
- CloudWatch dashboard

### Scaling Limits
- DynamoDB: 40,000 RCU/WCU per table
- Lambda: 1,000 concurrent executions
- CloudWatch Logs: 10,000 events/second per log stream

## Security Model

### Network Security
- OTEL Collector behind ALB with security groups
- Lambda functions in VPC with private subnets
- S3 buckets with encryption and versioning

### Access Control
- IAM roles with least privilege
- Cross-service permissions via service roles
- No hard-coded credentials

### Data Protection
- Encryption at rest (S3, DynamoDB)
- Encryption in transit (HTTPS/TLS)
- 30-day retention with automatic cleanup

## Deployment Architecture

### CloudFormation Stacks
1. `claude-code-auth-networking` - VPC and network resources
2. `claude-code-auth-monitoring` - OTEL Collector on ECS
3. `claude-code-auth-dashboard` - Dashboard and Lambda functions
4. `claude-code-auth-analytics` - Kinesis, S3, Athena pipeline
5. `claude-code-auth-stack` - Main application stack

### Dependencies
```
networking → monitoring → analytics → dashboard
                ↓
            auth-stack
```

## Monitoring the Monitoring

### Health Checks
- OTEL Collector: ALB health checks
- Lambda functions: CloudWatch error metrics
- DynamoDB: CloudWatch metrics for throttles
- Firehose: Delivery success metrics

### Alerting
- Lambda errors > 1% - Alert
- DynamoDB throttles > 0 - Alert
- Firehose delivery failures - Alert
- OTEL Collector unhealthy - Page

## Future Enhancements

1. **Predictive Analytics**: ML models for usage forecasting
2. **Cost Attribution**: Detailed chargeback by department/team
3. **Anomaly Detection**: CloudWatch Anomaly Detector integration
4. **Custom Dashboards**: Per-team/department views
5. **API Access**: GraphQL API for metrics data

## Conclusion

This architecture provides a robust, scalable, and cost-effective monitoring solution for Claude Code. By separating real-time operational metrics from detailed analytics, we achieve both performance and cost efficiency while maintaining full visibility into system usage and user behavior.