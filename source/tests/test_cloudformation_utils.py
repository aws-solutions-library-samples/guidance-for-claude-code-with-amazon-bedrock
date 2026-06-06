# ABOUTME: Unit tests for cloudformation.py utils — CloudFormationManager
# ABOUTME: Covers deploy_stack, delete_stack, exception mapping, template validation

"""Tests for claude_code_with_bedrock.cli.utils.cloudformation module."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

from claude_code_with_bedrock.cli.utils.cf_exceptions import (
    CloudFormationError,
    PermissionError as CfnPermissionError,
    ResourceConflictError,
    StackNotFoundError,
    TemplateValidationError,
)
from claude_code_with_bedrock.cli.utils.cloudformation import (
    CloudFormationManager,
    StackDeploymentResult,
    StackDeletionResult,
)


@pytest.fixture
def cfn_manager():
    """CloudFormationManager with mocked boto3 session."""
    with patch("claude_code_with_bedrock.cli.utils.cloudformation.boto3") as mock_boto3:
        mock_session = MagicMock()
        mock_boto3.Session.return_value = mock_session
        mock_cf = MagicMock()
        mock_s3 = MagicMock()
        mock_session.client.side_effect = lambda svc, **kw: mock_cf if svc == "cloudformation" else mock_s3
        manager = CloudFormationManager(region="us-east-1")
        manager._cf_client = mock_cf
        manager._s3_client = mock_s3
        yield manager


@pytest.fixture
def small_template(tmp_path):
    """Create a small valid CloudFormation template."""
    template = tmp_path / "template.yaml"
    template.write_text(
        "AWSTemplateFormatVersion: '2010-09-09'\n"
        "Description: Test template\n"
        "Resources:\n"
        "  MyBucket:\n"
        "    Type: AWS::S3::Bucket\n"
    )
    return str(template)


class TestStackDeploymentResult:
    """Tests for StackDeploymentResult."""

    def test_success_result(self):
        result = StackDeploymentResult(success=True, stack_id="stack-123", outputs={"Key": "val"})
        assert result.success is True
        assert result.stack_id == "stack-123"
        assert result.outputs == {"Key": "val"}

    def test_failure_result(self):
        result = StackDeploymentResult(success=False, error="Something broke")
        assert result.success is False
        assert result.error == "Something broke"
        assert result.outputs == {}

    def test_default_outputs_empty(self):
        result = StackDeploymentResult(success=True)
        assert result.outputs == {}


class TestStackDeletionResult:
    """Tests for StackDeletionResult."""

    def test_success(self):
        result = StackDeletionResult(success=True)
        assert result.success is True

    def test_failure(self):
        result = StackDeletionResult(success=False, error="Cannot delete")
        assert result.success is False
        assert result.error == "Cannot delete"


class TestCloudFormationManagerInit:
    """Tests for CloudFormationManager initialization."""

    @patch("claude_code_with_bedrock.cli.utils.cloudformation.boto3")
    def test_init_with_region_only(self, mock_boto3):
        manager = CloudFormationManager(region="eu-west-1")
        mock_boto3.Session.assert_called_with(region_name="eu-west-1")

    @patch("claude_code_with_bedrock.cli.utils.cloudformation.boto3")
    def test_init_with_profile(self, mock_boto3):
        manager = CloudFormationManager(region="us-east-1", profile="my-profile")
        mock_boto3.Session.assert_called_with(region_name="us-east-1", profile_name="my-profile")

    @patch("claude_code_with_bedrock.cli.utils.cloudformation.boto3")
    def test_lazy_cf_client(self, mock_boto3):
        mock_session = MagicMock()
        mock_boto3.Session.return_value = mock_session
        manager = CloudFormationManager(region="us-east-1")
        assert manager._cf_client is None
        _ = manager.cf_client
        mock_session.client.assert_called_with("cloudformation")

    @patch("claude_code_with_bedrock.cli.utils.cloudformation.boto3")
    def test_lazy_s3_client(self, mock_boto3):
        mock_session = MagicMock()
        mock_boto3.Session.return_value = mock_session
        manager = CloudFormationManager(region="us-east-1")
        assert manager._s3_client is None
        _ = manager.s3_client
        mock_session.client.assert_called_with("s3")


class TestDeployStack:
    """Tests for deploy_stack method."""

    def test_create_new_stack(self, cfn_manager, small_template):
        """New stack: calls create_stack and waits."""
        cfn_manager._cf_client.describe_stacks.side_effect = ClientError(
            {"Error": {"Code": "ValidationError", "Message": "does not exist"}}, "DescribeStacks"
        )
        cfn_manager._cf_client.create_stack.return_value = {"StackId": "arn:aws:cfn:us-east-1:123:stack/test/abc"}

        # Mock the waiter
        waiter_mock = MagicMock()
        cfn_manager._cf_client.get_waiter.return_value = waiter_mock

        # Mock get_stack_outputs
        cfn_manager._cf_client.describe_stacks.side_effect = [
            ClientError({"Error": {"Code": "ValidationError", "Message": "does not exist"}}, "DescribeStacks"),
            {"Stacks": [{"StackStatus": "CREATE_COMPLETE", "Outputs": [{"OutputKey": "Url", "OutputValue": "https://x"}]}]},
        ]

        result = cfn_manager.deploy_stack(stack_name="test-stack", template_path=small_template)
        assert result.success is True

    def test_template_too_large_fails(self, cfn_manager, tmp_path):
        """Template >51200 bytes should raise CloudFormationError."""
        big_template = tmp_path / "big.yaml"
        big_template.write_text("A" * 52000)

        # Stack doesn't exist — need to mock _check_stack_exists properly
        cfn_manager._cf_client.describe_stacks.side_effect = ClientError(
            {"Error": {"Code": "ValidationError", "Message": "does not exist"}}, "DescribeStacks"
        )

        result = cfn_manager.deploy_stack(stack_name="big-stack", template_path=str(big_template))
        # deploy_stack catches the exception internally and returns failure
        assert result.success is False
        assert "exceeds" in result.error or "51,200" in result.error

    def test_no_updates_needed(self, cfn_manager, small_template):
        """Update with no changes returns success."""
        # Stack exists
        cfn_manager._cf_client.describe_stacks.return_value = {
            "Stacks": [{"StackStatus": "CREATE_COMPLETE", "Outputs": [{"OutputKey": "K", "OutputValue": "V"}]}]
        }
        # update_stack raises "No updates"
        cfn_manager._cf_client.update_stack.side_effect = ClientError(
            {"Error": {"Code": "ValidationError", "Message": "No updates are to be performed"}}, "UpdateStack"
        )

        result = cfn_manager.deploy_stack(stack_name="test-stack", template_path=small_template)
        assert result.success is True
        assert result.outputs == {"K": "V"}

    def test_validation_error_raises(self, cfn_manager, small_template):
        """Template validation errors raise TemplateValidationError."""
        cfn_manager._cf_client.describe_stacks.side_effect = ClientError(
            {"Error": {"Code": "ValidationError", "Message": "does not exist"}}, "DescribeStacks"
        )
        cfn_manager._cf_client.create_stack.side_effect = ClientError(
            {"Error": {"Code": "ValidationError", "Message": "Invalid template property"}}, "CreateStack"
        )

        with pytest.raises(TemplateValidationError):
            cfn_manager.deploy_stack(stack_name="bad-stack", template_path=small_template)

    def test_insufficient_capabilities_raises(self, cfn_manager, small_template):
        """Missing IAM capabilities raise PermissionError."""
        cfn_manager._cf_client.describe_stacks.side_effect = ClientError(
            {"Error": {"Code": "ValidationError", "Message": "does not exist"}}, "DescribeStacks"
        )
        cfn_manager._cf_client.create_stack.side_effect = ClientError(
            {"Error": {"Code": "InsufficientCapabilitiesException", "Message": "Requires CAPABILITY_IAM"}},
            "CreateStack",
        )

        with pytest.raises(CfnPermissionError):
            cfn_manager.deploy_stack(stack_name="test-stack", template_path=small_template)

    def test_resource_conflict_raises(self, cfn_manager, small_template):
        """AlreadyExistsException with LogGroup raises ResourceConflictError."""
        cfn_manager._cf_client.describe_stacks.side_effect = ClientError(
            {"Error": {"Code": "ValidationError", "Message": "does not exist"}}, "DescribeStacks"
        )
        cfn_manager._cf_client.create_stack.side_effect = ClientError(
            {"Error": {"Code": "AlreadyExistsException", "Message": "LogGroup /aws/x already exists"}},
            "CreateStack",
        )

        with pytest.raises(ResourceConflictError):
            cfn_manager.deploy_stack(stack_name="test-stack", template_path=small_template)


class TestDeleteStack:
    """Tests for delete_stack method."""

    def test_successful_delete(self, cfn_manager):
        """Delete stack that exists."""
        cfn_manager._cf_client.describe_stacks.return_value = {
            "Stacks": [{"StackStatus": "CREATE_COMPLETE"}]
        }
        waiter_mock = MagicMock()
        cfn_manager._cf_client.get_waiter.return_value = waiter_mock

        result = cfn_manager.delete_stack("test-stack")
        assert result.success is True
        cfn_manager._cf_client.delete_stack.assert_called_once()

    def test_delete_nonexistent_stack(self, cfn_manager):
        """Delete stack that doesn't exist — should still succeed."""
        cfn_manager._cf_client.describe_stacks.side_effect = ClientError(
            {"Error": {"Code": "ValidationError", "Message": "does not exist"}}, "DescribeStacks"
        )

        result = cfn_manager.delete_stack("ghost-stack")
        assert result.success is True


