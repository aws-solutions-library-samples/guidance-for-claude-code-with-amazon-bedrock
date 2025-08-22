# CloudWatch Dashboard Implementation Guide

## Overview

The Claude Code dashboard consists of 20 custom widgets implemented as Lambda functions, providing real-time and historical metrics visualization. This document details the implementation, data sources, and optimization strategies.

## Dashboard Layout

### Row 1: Key Metrics
- **Total Tokens Used** - Large display of total token consumption
- **Active Users** - Count of unique users in time range
- **Cache Efficiency** - Percentage of cache hits vs. misses
- **Model Quota Usage** - TPM/RPM usage against Service Quotas

### Row 2: Time Series
- **Active Users Over Time** - Line chart from DynamoDB
- **Lines Added/Removed Over Time** - Dual-line chart from DynamoDB

### Row 3: User Analytics
- **Top Users by Token Usage** - Bar chart from DynamoDB
- **Token Usage by Model** - Distribution across models
- **Token Usage by Type** - Input/Output/Cache breakdown

### Row 4: Development Metrics
- **Code Generation by Language** - Programming language distribution
- **Operations by Type** - Edit/Write/Read operations
- **Code Acceptance Rate** - Percentage of accepted code
- **Commits** - Git commit activity

### Row 5: System Metrics
- **Token Usage Over Time** - Native CloudWatch line chart
- **Bedrock API Errors** - Error tracking
- **Throttles by Model** - Rate limit monitoring

## Lambda Function Implementation

### Shared Lambda Layers

#### query_utils.py
```python
# Rate limiting for CloudWatch Logs queries
def rate_limited_start_query(logs_client, log_group, start_time, end_time, query):
    # Implements exponential backoff
    # Handles throttling gracefully
    # Returns query ID

# Optimized query result polling
def wait_for_query_results(logs_client, query_id):
    # Adaptive polling intervals
    # Timeout handling
    # Returns results or raises exception

# Time range validation
def validate_time_range(start_time, end_time):
    # Maximum 7-day range for performance
    # Returns validation status and error HTML
```

#### metrics_utils.py
```python
# CloudWatch Metrics helper
def get_metric_statistics(client, metric_name, start_time, end_time, dimensions, statistic, period):
    # Handles pagination
    # Automatic period adjustment based on time range
    # Returns aggregated datapoints

# Check if metrics are available
def check_metrics_available(client):
    # Verifies CloudWatch Metrics exist
    # Used for fallback logic
```

### Widget Lambda Functions

#### 1. Total Tokens (total_tokens/index.py)
- **Data Source**: CloudWatch Metrics or Logs fallback
- **Performance**: < 500ms response time
- **Display**: Large number with gradient background
- **Features**: Automatic number formatting (K, M, B)

