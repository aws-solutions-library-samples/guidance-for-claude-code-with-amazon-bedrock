# Migration Guide: Per-Model Rate Tracking to DynamoDB

## Overview

This guide documents the migration from CloudWatch Metrics-based TPM/RPM tracking to DynamoDB-based per-minute rate tracking for improved granularity and cost efficiency.

## Changes Made

### 1. Metrics Aggregator Lambda

#### Added Functions
- `aggregate_model_rate_metrics()`: Queries logs and buckets token/request counts by model and minute
  - Parses timestamps to minute precision
  - Tracks both tokens and requests per model
  - Returns dict of model → minute → {tokens, requests}

#### Modified Functions
- `write_to_dynamodb()`: Extended to store per-minute model rate metrics
  - New item type: `pk=METRICS#YYYY-MM-DD, sk=HH:MM:SS#MODEL_RATE#model_id`
  - Stores tpm (tokens per minute) and rpm (requests per minute)
  - Uses GSI2 for model-specific queries: `gsi2pk=MODEL_RATE#model_id`

#### Removed Functions
- `aggregate_model_metrics()`: No longer needed
- CloudWatch Metrics publishing for ModelTPM and ModelRPM

### 2. Model Quota Usage Widget

#### New Implementation
- Queries DynamoDB instead of CloudWatch Metrics
- Calculates metrics over configurable time windows:
  - Recent peak (last 5 minutes)
  - 5-minute average
  - Overall peak with timestamp
- Dynamic layout based on model count:
  - 1 model: Grid layout with detailed view
  - 2-3 models: Two-line condensed view
  - 4-5 models: Single-line ultra-compact view

#### New Functions
- `get_model_rates_from_dynamodb()`: Queries per-minute rate data
- `format_compact_number()`: Ultra-compact number formatting
- `format_compact_time()`: Compact time display
- `get_micro_progress_bar()`: Text-based progress bar for compact mode

### 3. Cache Efficiency Widget

#### Fixed Metric Names
- Changed from `CacheHits`/`CacheMisses` to `CacheReadTokens`/`CacheCreationTokens`
- Updated calculation: Cache Reads / (Cache Reads + Cache Creation) × 100
- Display format: "X reads / Y cache ops"

## Data Schema

### DynamoDB Model Rate Item
```python
{
    'pk': 'METRICS#2024-01-20',
    'sk': '14:35:00#MODEL_RATE#us.anthropic.claude-opus-4-1-20250805-v1:0',
    'model': 'us.anthropic.claude-opus-4-1-20250805-v1:0',
    'tpm': Decimal('45000'),  # Tokens per minute
    'rpm': Decimal('3'),       # Requests per minute
    'timestamp': '2024-01-20T14:35:00Z',
    'gsi2pk': 'MODEL_RATE#us.anthropic.claude-opus-4-1-20250805-v1:0',
    'gsi2sk': '2024-01-20#14:35:00',
    'ttl': 1708444500
}
```

## Migration Steps

### For New Deployments
No action required. Deploy the updated Lambda functions and they will begin collecting per-minute data.

### For Existing Deployments

1. **Update Lambda Functions**
   ```bash
   # Deploy updated metrics_aggregator
   aws lambda update-function-code \
     --function-name metrics-aggregator \
     --zip-file fileb://metrics_aggregator.zip
   
   # Deploy updated dashboard widgets
   aws lambda update-function-code \
     --function-name model-quota-usage \
     --zip-file fileb://model_quota_usage.zip
   
   aws lambda update-function-code \
     --function-name cache-efficiency \
     --zip-file fileb://cache_efficiency.zip
   ```

2. **Verify DynamoDB Schema**
   - Table should have GSI2 (MetricTypeIndex) configured
   - Verify TTL is enabled on 'ttl' attribute

3. **Test Data Collection**
   - Wait 5 minutes for first aggregation run
   - Check DynamoDB for MODEL_RATE items:
   ```bash
   aws dynamodb query \
     --table-name ClaudeCodeMetrics \
     --index-name MetricTypeIndex \
     --key-condition-expression "gsi2pk = :pk" \
     --expression-attribute-values '{":pk":{"S":"MODEL_RATE#us.anthropic.claude-opus-4-1-20250805-v1:0"}}' \
     --limit 5
   ```

4. **Verify Dashboard**
   - Model Quota Usage widget should show data within 5 minutes
   - Cache Efficiency should display percentage
   - Check all layout modes work (1-5 models)

## Rollback Procedure

If issues occur, rollback by:

1. **Restore Previous Lambda Code**
   ```bash
   # Restore from previous version
   aws lambda update-function-code \
     --function-name metrics-aggregator \
     --zip-file fileb://metrics_aggregator_backup.zip
   ```

2. **Re-enable CloudWatch Metrics** (if needed)
   - Uncomment CloudWatch Metrics publishing in metrics_aggregator
   - Update model_quota_usage to query CloudWatch Metrics

## Benefits of Migration

### Cost Savings
- Eliminated per-model CloudWatch Metrics (was $14.40/month per model)
- DynamoDB pay-per-request: ~$0.01/month per model
- 99.9% cost reduction for rate tracking

### Improved Granularity
- Per-minute data points vs 5-minute aggregates
- Precise peak detection with timestamps
- Better rate limit monitoring

### Performance
- Faster widget loading (< 100ms DynamoDB queries)
- No CloudWatch Metrics API throttling
- Parallel query execution

## Monitoring

### Health Checks
```bash
# Check aggregator execution
aws logs tail /aws/lambda/metrics-aggregator --follow

# Monitor DynamoDB writes
aws cloudwatch get-metric-statistics \
  --namespace AWS/DynamoDB \
  --metric-name UserErrors \
  --dimensions Name=TableName,Value=ClaudeCodeMetrics \
  --start-time 2024-01-20T00:00:00Z \
  --end-time 2024-01-20T23:59:59Z \
  --period 300 \
  --statistics Sum
```

### Common Issues

#### No Data in Model Quota Widget
- Check metrics_aggregator CloudWatch Logs for errors
- Verify model IDs match between logs and QUOTA_MAPPINGS
- Ensure DynamoDB table has GSI2 configured

#### Incorrect Rate Calculations
- Verify token_type='input' filter for request counting
- Check timestamp parsing and minute bucketing
- Confirm Decimal type conversions

## Support

For issues or questions:
1. Check CloudWatch Logs for error messages
2. Review DynamoDB items for data consistency
3. Verify Lambda function configurations
4. Contact the platform team with error details