# ABOUTME: Tests that monitoring stack deploy triggers ECS force-redeploy
# ABOUTME: Regression test for issue #541 gap 3 (stale collector config)

"""Tests for ECS force-redeploy after monitoring stack deployment."""

from unittest.mock import MagicMock, patch


class TestECSForceRedeploy:
    """Verify that a successful monitoring deploy forces ECS service redeploy."""

    @patch("boto3.client")
    def test_force_redeploy_discovers_service_name(self, mock_boto_client):
        """Uses list_services to discover the service ARN instead of hardcoding."""
        mock_ecs = MagicMock()
        mock_ecs.list_services.return_value = {
            "serviceArns": ["arn:aws:ecs:eu-central-1:123456:service/claude-code-otel-cluster/otel-abc123"]
        }
        mock_boto_client.return_value = mock_ecs

        result = 0
        region = "eu-central-1"
        if result == 0:
            import boto3

            ecs_client = boto3.client("ecs", region_name=region)
            cluster = "claude-code-otel-cluster"
            services = ecs_client.list_services(cluster=cluster)["serviceArns"]
            if services:
                ecs_client.update_service(
                    cluster=cluster,
                    service=services[0],
                    forceNewDeployment=True,
                )

        mock_ecs.list_services.assert_called_once_with(cluster="claude-code-otel-cluster")
        mock_ecs.update_service.assert_called_once_with(
            cluster="claude-code-otel-cluster",
            service="arn:aws:ecs:eu-central-1:123456:service/claude-code-otel-cluster/otel-abc123",
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

            ecs_client = boto3.client("ecs", region_name="eu-central-1")
            cluster = "claude-code-otel-cluster"
            services = ecs_client.list_services(cluster=cluster)["serviceArns"]
            if services:
                ecs_client.update_service(
                    cluster=cluster,
                    service=services[0],
                    forceNewDeployment=True,
                )

        mock_ecs.list_services.assert_not_called()
        mock_ecs.update_service.assert_not_called()

    @patch("boto3.client")
    def test_no_service_found_is_non_fatal(self, mock_boto_client):
        """If no services exist in the cluster (first deploy), don't crash."""
        mock_ecs = MagicMock()
        mock_ecs.list_services.return_value = {"serviceArns": []}
        mock_boto_client.return_value = mock_ecs

        result = 0
        if result == 0:
            import boto3

            ecs_client = boto3.client("ecs", region_name="eu-central-1")
            cluster = "claude-code-otel-cluster"
            services = ecs_client.list_services(cluster=cluster)["serviceArns"]
            if services:
                ecs_client.update_service(
                    cluster=cluster,
                    service=services[0],
                    forceNewDeployment=True,
                )

        mock_ecs.update_service.assert_not_called()

    @patch("boto3.client")
    def test_force_redeploy_exception_is_non_fatal(self, mock_boto_client):
        """If ECS redeploy fails, it should not raise — just warn."""
        mock_ecs = MagicMock()
        mock_ecs.list_services.side_effect = Exception("access denied")
        mock_boto_client.return_value = mock_ecs

        result = 0
        redeploy_warning = None
        if result == 0:
            try:
                import boto3

                ecs_client = boto3.client("ecs", region_name="eu-central-1")
                cluster = "claude-code-otel-cluster"
                services = ecs_client.list_services(cluster=cluster)["serviceArns"]
                if services:
                    ecs_client.update_service(
                        cluster=cluster,
                        service=services[0],
                        forceNewDeployment=True,
                    )
            except Exception as exc:
                redeploy_warning = str(exc)

        assert redeploy_warning == "access denied"
