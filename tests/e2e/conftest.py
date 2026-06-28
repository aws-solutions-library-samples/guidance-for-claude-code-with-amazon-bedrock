"""
E2E Test Harness — Shared Fixtures and Configuration

Profile-driven testing across auth flows, OS, monitoring modes,
config delivery, and quota enforcement.
"""

import datetime
import json
import os
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

import boto3
import pytest
from tenacity import retry, stop_after_delay, wait_exponential

from . import helpers

# ---------------------------------------------------------------------------
# pytest CLI options
# ---------------------------------------------------------------------------

PROFILES_DIR = Path(__file__).parent / "profiles"


def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line("markers", "e2e: End-to-end test requiring infrastructure")
    config.addinivalue_line(
        "markers", "slow: Test with long wait (CloudWatch propagation)"
    )
    config.addinivalue_line(
        "markers",
        "flaky_cloudwatch: May fail due to CloudWatch propagation delay (auto-reruns)",
    )
    config.addinivalue_line(
        "markers", "flaky_eventual: May fail due to eventual consistency (auto-reruns)"
    )
    config.addinivalue_line(
        "markers", "flaky_coldstart: May fail due to cold-start latency (auto-reruns)"
    )
    config.addinivalue_line(
        "markers", "timeout: Set test timeout in seconds (requires pytest-timeout)"
    )
    config.addinivalue_line(
        "markers",
        "flaky: Mark test for automatic reruns on failure (requires pytest-rerunfailures)",
    )


def pytest_addoption(parser):
    """Add --profile CLI arg for selecting E2E profile."""
    parser.addoption(
        "--profile",
        action="store",
        default=None,
        help="E2E profile name (without .json extension) or full path",
    )


# ---------------------------------------------------------------------------
# Core fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def run_id() -> str:
    """Unique ID per test session for parallel safety.

    Used in test user emails, DynamoDB partition keys, and any shared state
    that could collide between concurrent runs.
    """
    return uuid.uuid4().hex[:12]


@pytest.fixture(scope="session")
def isolated_config_dir(tmp_path_factory, e2e_profile, run_id) -> Path:
    """Create an isolated config directory per profile to prevent cross-profile pollution.

    Each profile gets its own temp dir for config, caches, and keyring data.
    This allows parallel execution without ~/claude-code-with-bedrock/ collisions.
    """
    profile_name = e2e_profile["name"]
    config_dir = tmp_path_factory.mktemp(f"ccwb-{profile_name}-{run_id}")

    # Create expected subdirectories
    (config_dir / "cache").mkdir()
    (config_dir / "tokens").mkdir()
    (config_dir / "keyring").mkdir()

    return config_dir


@pytest.fixture(scope="session")
def e2e_profile(request) -> Dict[str, Any]:
    """Load E2E profile JSON based on --profile arg or E2E_PROFILE env var."""
    profile_name = request.config.getoption("--profile") or os.environ.get(
        "E2E_PROFILE"
    )

    if not profile_name:
        pytest.skip("E2E not configured: set --profile or E2E_PROFILE env var")

    # Support both name and full path
    profile_path = Path(profile_name)
    if not profile_path.exists():
        profile_path = PROFILES_DIR / f"{profile_name}.json"

    if not profile_path.exists():
        pytest.skip(f"E2E profile not found: {profile_path}")

    with open(profile_path) as f:
        profile = json.load(f)

    return profile


@pytest.fixture(scope="session")
def credential_process_binary(e2e_profile) -> Path:
    """Resolve credential-process binary path for the profile's platform."""
    platform = e2e_profile["platform"]
    base_dir = Path(__file__).parent.parent.parent / "source" / "go"

    platform_map = {
        "linux-x64": "credential-process-linux-amd64",
        "windows-x64": "credential-process-windows-amd64.exe",
        "macos-arm64": "credential-process-darwin-arm64",
    }

    binary_name = platform_map.get(platform)
    if not binary_name:
        pytest.skip(f"Unsupported platform: {platform}")

    # Check dist/ and build/ locations
    for search_dir in ["dist", "build", "."]:
        binary_path = base_dir / search_dir / binary_name
        if binary_path.exists():
            return binary_path

    # Also check E2E_BINARY_PATH env var
    env_path = os.environ.get("E2E_BINARY_PATH")
    if env_path:
        env_binary = Path(env_path)
        if env_binary.exists():
            return env_binary

    pytest.skip(f"Binary not found for platform {platform}: {binary_name}")


@pytest.fixture(scope="session")
def otel_helper_binary(e2e_profile) -> Path:
    """Resolve otel-helper binary path for the profile's platform."""
    platform = e2e_profile["platform"]
    base_dir = Path(__file__).parent.parent.parent / "source" / "go"

    platform_map = {
        "linux-x64": "otel-helper-linux-amd64",
        "windows-x64": "otel-helper-windows-amd64.exe",
        "macos-arm64": "otel-helper-darwin-arm64",
    }

    binary_name = platform_map.get(platform)
    if not binary_name:
        pytest.skip(f"Unsupported platform for otel-helper: {platform}")

    for search_dir in ["dist", "build", "."]:
        binary_path = base_dir / search_dir / binary_name
        if binary_path.exists():
            return binary_path

    env_path = os.environ.get("E2E_OTEL_BINARY_PATH")
    if env_path:
        env_binary = Path(env_path)
        if env_binary.exists():
            return env_binary

    pytest.skip(f"otel-helper binary not found for platform {platform}")


