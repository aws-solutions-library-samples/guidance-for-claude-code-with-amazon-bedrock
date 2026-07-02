"""
E2E Test Harness — Shared Helpers

Utility functions extracted from conftest.py for reuse across test modules.
These are pure functions (no pytest fixtures) — conftest wraps them in fixtures.
"""

import base64
import datetime
import json
import os
import platform
import signal
import socket
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import boto3


# ---------------------------------------------------------------------------
# Token / credential helpers
# ---------------------------------------------------------------------------


def patch_token_expiry(
    cache_dir: Path,
    profile_name: str,
    expired: bool = True,
) -> Path:
    """Modify cached JWT's exp claim to simulate token expiry or validity.

    Args:
        cache_dir: Directory containing cached token files.
        profile_name: Profile name to locate the cached token.
        expired: If True, set exp to past. If False, set exp to +1 hour.

    Returns:
        Path to the patched token file.
    """
    token_path = cache_dir / f"{profile_name}.json"

    if not token_path.exists():
        raise FileNotFoundError(f"Token cache not found: {token_path}")

    with open(token_path) as f:
        token_data = json.load(f)

    # Decode the JWT payload (without verification)
    access_token = token_data.get("AccessToken", token_data.get("access_token", ""))
    parts = access_token.split(".")
    if len(parts) != 3:
        raise ValueError(
            f"Token is not a valid JWT (expected 3 parts, got {len(parts)})"
        )

    # Decode payload
    payload_b64 = parts[1] + "=" * (4 - len(parts[1]) % 4)
    payload = json.loads(base64.urlsafe_b64decode(payload_b64))

    # Patch exp claim
    if expired:
        payload["exp"] = int(time.time()) - 3600  # 1 hour ago
    else:
        payload["exp"] = int(time.time()) + 3600  # 1 hour from now

    # Re-encode payload (signature will be invalid, but that's fine for testing)
    patched_payload = (
        base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()
    )
    parts[1] = patched_payload

    # Write back
    token_key = "AccessToken" if "AccessToken" in token_data else "access_token"
    token_data[token_key] = ".".join(parts)

    with open(token_path, "w") as f:
        json.dump(token_data, f)

    return token_path


# ---------------------------------------------------------------------------
# Process / port helpers
# ---------------------------------------------------------------------------


