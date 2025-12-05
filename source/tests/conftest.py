"""Pytest configuration and shared fixtures."""

import os

import pytest


# Set AWS region for all tests to avoid NoRegionError
@pytest.fixture(autouse=True, scope="session")
def set_aws_region():
    """Set AWS region for all tests."""
    os.environ["AWS_DEFAULT_REGION"] = "us-east-1"
    os.environ["AWS_REGION"] = "us-east-1"