#### 2. Active Users (active_users/index.py)
- **Data Source**: DynamoDB (WINDOW#SUMMARY records)
- **Query Pattern**: pk=METRICS#YYYY-MM-DD, sk begins_with time
- **Aggregation**: Unique user count across time range
- **Optimization**: Single query with filter expression

#### 3. Top Users (top_users/index.py)
- **Data Source**: DynamoDB (USER records)
- **Query Pattern**: Multiple day queries, aggregate in Lambda
- **Display**: Horizontal bar chart with percentages
- **Performance**: Parallel queries for multiple days

#### 4. Lines Over Time (lines_over_time/index.py)
- **Data Source**: DynamoDB (LINE_EVENT records)
- **Query Pattern**: GSI2 - TYPE#LINE_EVENT
- **Visualization**: Dual-line SVG chart
- **Features**: Time-based X-axis positioning

#### 5. Token by Model (token_by_model/index.py)
- **Data Source**: CloudWatch Metrics (TokensByModel)
- **Aggregation**: Sum across time range
- **Display**: Bar chart with model grouping
- **Optimization**: Single API call with all models

#### 6. Users Over Time (users_over_time/index.py)
- **Data Source**: DynamoDB (WINDOW#SUMMARY)
- **Time Series**: 5-minute intervals
- **Visualization**: SVG line chart
- **Features**: Adaptive Y-axis scaling

## DynamoDB Access Patterns

### Pattern 1: Time Range Queries
```python
# Query windows for a specific day
response = table.query(
    KeyConditionExpression=Key('pk').eq(f'METRICS#{date}') & 
                          Key('sk').between(f'{start_time}#WINDOW#SUMMARY',
                                           f'{end_time}#WINDOW#SUMMARY')
)
```

### Pattern 2: User Aggregation
```python
# Query user metrics across time range
response = table.query(
    KeyConditionExpression=Key('pk').eq(f'METRICS#{date}') & 
                          Key('sk').begins_with(f'{time}#USER#')
)
```

### Pattern 3: Line Events Time Series
```python
# Query via GSI2 for event type
response = table.query(
    IndexName='MetricTypeIndex',
    KeyConditionExpression=Key('gsi2pk').eq('TYPE#LINE_EVENT') &
                          Key('gsi2sk').between(start, end)
)
```

## Performance Optimizations

### 1. Caching Strategy
- Lambda container reuse for DynamoDB connections
- CloudWatch Metrics 15-minute cache
- Widget HTML cached in browser

### 2. Query Optimization
- Batch operations where possible
- Projection expressions to limit data transfer
- Parallel queries for multi-day ranges

### 3. Data Aggregation
- Pre-aggregated 5-minute windows
- Hierarchical aggregation (window → day → month)
- Client-side calculations minimized

### 4. Error Handling
```python
try:
    # Main logic
except ClientError as e:
    if e.response['Error']['Code'] == 'ThrottlingException':
        # Implement exponential backoff
    elif e.response['Error']['Code'] == 'ResourceNotFoundException':
        # Return empty dataset
except Exception as e:
    # Return error widget HTML
    return error_html(str(e))
```

## Widget HTML Generation

### Responsive Design
```python
# Adaptive sizing based on widget dimensions
widget_size = event.get('widgetContext', {}).get('size', {})
width = widget_size.get('width', 300)
height = widget_size.get('height', 200)

# Scale fonts and elements
font_size = min(width // 10, height // 5, 48)
```

### Consistent Styling
```python
# Common color palette
colors = {
    'primary': '#667eea',
    'secondary': '#764ba2',
    'success': '#10b981',
    'error': '#ef4444',
    'cache': '#8b5cf6'
}

# Gradient backgrounds
gradients = {
    'default': 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
    'error': 'linear-gradient(135deg, #ef4444 0%, #dc2626 100%)',
    'empty': 'linear-gradient(135deg, #6b7280 0%, #4b5563 100%)'
}
```

### SVG Chart Generation
```python
# Time series line chart
def generate_svg_line_chart(data_points, width, height):
    # Calculate scales
    x_scale = width / len(data_points)
    y_max = max(point['value'] for point in data_points)
    y_scale = height / y_max if y_max > 0 else 1
    
    # Generate path
    path_points = []
    for i, point in enumerate(data_points):
        x = i * x_scale
        y = height - (point['value'] * y_scale)
        path_points.append(f"{x},{y}")
    
    return f'<polyline points="{" ".join(path_points)}" />'
```

## Data Freshness

### Real-time Metrics (< 1 minute delay)
- Active Users
- Total Tokens
- Cache Efficiency

### Near Real-time (5-minute delay)
- Lines of Code
- Users Over Time
- Top Users

### Batch Processed (5-15 minute delay)
- Model Quota Usage
- Token Usage by Type
- Operations by Type

## Testing Strategy

### Unit Tests
```python
# Test number formatting
assert format_number(1234) == "1,234"
assert format_number(1234567) == "1.2M"
assert format_number(1234567890) == "1.2B"

# Test time range validation
assert validate_time_range(start, end)[0] == True  # Valid
assert validate_time_range(start, end_plus_8_days)[0] == False  # Too long
```

### Integration Tests
- DynamoDB query patterns
- CloudWatch Metrics retrieval
- Error handling scenarios

### Load Tests
- Concurrent widget loads
- Large time range queries
- Multiple user scenarios

## Troubleshooting

### Common Issues

#### 1. "No Data Available"
- Check EventBridge rule is enabled
- Verify metrics aggregator is running
- Confirm DynamoDB has data for time range

#### 2. Slow Widget Loading
- Check Lambda cold start times
- Verify DynamoDB read capacity
- Review CloudWatch Logs for errors

#### 3. Incorrect Totals
- Verify time range selection
- Check aggregation logic
- Confirm Decimal type handling

### Debug Mode
```python
# Enable debug logging
DEBUG = os.environ.get('DEBUG', 'false').lower() == 'true'

if DEBUG:
    print(f"Query: {query}")
    print(f"Results: {len(results)} items")
    print(f"Time range: {start_dt} to {end_dt}")
```

## Configuration

### Environment Variables
```yaml
METRICS_LOG_GROUP: /aws/claude-code/metrics
METRICS_REGION: us-east-1
METRICS_TABLE: ClaudeCodeMetrics
METRICS_ONLY: true  # Skip log queries, use metrics only
DEBUG: false  # Enable debug logging
```

### Lambda Configuration
- **Runtime**: Python 3.11
- **Memory**: 256 MB (sufficient for most queries)
- **Timeout**: 30 seconds (rarely exceeds 5 seconds)
- **Concurrent Executions**: 10 (prevents throttling)

## Cost Analysis

### Per Widget Costs (Monthly)
- Lambda Invocations: ~$0.20 per million requests
- DynamoDB Queries: ~$0.25 per million read units
- CloudWatch Metrics: Included in aggregator costs
- Total per widget: < $1/month at moderate usage

### Dashboard Total Cost
- 20 widgets × $1/month = $20/month base
- Scales linearly with refresh frequency
- Cost remains constant regardless of user count

## Future Enhancements

1. **Widget Caching**: CloudFront distribution for static widgets
2. **WebSocket Updates**: Real-time push updates
3. **Custom Filters**: Department/team selection
4. **Export Functionality**: CSV/PDF reports
5. **Mobile Optimization**: Responsive widget layouts

## Conclusion

The dashboard implementation provides a scalable, performant, and cost-effective solution for monitoring Claude Code usage. By leveraging DynamoDB for time-series data and CloudWatch Metrics for aggregates, we achieve sub-second load times while maintaining detailed analytics capabilities.