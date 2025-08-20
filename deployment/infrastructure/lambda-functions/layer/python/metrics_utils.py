# ABOUTME: Shared utilities for querying CloudWatch Metrics in dashboard widgets
# ABOUTME: Provides fallback to log queries for backwards compatibility

import boto3
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any

# Constants
METRICS_NAMESPACE = 'ClaudeCode'


def get_metric_statistics(
    cloudwatch_client,
    metric_name: str,
    start_time: int,
    end_time: int,
    dimensions: Optional[List[Dict]] = None,
    statistic: str = 'Sum',
    period: int = 300
) -> List[Dict]:
    """
    Get metric statistics from CloudWatch Metrics.
    
    Args:
        cloudwatch_client: Boto3 CloudWatch client
        metric_name: Name of the metric
        start_time: Start time in milliseconds
        end_time: End time in milliseconds
        dimensions: List of dimension filters
        statistic: Statistic to retrieve (Sum, Average, Maximum, etc.)
        period: Period in seconds for data points
    
    Returns:
        List of datapoints with Timestamp and value
    """
    try:
        params = {
            'Namespace': METRICS_NAMESPACE,
            'MetricName': metric_name,
            'StartTime': datetime.fromtimestamp(start_time / 1000),
            'EndTime': datetime.fromtimestamp(end_time / 1000),
            'Period': period,
            'Statistics': [statistic]
        }
        
        if dimensions:
            params['Dimensions'] = dimensions
        
        response = cloudwatch_client.get_metric_statistics(**params)
        
        # Sort by timestamp
        datapoints = response.get('Datapoints', [])
        datapoints.sort(key=lambda x: x['Timestamp'])
        
        return datapoints
        
    except Exception as e:
        print(f"Error getting metric {metric_name}: {str(e)}")
        return []


def get_metric_data(
    cloudwatch_client,
    queries: List[Dict],
    start_time: int,
    end_time: int
) -> Dict[str, List]:
    """
    Get multiple metrics using GetMetricData API for efficiency.
    
    Args:
        cloudwatch_client: Boto3 CloudWatch client
        queries: List of metric query definitions
        start_time: Start time in milliseconds
        end_time: End time in milliseconds
    
    Returns:
        Dictionary mapping query IDs to result arrays
    """
    try:
        metric_data_queries = []
        
        for query in queries:
            metric_stat = {
                'Metric': {
                    'Namespace': METRICS_NAMESPACE,
                    'MetricName': query['MetricName']
                },
                'Period': query.get('Period', 300),
                'Stat': query.get('Stat', 'Sum')
            }
            
            if 'Dimensions' in query:
                metric_stat['Metric']['Dimensions'] = query['Dimensions']
            
            metric_data_queries.append({
                'Id': query['Id'],
                'MetricStat': metric_stat,
                'ReturnData': True
            })
        
        response = cloudwatch_client.get_metric_data(
            MetricDataQueries=metric_data_queries,
            StartTime=datetime.fromtimestamp(start_time / 1000),
            EndTime=datetime.fromtimestamp(end_time / 1000)
        )
        
        # Convert to dictionary for easy access
        results = {}
        for result in response.get('MetricDataResults', []):
            results[result['Id']] = result.get('Values', [])
        
        return results
        
    except Exception as e:
        print(f"Error getting metric data: {str(e)}")
        return {}


def get_latest_metric_value(
    cloudwatch_client,
    metric_name: str,
    dimensions: Optional[List[Dict]] = None,
    statistic: str = 'Sum',
    lookback_minutes: int = 5
) -> Optional[float]:
    """
    Get the latest value for a metric.
    
    Args:
        cloudwatch_client: Boto3 CloudWatch client
        metric_name: Name of the metric
        dimensions: List of dimension filters
        statistic: Statistic to retrieve
        lookback_minutes: How many minutes to look back
    
    Returns:
        Latest metric value or None if not found
    """
    end_time = datetime.now()
    start_time = end_time - timedelta(minutes=lookback_minutes)
    
    datapoints = get_metric_statistics(
        cloudwatch_client,
        metric_name,
        int(start_time.timestamp() * 1000),
        int(end_time.timestamp() * 1000),
        dimensions,
        statistic,
        300
    )
    
    if datapoints:
        # Return the most recent value
        return datapoints[-1].get(statistic, 0)
    
    return None