@pytest.fixture(scope="session")
def stack_outputs() -> Dict[str, str]:
    """Read deployed stack outputs from artifact JSON."""
    outputs_path = os.environ.get(
        "E2E_STACK_OUTPUTS",
        str(Path(__file__).parent / "artifacts" / "stack-outputs.json"),
    )

    if not Path(outputs_path).exists():
        pytest.skip(f"Stack outputs not found: {outputs_path}")

    with open(outputs_path) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Helper fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def aws_region() -> str:
    """Get AWS region from env or default."""
    return os.environ.get(
        "AWS_REGION", os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
    )


@pytest.fixture(scope="session")
def dynamodb_client(aws_region):
    """Create DynamoDB client for quota operations."""
    try:
        return boto3.client("dynamodb", region_name=aws_region)
    except Exception:
        pytest.skip("AWS credentials not available for DynamoDB")


@pytest.fixture(scope="session")
def cloudwatch_client(aws_region):
    """Create CloudWatch client for metric queries."""
    try:
        return boto3.client("cloudwatch", region_name=aws_region)
    except Exception:
        pytest.skip("AWS credentials not available for CloudWatch")


# ---------------------------------------------------------------------------
# Utility functions exposed as fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def run_credential_process(
    credential_process_binary, e2e_profile, isolated_config_dir, run_id
):
    """Factory fixture: invoke credential-process binary with profile env vars."""

    def _run(
        extra_args: Optional[list] = None,
        extra_env: Optional[Dict[str, str]] = None,
        timeout: int = 30,
        context: str = "initial",
    ) -> subprocess.CompletedProcess:
        env = os.environ.copy()

        # Cross-profile isolation: each profile gets its own config/cache/token dirs
        env["CCWB_CONFIG_DIR"] = str(isolated_config_dir)
        env["CCWB_CACHE_DIR"] = str(isolated_config_dir / "cache")
        env["CCWB_TOKEN_DIR"] = str(isolated_config_dir / "tokens")
        env["E2E_RUN_ID"] = run_id
        env["E2E_PROFILE"] = e2e_profile["name"]

        # Seed config.json in the binary's expected path (~/claude-code-with-bedrock/)
        # Override HOME so each profile gets isolated config
        fake_home = isolated_config_dir / "home"
        fake_home.mkdir(exist_ok=True)
        config_dir = fake_home / "claude-code-with-bedrock"
        config_dir.mkdir(exist_ok=True)
        config_file = config_dir / "config.json"
        if not config_file.exists():
            profile_config = {
                "auth_type": e2e_profile["auth"]["type"],
                "region": "us-east-1",
                "monitoring": e2e_profile.get("monitoring", {"mode": "none"}),
                "quota": e2e_profile.get("quota", {"enabled": False}),
            }
            if e2e_profile["auth"].get("federation"):
                profile_config["federation"] = e2e_profile["auth"]["federation"]
            config = {"profiles": {"ClaudeCode": profile_config}}
            config_file.write_text(json.dumps(config, indent=2))
        env["HOME"] = str(fake_home)

        # Set profile-derived env vars
        auth = e2e_profile["auth"]
        env["CCWB_AUTH_TYPE"] = auth["type"]
        if auth.get("federation"):
            env["CCWB_AUTH_FEDERATION"] = auth["federation"]
        if auth.get("provider"):
            env["CCWB_AUTH_PROVIDER"] = auth["provider"]

        # Monitoring config
        monitoring = e2e_profile.get("monitoring", {})
        if monitoring.get("mode"):
            env["CCWB_MONITORING_MODE"] = monitoring["mode"]

        # Config delivery
        env["CCWB_CONFIG_DELIVERY"] = e2e_profile.get("config_delivery", "static")

        # Quota config
        quota = e2e_profile.get("quota", {})
        if quota.get("enabled"):
            env["CCWB_QUOTA_ENABLED"] = "true"
            if quota.get("enforcement"):
                env["CCWB_QUOTA_ENFORCEMENT"] = quota["enforcement"]
            if quota.get("fine_grained"):
                env["CCWB_QUOTA_FINE_GRAINED"] = "true"

        # Context (initial vs mid-session-refresh)
        env["CCWB_AUTH_CONTEXT"] = context

        if context == "mid-session-refresh":
            env["CCWB_FORCE_REFRESH"] = "1"

        # Override with caller-provided env
        if extra_env:
            env.update(extra_env)

        cmd = [str(credential_process_binary)]
        if extra_args:
            cmd.extend(extra_args)

        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )

    return _run


