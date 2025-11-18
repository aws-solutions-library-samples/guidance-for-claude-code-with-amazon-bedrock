# ABOUTME: CloudFormation manager using boto3 SDK
# ABOUTME: Replaces subprocess calls with native Python CloudFormation operations

"""CloudFormation manager for boto3-based stack operations."""

import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import boto3
import cfn_flip
from botocore.exceptions import ClientError, WaiterError

from .cf_exceptions import (
    CloudFormationError,
    PermissionError,
    ResourceConflictError,
    StackNotFoundError,
    TemplateValidationError,
)


class StackDeploymentResult:
    """Result of a stack deployment operation."""

    def __init__(self, success: bool, stack_id: str = None, outputs: dict[str, str] = None, error: str = None):
        self.success = success
        self.stack_id = stack_id
        self.outputs = outputs or {}
        self.error = error


class StackDeletionResult:
    """Result of a stack deletion operation."""

    def __init__(self, success: bool, error: str = None):
        self.success = success
        self.error = error


class CloudFormationManager:
    """
    Centralized CloudFormation operations manager.
    Replaces subprocess calls with boto3 SDK for better error handling and performance.
    """

    def __init__(self, region: str, profile: str = None):
        """
        Initialize CloudFormation manager.

        Args:
            region: AWS region
            profile: Optional AWS profile name
        """
        self.region = region
        self.session = (
            boto3.Session(region_name=region, profile_name=profile) if profile else boto3.Session(region_name=region)
        )
        self._cf_client = None
        self._s3_client = None

    @property
    def cf_client(self):
        """Lazy-loaded CloudFormation client with connection pooling."""
        if not self._cf_client:
            self._cf_client = self.session.client("cloudformation")
        return self._cf_client

    @property
    def s3_client(self):
        """Lazy-loaded S3 client for template packaging."""
        if not self._s3_client:
            self._s3_client = self.session.client("s3")
        return self._s3_client

    def deploy_stack(
        self,
        stack_name: str,
        template_path: str | Path,
        parameters: list[dict[str, str]] = None,
        capabilities: list[str] = None,
        tags: dict[str, str] = None,
        on_event: Callable = None,
        timeout: int = 3600,
        disable_rollback: bool = False,
    ) -> StackDeploymentResult:
        """
        Deploy or update a CloudFormation stack.

        This method handles both create and update operations automatically.
        Replaces: aws cloudformation deploy

        Args:
            stack_name: Name of the stack
            template_path: Path to CloudFormation template
            parameters: Stack parameters in boto3 format
            capabilities: IAM capabilities required
            tags: Tags to apply to the stack
            on_event: Callback for stack events
            timeout: Timeout in seconds
            disable_rollback: Disable automatic rollback on failure

        Returns:
            StackDeploymentResult with success status and outputs
        """
        try:
            # Read template
            template_body = self._read_template(template_path)

            # Check if stack exists
            exists, current_status = self._check_stack_exists(stack_name)

            # Handle ROLLBACK_COMPLETE state
            if current_status == "ROLLBACK_COMPLETE":
                if on_event:
                    on_event({"message": f"Stack {stack_name} is in ROLLBACK_COMPLETE state. Deleting..."})
                self.delete_stack(stack_name, force=True)
                exists = False

            # Prepare parameters
            params = {
                "StackName": stack_name,
                "TemplateBody": template_body,
                "Capabilities": capabilities or [],
            }

            if parameters:
                params["Parameters"] = parameters

            if tags:
                params["Tags"] = [{"Key": k, "Value": v} for k, v in tags.items()]

            if disable_rollback:
                params["DisableRollback"] = True

            # Create or update stack
            if not exists:
                if on_event:
                    on_event({"message": f"Creating stack {stack_name}..."})
                response = self.cf_client.create_stack(**params)
                stack_id = response["StackId"]
                wait_status = "stack_create_complete"
            else:
                if on_event:
                    on_event({"message": f"Updating stack {stack_name}..."})
                try:
                    # For updates, we need to use different parameters
                    update_params = params.copy()
                    update_params.pop("DisableRollback", None)  # Not valid for updates
                    response = self.cf_client.update_stack(**update_params)
                    stack_id = response["StackId"]
                    wait_status = "stack_update_complete"
                except ClientError as e:
                    if "No updates are to be performed" in str(e):
                        if on_event:
                            on_event({"message": "Stack is up to date, no changes needed"})
                        outputs = self.get_stack_outputs(stack_name)
                        return StackDeploymentResult(success=True, stack_id=stack_name, outputs=outputs)
                    raise

            # Wait for completion with event streaming
            success = self._wait_for_stack(stack_name, wait_status, timeout, on_event)

            if success:
                outputs = self.get_stack_outputs(stack_name)
                return StackDeploymentResult(success=True, stack_id=stack_id, outputs=outputs)
            else:
                # Get failure reason
                error = self._get_stack_failure_reason(stack_name)
                return StackDeploymentResult(success=False, error=error)

        except ClientError as e:
            error_code = e.response["Error"]["Code"]
            error_message = e.response["Error"]["Message"]

            # Map to our custom exceptions
            if error_code == "ValidationError":
                if "does not exist" in error_message:
                    raise StackNotFoundError(f"Stack {stack_name} not found: {error_message}") from e
                else:
                    raise TemplateValidationError(f"Template validation failed: {error_message}") from e
            elif error_code == "InsufficientCapabilitiesException":
                raise PermissionError(f"Insufficient capabilities: {error_message}") from None
            elif error_code == "AlreadyExistsException":
                if "LogGroup" in error_message:
                    raise ResourceConflictError(f"Resource already exists: {error_message}") from None
            else:
                raise CloudFormationError(f"CloudFormation error: {error_message}") from None

        except Exception as e:
            return StackDeploymentResult(success=False, error=str(e))

    def delete_stack(
        self,
        stack_name: str,
        retain_resources: list[str] = None,
        force: bool = False,
        on_event: Callable = None,
        timeout: int = 600,
    ) -> StackDeletionResult:
        """
        Delete a CloudFormation stack.

        Args:
            stack_name: Name of the stack to delete
            retain_resources: Resources to retain after deletion
            force: Force deletion even if in DELETE_FAILED state
            on_event: Callback for stack events
            timeout: Timeout in seconds

        Returns:
            StackDeletionResult with success status
        """
        try:
            # Check if stack exists
            exists, current_status = self._check_stack_exists(stack_name)

            if not exists:
                if on_event:
                    on_event({"message": f"Stack {stack_name} does not exist or already deleted"})
                return StackDeletionResult(success=True)

            # Handle DELETE_FAILED state
            if current_status == "DELETE_FAILED" and not force:
                return StackDeletionResult(
                    success=False, error="Stack is in DELETE_FAILED state. Use force=True to retry."
                )

            # Delete stack
            params = {"StackName": stack_name}
            if retain_resources:
                params["RetainResources"] = retain_resources

            if on_event:
                on_event({"message": f"Deleting stack {stack_name}..."})

            self.cf_client.delete_stack(**params)

            # Wait for deletion
            success = self._wait_for_stack(stack_name, "stack_delete_complete", timeout, on_event)

            return StackDeletionResult(success=success)

        except ClientError as e:
            error_message = e.response["Error"]["Message"]
            return StackDeletionResult(success=False, error=error_message)

        except Exception as e:
            return StackDeletionResult(success=False, error=str(e))

    def package_template(
        self, template_path: str | Path, s3_bucket: str, s3_prefix: str = None, on_event: Callable = None
    ) -> str:
        """
        Package a CloudFormation template and upload artifacts to S3.

        This handles Lambda functions and nested templates.
        Replaces: aws cloudformation package

        Args:
            template_path: Path to the template
            s3_bucket: S3 bucket for artifacts
            s3_prefix: Optional S3 key prefix
            on_event: Callback for progress

        Returns:
            Packaged template as string
        """
        template_path = Path(template_path)

        # Read template
        with open(template_path) as f:
            template_body = f.read()

        # Parse template using cfn-flip for CloudFormation compatibility
        if template_path.suffix in [".yaml", ".yml"]:
            template = cfn_flip.load_yaml(template_body)
        else:
            template = cfn_flip.load_json(template_body)

        # Process resources for packaging
        if "Resources" in template:
            for resource_name, resource in template["Resources"].items():
                # Ensure resource is a dict (cfn_flip might return special types)
                if not isinstance(resource, dict):
                    continue
                resource_type = resource.get("Type", "")

                # Handle Lambda functions
                if resource_type == "AWS::Lambda::Function":
                    code = resource.get("Properties", {}).get("Code", {})
                    if "ZipFile" not in code and code.get("S3Bucket") != s3_bucket:
                        # Need to package local code
                        local_path = template_path.parent / code.get("S3Key", "")
                        if local_path.exists():
                            # Upload to S3
                            s3_key = (
                                f"{s3_prefix}/{resource_name}/{local_path.name}"
                                if s3_prefix
                                else f"{resource_name}/{local_path.name}"
                            )

                            if on_event:
                                on_event({"message": f"Uploading {local_path.name} to s3://{s3_bucket}/{s3_key}"})

                            self.s3_client.upload_file(str(local_path), s3_bucket, s3_key)

                            # Update template
                            resource["Properties"]["Code"] = {"S3Bucket": s3_bucket, "S3Key": s3_key}

                # Handle nested stacks
                elif resource_type == "AWS::CloudFormation::Stack":
                    template_url = resource.get("Properties", {}).get("TemplateURL", "")
                    if not str(template_url).startswith("https://"):
                        # Need to package nested template
                        nested_path = template_path.parent / template_url
                        if nested_path.exists():
                            # Recursively package nested template
                            nested_packaged = self.package_template(nested_path, s3_bucket, s3_prefix, on_event)

                            # Upload packaged nested template
                            s3_key = (
                                f"{s3_prefix}/{resource_name}/template.yaml"
                                if s3_prefix
                                else f"{resource_name}/template.yaml"
                            )

                            if on_event:
                                on_event({"message": f"Uploading nested template to s3://{s3_bucket}/{s3_key}"})

                            self.s3_client.put_object(Bucket=s3_bucket, Key=s3_key, Body=nested_packaged)

                            # Update template
                            resource["Properties"]["TemplateURL"] = f"https://{s3_bucket}.s3.amazonaws.com/{s3_key}"

        # Return packaged template as YAML with CloudFormation intrinsic functions preserved
        return cfn_flip.dump_yaml(template)

    def get_stack_status(self, stack_name: str) -> str | None:
        """
        Get the current status of a stack.

        Args:
            stack_name: Name of the stack

        Returns:
            Stack status or None if not found
        """
        try:
            response = self.cf_client.describe_stacks(StackName=stack_name)
            if response["Stacks"]:
                return response["Stacks"][0]["StackStatus"]
            return None
        except ClientError as e:
            if e.response["Error"]["Code"] == "ValidationError":
                return None
            raise

    def get_stack_outputs(self, stack_name: str) -> dict[str, str]:
        """
        Get outputs from a CloudFormation stack.

        Args:
            stack_name: Name of the stack

        Returns:
            Dictionary of output keys and values
        """
        try:
            response = self.cf_client.describe_stacks(StackName=stack_name)
            if response["Stacks"]:
                stack = response["Stacks"][0]
                outputs = {}
                for output in stack.get("Outputs", []):
                    outputs[output["OutputKey"]] = output["OutputValue"]
                return outputs
            return {}
        except ClientError:
            return {}

    def list_stacks(self, status_filter: list[str] = None) -> list[dict[str, Any]]:
        """
        List CloudFormation stacks.

        Args:
            status_filter: Optional list of stack statuses to filter

        Returns:
            List of stack summaries
        """
        try:
            params = {}
            if status_filter:
                params["StackStatusFilter"] = status_filter

            response = self.cf_client.list_stacks(**params)
            return response.get("StackSummaries", [])
        except ClientError:
            return []

    def _read_template(self, template_path: str | Path) -> str:
        """Read and return template content."""
        template_path = Path(template_path)
        with open(template_path) as f:
            content = f.read()
        return content

    def _check_stack_exists(self, stack_name: str) -> tuple[bool, str | None]:
        """Check if stack exists and return its status."""
        try:
            response = self.cf_client.describe_stacks(StackName=stack_name)
            if response["Stacks"]:
                status = response["Stacks"][0]["StackStatus"]
                return True, status
            return False, None
        except ClientError as e:
            if e.response["Error"]["Code"] == "ValidationError":
                return False, None
            raise

    def _wait_for_stack(self, stack_name: str, waiter_name: str, timeout: int, on_event: Callable = None) -> bool:
        """
        Wait for stack operation to complete with event streaming.

        Args:
            stack_name: Name of the stack
            waiter_name: Name of the waiter (e.g., 'stack_create_complete')
            timeout: Timeout in seconds
            on_event: Callback for stack events

        Returns:
            True if successful, False otherwise
        """
        # Stream events while waiting
        if on_event:
            self._start_event_streaming(stack_name, on_event)

        try:
            waiter = self.cf_client.get_waiter(waiter_name)
            waiter.wait(StackName=stack_name, WaiterConfig={"Delay": 5, "MaxAttempts": timeout // 5})
            return True
        except WaiterError:
            # Check if it's a timeout or actual failure
            final_status = self.get_stack_status(stack_name)
            if final_status and "FAILED" in final_status:
                return False
            elif final_status and "ROLLBACK" in final_status:
                return False
            # Might be timeout
            return False
        except Exception:
            return False

    def _start_event_streaming(self, stack_name: str, on_event: Callable):
        """Start streaming stack events in a separate thread."""
        import threading

        seen_events = set()

        def stream_events():
            while True:
                try:
                    response = self.cf_client.describe_stack_events(StackName=stack_name)
                    for event in response.get("StackEvents", []):
                        event_id = event["EventId"]
                        if event_id not in seen_events:
                            seen_events.add(event_id)
                            # Format event for callback
                            formatted_event = {
                                "timestamp": event.get("Timestamp"),
                                "LogicalResourceId": event.get("LogicalResourceId"),
                                "ResourceType": event.get("ResourceType"),
                                "ResourceStatus": event.get("ResourceStatus"),
                                "ResourceStatusReason": event.get("ResourceStatusReason"),
                                "message": f"{event.get('LogicalResourceId')} - {event.get('ResourceStatus')}",
                            }
                            on_event(formatted_event)

                    # Check if stack operation is complete
                    status = self.get_stack_status(stack_name)
                    if status and ("COMPLETE" in status or "FAILED" in status):
                        break

                    time.sleep(2)
                except Exception:
                    break

        thread = threading.Thread(target=stream_events, daemon=True)
        thread.start()
        return thread

    def _get_stack_failure_reason(self, stack_name: str) -> str:
        """Get the failure reason from stack events."""
        try:
            response = self.cf_client.describe_stack_events(StackName=stack_name)
            events = response.get("StackEvents", [])

            # Find the first failure event
            for event in events:
                status = event.get("ResourceStatus", "")
                reason = event.get("ResourceStatusReason", "")

                if "FAILED" in status and "cancelled" not in reason.lower():
                    resource_type = event.get("ResourceType", "Unknown")
                    logical_id = event.get("LogicalResourceId", "Unknown")
                    return f"{resource_type} ({logical_id}): {reason}"

            return "Unknown failure reason"
        except Exception as e:
            return f"Error fetching failure reason: {str(e)}"

    def validate_template(self, template_path: str | Path) -> bool:
        """
        Validate a CloudFormation template.

        Args:
            template_path: Path to the template

        Returns:
            True if valid, raises TemplateValidationError otherwise
        """
        try:
            template_body = self._read_template(template_path)
            self.cf_client.validate_template(TemplateBody=template_body)
            return True
        except ClientError as e:
            raise TemplateValidationError(f"Template validation failed: {e.response['Error']['Message']}") from e
