# ABOUTME: Custom exception classes for CloudFormation operations
# ABOUTME: Provides structured error handling for boto3 CloudFormation calls

"""Custom exceptions for CloudFormation operations."""


class CloudFormationError(Exception):
    """Base exception for all CloudFormation operations."""

    def __init__(self, message: str, stack_name: str = None):
        self.message = message
        self.stack_name = stack_name
        super().__init__(self.message)


class StackNotFoundError(CloudFormationError):
    """Raised when a stack does not exist."""

    pass


class StackRollbackError(CloudFormationError):
    """Raised when a stack is in ROLLBACK_COMPLETE state."""

    def __init__(self, message: str, stack_name: str = None):
        super().__init__(message, stack_name)
        self.recovery_action = f"Delete stack {stack_name} and retry"


class ResourceConflictError(CloudFormationError):
    """Raised when a resource already exists (e.g., LogGroup, S3 bucket)."""

    def __init__(self, message: str, resource_id: str = None, stack_name: str = None):
        super().__init__(message, stack_name)
        self.resource_id = resource_id

    def get_cleanup_command(self) -> str:
        """Get the AWS CLI command to clean up the conflicting resource."""
        if "LogGroup" in self.message:
            return f"aws logs delete-log-group --log-group-name {self.resource_id}"
        elif "Bucket" in self.message:
            return f"aws s3 rb s3://{self.resource_id} --force"
        return ""


class TemplateValidationError(CloudFormationError):
    """Raised when template validation fails."""

    pass


class PermissionError(CloudFormationError):
    """Raised when IAM permissions are insufficient."""

    def __init__(self, message: str, required_capability: str = None, stack_name: str = None):
        super().__init__(message, stack_name)
        self.required_capability = required_capability


class StackOperationInProgressError(CloudFormationError):
    """Raised when a stack operation is already in progress."""

    def __init__(self, message: str, current_operation: str = None, stack_name: str = None):
        super().__init__(message, stack_name)
        self.current_operation = current_operation


class StackDeleteFailedError(CloudFormationError):
    """Raised when stack deletion fails."""

    def __init__(self, message: str, retained_resources: list = None, stack_name: str = None):
        super().__init__(message, stack_name)
        self.retained_resources = retained_resources or []


class ParameterError(CloudFormationError):
    """Raised when stack parameters are invalid."""

    def __init__(self, message: str, parameter_name: str = None, stack_name: str = None):
        super().__init__(message, stack_name)
        self.parameter_name = parameter_name


class TimeoutError(CloudFormationError):
    """Raised when a stack operation times out."""

    def __init__(self, message: str, operation: str = None, stack_name: str = None):
        super().__init__(message, stack_name)
        self.operation = operation
