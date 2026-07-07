# ABOUTME: pytest fixtures for idc-landing-page Lambda tests
# ABOUTME: Sets required env vars before import and provides a moto-mocked S3 bucket

import os
import sys
import importlib

import pytest
import boto3
from moto import mock_aws

# Required environment variables must be set BEFORE index.py is imported,
# since it reads them at module scope via os.environ[...].
os.environ.setdefault('S3_BUCKET_NAME', 'test-bucket')
os.environ.setdefault('COGNITO_DOMAIN', 'test-domain.auth.us-east-1.amazoncognito.com')
os.environ.setdefault('COGNITO_CLIENT_ID', 'test-client-id')
os.environ.setdefault('COGNITO_USER_POOL_ID', 'us-east-1_TESTPOOL')
os.environ.setdefault('COGNITO_BOOTSTRAP_CLIENT_ID', 'test-bootstrap-client-id')
os.environ.setdefault('REGION', 'us-east-1')
os.environ.setdefault('ADMIN_GROUP', 'Claude-Code-Admins')
os.environ.setdefault('SESSION_SIGNING_SECRET_ARN', 'arn:aws:secretsmanager:us-east-1:123456789012:secret:test-session-secret')

# Make `lambda/` importable as the package root (so `import index` and
# `from shared import ...` resolve the same way they do inside the real
# Lambda runtime, which zips lambda/ as the deployment root).
LAMBDA_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if LAMBDA_DIR not in sys.path:
    sys.path.insert(0, LAMBDA_DIR)


@pytest.fixture()
def aws_credentials():
    """Dummy AWS creds so boto3 never touches real credentials."""
    os.environ['AWS_ACCESS_KEY_ID'] = 'testing'
    os.environ['AWS_SECRET_ACCESS_KEY'] = 'testing'
    os.environ['AWS_SECURITY_TOKEN'] = 'testing'
    os.environ['AWS_SESSION_TOKEN'] = 'testing'
    os.environ['AWS_DEFAULT_REGION'] = 'us-east-1'


@pytest.fixture()
def mocked_aws(aws_credentials):
    """Start moto's AWS mock and yield control."""
    with mock_aws():
        yield


@pytest.fixture()
def idx(mocked_aws):
    """Import (or reload) index.py with mocked AWS + fresh module-level clients.

    index.py creates boto3 clients at import time, so the module must be
    (re)imported *inside* the mock_aws() context for its s3_client etc. to
    be moto-backed rather than real.
    """
    import index as idx_module
    importlib.reload(idx_module)
    yield idx_module


@pytest.fixture()
def bucket(idx):
    """Create the S3 bucket that index.py expects (BUCKET_NAME)."""
    s3 = boto3.client('s3', region_name='us-east-1')
    s3.create_bucket(Bucket=idx.BUCKET_NAME)
    return idx.BUCKET_NAME


@pytest.fixture()
def session_secret(idx):
    """Seed the mocked Secrets Manager secret index.py signs sessions with.

    Also resets the module-level secret cache, since tests reload `idx` but
    the cache is a plain module global that would otherwise leak a stale
    (or missing) value across tests that reuse the same moto session.
    """
    sm = boto3.client('secretsmanager', region_name='us-east-1')
    sm.create_secret(Name='test-session-secret', SecretString='test-signing-key-not-for-production')
    idx._session_signing_secret_cache = None
    return 'test-signing-key-not-for-production'


def make_session_token(idx, email='alice@example.com', name='', exp_delta=3600):
    """Build a real HMAC-signed session token via index.create_session_token(),
    so tests exercise the same signing path as production rather than
    hand-rolling the (previously forgeable) format."""
    return idx.create_session_token(email=email, name=name, ttl_seconds=exp_delta)


def mock_cognito_get_user(idx, monkeypatch, email, username=None):
    """Monkeypatch verify_cognito_access_token() to simulate a successful
    Cognito GetUser call, without needing a real access token or a moto
    Cognito Identity Provider mock (moto's cognito-idp GetUser support is
    limited). Any non-empty token string is treated as valid; the point of
    these tests is to exercise index.py's handling of the *result*, not to
    re-test Cognito's own token validation.
    """
    def fake_verify(access_token):
        if not access_token:
            return None
        return {'email': email, 'username': username or email}
    monkeypatch.setattr(idx, 'verify_cognito_access_token', fake_verify)