def kill_process_on_port(port: int) -> bool:
    """Find and kill process listening on a port (cross-platform).

    Args:
        port: TCP port number.

    Returns:
        True if a process was killed, False if none found.
    """
    system = platform.system()

    try:
        if system == "Windows":
            # Use netstat to find PID, then taskkill
            result = subprocess.run(
                ["netstat", "-ano"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            for line in result.stdout.splitlines():
                if f":{port}" in line and "LISTENING" in line:
                    parts = line.strip().split()
                    pid = parts[-1]
                    subprocess.run(
                        ["taskkill", "/F", "/PID", pid],
                        capture_output=True,
                        timeout=10,
                    )
                    return True
        else:
            # Unix: use lsof or fuser
            result = subprocess.run(
                ["lsof", "-ti", f":{port}"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0 and result.stdout.strip():
                for pid_str in result.stdout.strip().splitlines():
                    pid = int(pid_str.strip())
                    os.kill(pid, signal.SIGKILL)
                return True
    except (subprocess.TimeoutExpired, OSError, ValueError):
        pass

    return False


def wait_for_port(
    host: str = "127.0.0.1",
    port: int = 4318,
    timeout: float = 10.0,
) -> bool:
    """TCP connect poll with retry until port is accepting connections.

    Args:
        host: Hostname to connect to.
        port: Port number.
        timeout: Max seconds to wait.

    Returns:
        True if port became available, False on timeout.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1.0)
            sock.connect((host, port))
            sock.close()
            return True
        except (ConnectionRefusedError, OSError, socket.timeout):
            time.sleep(0.5)
        finally:
            try:
                sock.close()
            except Exception:
                pass
    return False


# ---------------------------------------------------------------------------
# Cognito helpers
# ---------------------------------------------------------------------------


def create_cognito_test_user(
    pool_id: str,
    email: str,
    password: str,
    region: str = "us-east-1",
) -> Dict[str, Any]:
    """Create a test user in Cognito User Pool via Admin API.

    Args:
        pool_id: Cognito User Pool ID.
        email: User email address.
        password: User password.
        region: AWS region.

    Returns:
        Dict with user creation response.
    """
    client = boto3.client("cognito-idp", region_name=region)

    # Create user
    response = client.admin_create_user(
        UserPoolId=pool_id,
        Username=email,
        UserAttributes=[
            {"Name": "email", "Value": email},
            {"Name": "email_verified", "Value": "true"},
        ],
        TemporaryPassword=password,
        MessageAction="SUPPRESS",
    )

    # Set permanent password
    client.admin_set_user_password(
        UserPoolId=pool_id,
        Username=email,
        Password=password,
        Permanent=True,
    )

    return response


def cognito_auth_headless(
    pool_id: str,
    client_id: str,
    email: str,
    password: str,
    region: str = "us-east-1",
) -> Dict[str, str]:
    """Authenticate via AdminInitiateAuth (headless, no browser).

    Args:
        pool_id: Cognito User Pool ID.
        client_id: App client ID.
        email: User email.
        password: User password.
        region: AWS region.

    Returns:
        Dict with AccessToken, IdToken, RefreshToken.
    """
    client = boto3.client("cognito-idp", region_name=region)

    response = client.admin_initiate_auth(
        UserPoolId=pool_id,
        ClientId=client_id,
        AuthFlow="ADMIN_USER_PASSWORD_AUTH",
        AuthParameters={
            "USERNAME": email,
            "PASSWORD": password,
        },
    )

    auth_result = response.get("AuthenticationResult", {})
    return {
        "AccessToken": auth_result.get("AccessToken", ""),
        "IdToken": auth_result.get("IdToken", ""),
        "RefreshToken": auth_result.get("RefreshToken", ""),
    }


# ---------------------------------------------------------------------------
# DynamoDB / Quota helpers
# ---------------------------------------------------------------------------


def seed_quota_usage(
    table: str,
    user: str,
    tokens: int,
    region: str = "us-east-1",
) -> None:
    """Write token usage to DynamoDB quota table.

    Args:
        table: DynamoDB table name.
        user: User identifier (partition key component).
        tokens: Number of tokens used.
        region: AWS region.
    """
    client = boto3.client("dynamodb", region_name=region)
    client.put_item(
        TableName=table,
        Item={
            "pk": {"S": f"USER#{user}"},
            "sk": {"S": "USAGE#current"},
            "tokens_used": {"N": str(tokens)},
            "updated_at": {"S": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())},
        },
    )


def set_user_quota_policy(
    table: str,
    user: str,
    limit: int,
    region: str = "us-east-1",
) -> None:
    """Write per-user quota policy to DynamoDB.

    Args:
        table: DynamoDB table name.
        user: User identifier.
        limit: Token limit.
        region: AWS region.
    """
    client = boto3.client("dynamodb", region_name=region)
    client.put_item(
        TableName=table,
        Item={
            "pk": {"S": f"USER#{user}"},
            "sk": {"S": "POLICY#quota"},
            "token_limit": {"N": str(limit)},
            "enforcement": {"S": "block"},
            "updated_at": {"S": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())},
        },
    )


def cleanup_quota_data(
    table: str,
    user: str,
    region: str = "us-east-1",
) -> None:
    """Delete test quota items from DynamoDB after test.

    Args:
        table: DynamoDB table name.
        user: User identifier.
        region: AWS region.
    """
    client = boto3.client("dynamodb", region_name=region)

    # Delete usage and policy items
    for sk in ["USAGE#current", "POLICY#quota"]:
        try:
            client.delete_item(
                TableName=table,
                Key={
                    "pk": {"S": f"USER#{user}"},
                    "sk": {"S": sk},
                },
            )
        except client.exceptions.ResourceNotFoundException:
            pass
        except Exception:
            # Best-effort cleanup — don't fail the test
            pass


# ---------------------------------------------------------------------------
# CloudWatch helpers
# ---------------------------------------------------------------------------


def wait_for_cloudwatch_metric(
    namespace: str,
    metric: str,
    dimensions: List[Dict[str, str]],
    region: str = "us-east-1",
    timeout: float = 90.0,
) -> Optional[float]:
    """Poll CloudWatch for a metric with exponential backoff.

    Args:
        namespace: CloudWatch namespace.
        metric: Metric name.
        dimensions: List of dimension dicts with Name/Value keys.
        region: AWS region.
        timeout: Max seconds to poll.

    Returns:
        Metric sum value, or None on timeout.
    """
    client = boto3.client("cloudwatch", region_name=region)

    wait_time = 5.0
    deadline = time.time() + timeout

    while time.time() < deadline:
        end_time = datetime.datetime.utcnow()
        start_time = end_time - datetime.timedelta(minutes=5)

        response = client.get_metric_statistics(
            Namespace=namespace,
            MetricName=metric,
            Dimensions=dimensions,
            StartTime=start_time,
            EndTime=end_time,
            Period=60,
            Statistics=["Sum"],
        )

        datapoints = response.get("Datapoints", [])
        if datapoints:
            # Return most recent datapoint
            sorted_points = sorted(datapoints, key=lambda d: d["Timestamp"])
            return sorted_points[-1]["Sum"]

        time.sleep(wait_time)
        wait_time = min(wait_time * 2, 30.0)

    return None