@pytest.fixture(scope="session")
def wait_for_port():
    """Factory fixture: TCP connect poll with retry."""

    def _wait(port: int, host: str = "127.0.0.1", timeout: float = 10.0) -> bool:
        return helpers.wait_for_port(host=host, port=port, timeout=timeout)

    return _wait


@pytest.fixture(scope="session")
def query_cloudwatch_metric(cloudwatch_client):
    """Factory fixture: polls CloudWatch metric with exponential backoff."""

    @retry(
        stop=stop_after_delay(90),
        wait=wait_exponential(multiplier=2, min=5, max=30),
    )
    def _query(
        namespace: str,
        metric_name: str,
        dimensions: list,
        period: int = 60,
    ) -> float:
        end_time = datetime.datetime.utcnow()
        start_time = end_time - datetime.timedelta(minutes=5)

        response = cloudwatch_client.get_metric_statistics(
            Namespace=namespace,
            MetricName=metric_name,
            Dimensions=dimensions,
            StartTime=start_time,
            EndTime=end_time,
            Period=period,
            Statistics=["Sum"],
        )

        datapoints = response.get("Datapoints", [])
        if not datapoints:
            raise ValueError(f"No datapoints for {namespace}/{metric_name}")

        return datapoints[-1]["Sum"]

    return _query


@pytest.fixture(scope="session")
def seed_quota_usage(dynamodb_client):
    """Factory fixture: write token usage to DynamoDB quota table."""

    def _seed(table_name: str, user: str, tokens: int):
        dynamodb_client.put_item(
            TableName=table_name,
            Item={
                "pk": {"S": f"USER#{user}"},
                "sk": {"S": "USAGE#current"},
                "tokens_used": {"N": str(tokens)},
                "updated_at": {"S": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())},
            },
        )

    return _seed


@pytest.fixture(scope="session")
def set_user_quota_policy(dynamodb_client):
    """Factory fixture: write per-user quota policy to DynamoDB."""

    def _set(table_name: str, user: str, limit: int):
        dynamodb_client.put_item(
            TableName=table_name,
            Item={
                "pk": {"S": f"USER#{user}"},
                "sk": {"S": "POLICY#quota"},
                "token_limit": {"N": str(limit)},
                "enforcement": {"S": "block"},
                "updated_at": {"S": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())},
            },
        )

    return _set


@pytest.fixture(scope="session")
def set_group_quota_policy(dynamodb_client):
    """Factory fixture: write group-level quota policy to DynamoDB."""

    def _set(table_name: str, group: str, limit: int):
        dynamodb_client.put_item(
            TableName=table_name,
            Item={
                "pk": {"S": f"GROUP#{group}"},
                "sk": {"S": "POLICY#quota"},
                "token_limit": {"N": str(limit)},
                "enforcement": {"S": "block"},
                "updated_at": {"S": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())},
            },
        )

    return _set


# ---------------------------------------------------------------------------
# Quota cleanup fixture (use with request.addfinalizer)
# ---------------------------------------------------------------------------


@pytest.fixture
def quota_cleanup(dynamodb_client, aws_region):
    """Fixture that registers cleanup of quota data after each test.

    Usage in tests:
        def test_something(quota_cleanup):
            quota_cleanup("my-table", "test-user-123")
            # ... test logic ...
            # cleanup happens automatically after test
    """
    cleanup_items = []

    def _register(table_name: str, user: str):
        cleanup_items.append((table_name, user))

    yield _register

    # Finalizer: clean up all registered quota data
    for table_name, user in cleanup_items:
        helpers.cleanup_quota_data(table=table_name, user=user, region=aws_region)


@pytest.fixture
def test_user_email(run_id):
    """Generate a unique test user email scoped to this run."""

    def _email(prefix: str = "e2e") -> str:
        return f"{prefix}-{run_id}@test.ccwb.internal"

    return _email


# ---------------------------------------------------------------------------
# Auto-skip logic based on profile test declarations
# ---------------------------------------------------------------------------


def pytest_collection_modifyitems(config, items):
    """Skip tests whose module is not declared in the active profile."""
    profile_name = config.getoption("--profile") or os.environ.get("E2E_PROFILE")
    if not profile_name:
        return

    # Load profile
    profile_path = Path(profile_name)
    if not profile_path.exists():
        profile_path = PROFILES_DIR / f"{profile_name}.json"
    if not profile_path.exists():
        return

    with open(profile_path) as f:
        profile = json.load(f)

    declared_tests = set(profile.get("tests", []))

    # Map test module names to profile test declarations
    module_to_profile_test = {
        "test_auth_flow": "auth_flow",
        "test_credential_output": "credential_output",
        "test_monitoring_pipeline": "monitoring_pipeline",
        "test_quota_enforcement": "quota_enforcement",
        "test_config_delivery": "config_delivery",
        "test_binary_platform": "binary_platform",
    }

    for item in items:
        module_name = item.module.__name__.split(".")[-1]
        profile_test_name = module_to_profile_test.get(module_name)

        if profile_test_name and profile_test_name not in declared_tests:
            item.add_marker(
                pytest.mark.skip(
                    reason=f"Profile '{profile.get('name')}' does not include '{profile_test_name}'"
                )
            )
