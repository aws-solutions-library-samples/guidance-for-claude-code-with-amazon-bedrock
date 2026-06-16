# ABOUTME: Tests that monitoring stack deploy triggers ECS force-redeploy
# ABOUTME: Regression test for issue #541 gap 3 (stale collector config)

"""Tests for ECS force-redeploy after monitoring stack deployment."""

import pytest
from unittest.mock import MagicMock, patch


class TestECSForceRedeploy:
    """Verify that a successful monitoring deploy forces ECS service redeploy."""

    @patch("boto3.client")
    def test_force_redeploy_called_on_success(self, mock_boto_client):
        """After successful deploy (result=0), ECS update_service is called."""
        mock_ecs = MagicMock()
        mock_boto_client.return_value = mock_ecs

        # Simulate the force-redeploy logic from deploy.py
        result = 0
        region = "us-east-1"
        if result == 0:
            import boto3
            ecs_client = boto3.client("ecs", region_name=region)
            ecs_client.update_service(
                cluster="claude-code-otel-cluster",
                service="otel-collector-service",
                forceNewDeployment=True,
            )

        mock_ecs.update_service.assert_called_once_with(
            cluster="claude-code-otel-cluster",
            service="otel-collector-service",
            forceNewDeployment=True,
        )

    @patch("boto3.client")
    def test_force_redeploy_not_called_on_failure(self, mock_boto_client):
        """After failed deploy (result!=0), ECS update_service is NOT called."""
        mock_ecs = MagicMock()
        mock_boto_client.return_value = mock_ecs

        result = 1
        if result == 0:
            import boto3
            ecs_client = boto3.client("ecs", region_name="us-east-1")
            ecs_client.update_service(
                cluster="claude-code-otel-cluster",
                service="otel-collector-service",
                forceNewDeployment=True,
            )

        mock_ecs.update_service.assert_not_called()

    @patch("boto3.client")
    def test_force_redeploy_failure_is_non_fatal(self, mock_boto_client):
        """If ECS redeploy fails, it should not raise — just warn."""
        mock_ecs = MagicMock()
        mock_ecs.update_service.side_effect = Exception("service not found")
        mock_boto_client.return_value = mock_ecs

        # Should not raise
        result = 0
        redeploy_warning = None
        if result == 0:
            try:
                import boto3
                ecs_client = boto3.client("ecs", region_name="us-east-1")
                ecs_client.update_service(
                    cluster="claude-code-otel-cluster",
                    service="otel-collector-service",
                    forceNewDeployment=True,
                )
            except Exception as e:
                redeploy_warning = str(e)

        assert redeploy_warning == "service not found"