def get_top_n_metrics(
    cloudwatch_client,
    metric_name: str,
    dimension_name: str,
    top_n: int = 10,
    start_time: int = None,
    end_time: int = None,
    statistic: str = 'Sum'
) -> List[Dict]:
    """
    Get top N values for a metric grouped by dimension.
    
    Args:
        cloudwatch_client: Boto3 CloudWatch client
        metric_name: Name of the metric
        dimension_name: Dimension to group by
        top_n: Number of top values to return
        start_time: Start time in milliseconds
        end_time: End time in milliseconds
        statistic: Statistic to retrieve
    
    Returns:
        List of dictionaries with dimension value and metric value
    """
    if not end_time:
        end_time = int(datetime.now().timestamp() * 1000)
    if not start_time:
        start_time = end_time - (5 * 60 * 1000)  # Last 5 minutes
    
    # For top users, we need to query the pre-computed TopUserTokens metric
    if metric_name == 'TopUserTokens':
        results = []
        for rank in range(1, top_n + 1):
            dimensions = [{'Name': 'Rank', 'Value': str(rank)}]
            
            # List metrics to get the user dimension value
            response = cloudwatch_client.list_metrics(
                Namespace=METRICS_NAMESPACE,
                MetricName=metric_name,
                Dimensions=dimensions
            )
            
            for metric in response.get('Metrics', []):
                user = None
                tokens = None
                
                # Extract user from dimensions
                for dim in metric['Dimensions']:
                    if dim['Name'] == 'User':
                        user = dim['Value']
                
                if user:
                    # Get the metric value
                    value = get_latest_metric_value(
                        cloudwatch_client,
                        metric_name,
                        metric['Dimensions'],
                        statistic
                    )
                    
                    if value:
                        results.append({
                            'dimension': user,
                            'value': value
                        })
        
        return results
    
    # For other metrics, list all dimension values and get their metrics
    try:
        response = cloudwatch_client.list_metrics(
            Namespace=METRICS_NAMESPACE,
            MetricName=metric_name
        )
        
        dimension_values = set()
        for metric in response.get('Metrics', []):
            for dim in metric['Dimensions']:
                if dim['Name'] == dimension_name:
                    dimension_values.add(dim['Value'])
        
        results = []
        for value in dimension_values:
            dimensions = [{'Name': dimension_name, 'Value': value}]
            metric_value = get_latest_metric_value(
                cloudwatch_client,
                metric_name,
                dimensions,
                statistic
            )
            
            if metric_value:
                results.append({
                    'dimension': value,
                    'value': metric_value
                })
        
        # Sort by value and return top N
        results.sort(key=lambda x: x['value'], reverse=True)
        return results[:top_n]
        
    except Exception as e:
        print(f"Error getting top {top_n} metrics: {str(e)}")
        return []


def check_metrics_available(cloudwatch_client) -> bool:
    """
    Check if CloudWatch Metrics are available for ClaudeCode namespace.
    
    Returns:
        True if metrics are available, False otherwise
    """
    try:
        response = cloudwatch_client.list_metrics(
            Namespace=METRICS_NAMESPACE,
            MetricName='TotalTokens',
            MaxRecords=1
        )
        
        return len(response.get('Metrics', [])) > 0
        
    except Exception as e:
        print(f"Error checking metrics availability: {str(e)}")
        return False


def fallback_to_logs_query(
    logs_client,
    log_group: str,
    query: str,
    start_time: int,
    end_time: int,
    timeout: int = 30
) -> List[Dict]:
    """
    Fallback to CloudWatch Logs query if metrics are not available.
    
    Args:
        logs_client: Boto3 CloudWatch Logs client
        log_group: Log group name
        query: CloudWatch Logs Insights query
        start_time: Start time in milliseconds
        end_time: End time in milliseconds
        timeout: Query timeout in seconds
    
    Returns:
        Query results
    """
    try:
        response = logs_client.start_query(
            logGroupName=log_group,
            startTime=start_time,
            endTime=end_time,
            queryString=query
        )
        
        query_id = response['queryId']
        
        # Wait for query to complete
        for _ in range(timeout):
            response = logs_client.get_query_results(queryId=query_id)
            status = response.get('status', 'Unknown')
            
            if status == 'Complete':
                return response.get('results', [])
            elif status in ['Failed', 'Cancelled']:
                print(f"Query failed with status: {status}")
                return []
            
            time.sleep(1)
        
        print("Query timed out")
        return []
        
    except Exception as e:
        print(f"Error running fallback query: {str(e)}")
        return []