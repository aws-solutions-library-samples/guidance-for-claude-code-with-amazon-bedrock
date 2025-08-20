# ABOUTME: Shared utilities for CloudWatch Logs query management
# ABOUTME: Implements rate limiting and caching to prevent API throttling

import time
import random
import json
import hashlib
from datetime import datetime, timedelta

# Global cache for query results
_query_cache = {}
_last_query_time = 0
_query_counter = 0

def validate_time_range(start_time, end_time, max_days=7):
    """
    Validate the time range is within acceptable limits.
    
    Args:
        start_time: Start time in milliseconds
        end_time: End time in milliseconds
        max_days: Maximum allowed range in days (default 7)
    
    Returns:
        Tuple (is_valid, range_days, error_html)
    """
    range_ms = end_time - start_time
    range_days = range_ms / (1000 * 60 * 60 * 24)
    
    if range_days > max_days:
        error_html = f"""
        <div style="
            display: flex;
            align-items: center;
            justify-content: center;
            height: 100%;
            background: linear-gradient(135deg, #fef3c7 0%, #fed7aa 100%);
            border-radius: 8px;
            padding: 20px;
            box-sizing: border-box;
            font-family: 'Amazon Ember', -apple-system, sans-serif;
        ">
            <div style="text-align: center;">
                <div style="
                    color: #92400e;
                    font-size: 18px;
                    font-weight: 600;
                    margin-bottom: 12px;
                ">⚠️ Time Range Too Large</div>
                <div style="
                    color: #78350f;
                    font-size: 14px;
                    margin-bottom: 8px;
                ">Please select a time range of {max_days} days or less</div>
                <div style="
                    color: #92400e;
                    font-size: 13px;
                    font-weight: 500;
                ">Current selection: {range_days:.1f} days</div>
                <div style="
                    color: #a16207;
                    font-size: 11px;
                    margin-top: 12px;
                    line-height: 1.4;
                ">Large time ranges can cause performance issues and timeouts.<br/>
                Try narrowing your selection for faster results.</div>
            </div>
        </div>
        """
        return False, range_days, error_html
    
    return True, range_days, None


def get_cache_key(log_group, query_string, start_time, end_time):
    """Generate a cache key for a query."""
    # Round times to nearest minute for better cache hits
    start_rounded = (start_time // 60000) * 60000
    end_rounded = (end_time // 60000) * 60000
    
    key_string = f"{log_group}:{query_string}:{start_rounded}:{end_rounded}"
    return hashlib.md5(key_string.encode()).hexdigest()


def get_cached_result(cache_key, max_age_seconds=60):
    """Get a cached query result if it's still fresh."""
    if cache_key in _query_cache:
        cached_time, result = _query_cache[cache_key]
        if time.time() - cached_time < max_age_seconds:
            return result
    return None


def cache_result(cache_key, result):
    """Cache a query result."""
    _query_cache[cache_key] = (time.time(), result)
    
    # Clean old cache entries (keep last 100)
    if len(_query_cache) > 100:
        sorted_items = sorted(_query_cache.items(), key=lambda x: x[1][0])
        for key, _ in sorted_items[:20]:  # Remove oldest 20
            del _query_cache[key]


def rate_limited_start_query(logs_client, log_group, start_time, end_time, query_string, cache_age=60):
    """
    Start a CloudWatch Logs query with rate limiting and caching.
    
    Implements:
    - Result caching (60 second default)
    - Rate limiting (max 5 queries per second across all widgets)
    - Exponential backoff with jitter for retries
    """
    global _last_query_time, _query_counter
    
    # Check cache first
    cache_key = get_cache_key(log_group, query_string, start_time, end_time)
    cached = get_cached_result(cache_key, cache_age)
    if cached:
        return cached
    
    # Rate limiting - max 5 queries per second
    current_time = time.time()
    time_since_last = current_time - _last_query_time
    
    if time_since_last < 0.2:  # 5 queries per second = 0.2 seconds between queries
        sleep_time = 0.2 - time_since_last + random.uniform(0, 0.1)  # Add jitter
        time.sleep(sleep_time)
    
    # Stagger queries based on counter
    _query_counter += 1
    if _query_counter % 3 == 0:  # Every 3rd query, add extra delay
        time.sleep(random.uniform(0.1, 0.3))
    
    # Try query with exponential backoff
    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = logs_client.start_query(
                logGroupName=log_group,
                startTime=start_time,
                endTime=end_time,
                queryString=query_string
            )
            
            _last_query_time = time.time()
            
            # Cache the query ID for future reference
            cache_result(cache_key, response)
            
            return response
            
        except Exception as e:
            if "ThrottlingException" in str(e) and attempt < max_retries - 1:
                # Exponential backoff with jitter
                sleep_time = (2 ** attempt) + random.uniform(0, 1)
                time.sleep(sleep_time)
            else:
                raise


def wait_for_query_results(logs_client, query_id, max_wait=55):
    """
    Wait for query results with optimized polling.
    
    Uses adaptive polling intervals based on query status.
    """
    start_time = time.time()
    
    # Initial delay to let query start
    time.sleep(0.5)
    
    # Adaptive polling intervals
    poll_intervals = [0.5, 0.5, 1.0, 1.5, 2.0, 3.0]  # Gradually increase
    interval_index = 0
    
    while time.time() - start_time < max_wait:
        try:
            response = logs_client.get_query_results(queryId=query_id)
            status = response.get('status', 'Unknown')
            
            if status in ['Complete', 'Failed', 'Cancelled']:
                return response
            
            # Use adaptive interval
            interval = poll_intervals[min(interval_index, len(poll_intervals) - 1)]
            time.sleep(interval)
            
            # Increase interval index for next iteration
            if interval_index < len(poll_intervals) - 1:
                interval_index += 1
                
        except Exception as e:
            if "ThrottlingException" in str(e):
                # If throttled, wait longer
                time.sleep(3.0)
            else:
                raise
    
    # Return timeout response
    return {"status": "Timeout", "results": []}


def batch_queries(logs_client, queries_config, max_concurrent=3):
    """
    Execute multiple queries in controlled batches.
    
    Args:
        queries_config: List of (log_group, start_time, end_time, query_string) tuples
        max_concurrent: Maximum number of concurrent queries
    
    Returns:
        List of query IDs in same order as input
    """
    query_ids = []
    
    for i, (log_group, start_time, end_time, query_string) in enumerate(queries_config):
        # Add delay between batches
        if i > 0 and i % max_concurrent == 0:
            time.sleep(1.0)  # Pause between batches
        
        response = rate_limited_start_query(
            logs_client, log_group, start_time, end_time, query_string
        )
        query_ids.append(response.get("queryId"))
    
    return query_ids