class TestGetStackOutputs:
    """Tests for get_stack_outputs."""

    def test_returns_outputs_dict(self, cfn_manager):
        cfn_manager._cf_client.describe_stacks.return_value = {
            "Stacks": [{
                "StackStatus": "CREATE_COMPLETE",
                "Outputs": [
                    {"OutputKey": "BucketName", "OutputValue": "my-bucket"},
                    {"OutputKey": "Endpoint", "OutputValue": "https://api.example.com"},
                ],
            }]
        }

        outputs = cfn_manager.get_stack_outputs("my-stack")
        assert outputs == {"BucketName": "my-bucket", "Endpoint": "https://api.example.com"}

    def test_no_outputs_returns_empty(self, cfn_manager):
        cfn_manager._cf_client.describe_stacks.return_value = {
            "Stacks": [{"StackStatus": "CREATE_COMPLETE"}]
        }

        outputs = cfn_manager.get_stack_outputs("my-stack")
        assert outputs == {}


class TestGetStackStatus:
    """Tests for get_stack_status."""

    def test_returns_status(self, cfn_manager):
        cfn_manager._cf_client.describe_stacks.return_value = {
            "Stacks": [{"StackStatus": "UPDATE_IN_PROGRESS"}]
        }
        assert cfn_manager.get_stack_status("my-stack") == "UPDATE_IN_PROGRESS"

    def test_nonexistent_returns_none(self, cfn_manager):
        cfn_manager._cf_client.describe_stacks.side_effect = ClientError(
            {"Error": {"Code": "ValidationError", "Message": "does not exist"}}, "DescribeStacks"
        )
        assert cfn_manager.get_stack_status("ghost-stack") is None


class TestValidateTemplate:
    """Tests for validate_template."""

    def test_valid_template(self, cfn_manager, small_template):
        cfn_manager._cf_client.validate_template.return_value = {}
        assert cfn_manager.validate_template(small_template) is True

    def test_invalid_template(self, cfn_manager, small_template):
        cfn_manager._cf_client.validate_template.side_effect = ClientError(
            {"Error": {"Code": "ValidationError", "Message": "Template format error"}}, "ValidateTemplate"
        )
        with pytest.raises(TemplateValidationError):
            cfn_manager.validate_template(small_template)
