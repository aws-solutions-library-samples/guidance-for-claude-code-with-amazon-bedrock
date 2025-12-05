# ABOUTME: Comprehensive smoke tests for entire codebase
# ABOUTME: Catches import errors, syntax errors, instantiation issues, and configuration problems

"""Comprehensive smoke tests to catch errors before commit."""

import importlib
import sys
from pathlib import Path

import pytest
from cleo.commands.command import Command


class TestCoreModuleImports:
    """Test that all core modules can be imported without errors."""

    @pytest.mark.parametrize(
        "module_path",
        [
            "claude_code_with_bedrock.config",
            "claude_code_with_bedrock.models",
            "claude_code_with_bedrock.quota_policies",
            "claude_code_with_bedrock.validators",
            "claude_code_with_bedrock.migration",
            "claude_code_with_bedrock.cli",
            "credential_provider",
        ],
    )
    def test_core_module_import(self, module_path):
        """Test that core modules can be imported without errors.

        This catches:
        - Syntax errors in core modules
        - Import errors (missing dependencies, circular imports)
        - Module-level exceptions
        """
        try:
            importlib.import_module(module_path)
        except Exception as e:
            pytest.fail(f"Failed to import {module_path}: {e}")

    def test_config_classes_instantiable(self):
        """Test that Config and Profile classes can be instantiated."""
        from claude_code_with_bedrock.config import Profile

        # Test Profile instantiation
        try:
            profile = Profile(
                name="test",
                provider_domain="test.okta.com",
                client_id="test-client",
                credential_storage="session",
                aws_region="us-east-1",
                identity_pool_name="test-pool",
            )
        except Exception as e:
            pytest.fail(f"Failed to instantiate Profile: {e}")

        # Verify basic attributes
        assert profile.name == "test"
        assert profile.aws_region == "us-east-1"

    def test_models_can_be_imported(self):
        """Test that all model classes can be imported."""
        from claude_code_with_bedrock.models import EnforcementMode, PolicyType

        # Verify enums have expected values
        assert hasattr(EnforcementMode, "ALERT")
        assert hasattr(EnforcementMode, "BLOCK")
        assert hasattr(PolicyType, "USER")
        assert hasattr(PolicyType, "GROUP")
        assert hasattr(PolicyType, "DEFAULT")

    def test_quota_policy_manager_importable(self):
        """Test that QuotaPolicyManager can be imported and has expected interface."""
        from claude_code_with_bedrock.quota_policies import QuotaPolicyManager

        # Verify class has expected methods
        assert hasattr(QuotaPolicyManager, "create_policy")
        assert hasattr(QuotaPolicyManager, "update_policy")
        assert hasattr(QuotaPolicyManager, "get_policy")
        assert hasattr(QuotaPolicyManager, "delete_policy")
        assert hasattr(QuotaPolicyManager, "list_policies")
        assert hasattr(QuotaPolicyManager, "get_usage_summary")


class TestLambdaFunctions:
    """Test that Lambda function code can be imported."""

    @pytest.mark.parametrize(
        "lambda_module",
        [
            "quota_monitor.quota_monitor",
            "metrics_aggregator.metrics_aggregator",
        ],
    )
    def test_lambda_import(self, lambda_module):
        """Test that Lambda function modules can be imported.

        Lambda functions are in the deployment/lambda/ directory.
        """
        # Add lambda directory to path temporarily
        lambda_dir = Path(__file__).parent.parent.parent.parent / "deployment" / "lambda"
        if lambda_dir.exists():
            sys.path.insert(0, str(lambda_dir))
            try:
                importlib.import_module(lambda_module)
            except Exception as e:
                pytest.fail(f"Failed to import Lambda {lambda_module}: {e}")
            finally:
                sys.path.remove(str(lambda_dir))


class TestCommandImports:
    """Test that all CLI commands can be imported and instantiated."""

    @pytest.mark.parametrize(
        "module_path,command_classes",
        [
            ("claude_code_with_bedrock.cli.commands.init", ["InitCommand"]),
            ("claude_code_with_bedrock.cli.commands.deploy", ["DeployCommand"]),
            ("claude_code_with_bedrock.cli.commands.destroy", ["DestroyCommand"]),
            ("claude_code_with_bedrock.cli.commands.status", ["StatusCommand"]),
            ("claude_code_with_bedrock.cli.commands.cleanup", ["CleanupCommand"]),
            ("claude_code_with_bedrock.cli.commands.package", ["PackageCommand"]),
            ("claude_code_with_bedrock.cli.commands.distribute", ["DistributeCommand"]),
            ("claude_code_with_bedrock.cli.commands.test", ["TestCommand"]),
            (
                "claude_code_with_bedrock.cli.commands.context",
                [
                    "ContextListCommand",
                    "ContextCurrentCommand",
                    "ContextUseCommand",
                    "ContextShowCommand",
                    "ConfigValidateCommand",
                    "ConfigExportCommand",
                    "ConfigImportCommand",
                ],
            ),
            ("claude_code_with_bedrock.cli.commands.builds", ["BuildsCommand"]),
            (
                "claude_code_with_bedrock.cli.commands.quota",
                [
                    "QuotaSetUserCommand",
                    "QuotaSetGroupCommand",
                    "QuotaSetDefaultCommand",
                    "QuotaListCommand",
                    "QuotaDeleteCommand",
                    "QuotaShowCommand",
                    "QuotaUsageCommand",
                    "QuotaUnblockCommand",
                    "QuotaExportCommand",
                    "QuotaImportCommand",
                ],
            ),
        ],
    )
    def test_command_import(self, module_path, command_classes):
        """Test that command modules can be imported without errors.

        This catches:
        - Syntax errors
        - Import errors
        - Module-level exceptions
        """
        try:
            module = importlib.import_module(module_path)
        except Exception as e:
            pytest.fail(f"Failed to import {module_path}: {e}")

        # Verify all expected command classes exist
        for class_name in command_classes:
            assert hasattr(module, class_name), f"{class_name} not found in {module_path}"

    @pytest.mark.parametrize(
        "module_path,command_class",
        [
            ("claude_code_with_bedrock.cli.commands.init", "InitCommand"),
            ("claude_code_with_bedrock.cli.commands.deploy", "DeployCommand"),
            ("claude_code_with_bedrock.cli.commands.destroy", "DestroyCommand"),
            ("claude_code_with_bedrock.cli.commands.status", "StatusCommand"),
            ("claude_code_with_bedrock.cli.commands.cleanup", "CleanupCommand"),
            ("claude_code_with_bedrock.cli.commands.package", "PackageCommand"),
            ("claude_code_with_bedrock.cli.commands.distribute", "DistributeCommand"),
            ("claude_code_with_bedrock.cli.commands.test", "TestCommand"),
            ("claude_code_with_bedrock.cli.commands.context", "ContextListCommand"),
            ("claude_code_with_bedrock.cli.commands.context", "ContextCurrentCommand"),
            ("claude_code_with_bedrock.cli.commands.context", "ContextUseCommand"),
            ("claude_code_with_bedrock.cli.commands.context", "ContextShowCommand"),
            ("claude_code_with_bedrock.cli.commands.context", "ConfigValidateCommand"),
            ("claude_code_with_bedrock.cli.commands.context", "ConfigExportCommand"),
            ("claude_code_with_bedrock.cli.commands.context", "ConfigImportCommand"),
            ("claude_code_with_bedrock.cli.commands.builds", "BuildsCommand"),
            ("claude_code_with_bedrock.cli.commands.quota", "QuotaSetUserCommand"),
            ("claude_code_with_bedrock.cli.commands.quota", "QuotaSetGroupCommand"),
            ("claude_code_with_bedrock.cli.commands.quota", "QuotaSetDefaultCommand"),
            ("claude_code_with_bedrock.cli.commands.quota", "QuotaListCommand"),
            ("claude_code_with_bedrock.cli.commands.quota", "QuotaDeleteCommand"),
            ("claude_code_with_bedrock.cli.commands.quota", "QuotaShowCommand"),
            ("claude_code_with_bedrock.cli.commands.quota", "QuotaUsageCommand"),
            ("claude_code_with_bedrock.cli.commands.quota", "QuotaUnblockCommand"),
            ("claude_code_with_bedrock.cli.commands.quota", "QuotaExportCommand"),
            ("claude_code_with_bedrock.cli.commands.quota", "QuotaImportCommand"),
        ],
    )
    def test_command_instantiation(self, module_path, command_class):
        """Test that command classes can be instantiated without errors.

        This catches:
        - Invalid argument() calls (e.g., unsupported 'required' parameter)
        - Invalid option() calls
        - Class-level definition errors
        - Missing required class attributes
        """
        try:
            module = importlib.import_module(module_path)
            command_cls = getattr(module, command_class)
            command_instance = command_cls()
        except TypeError as e:
            pytest.fail(
                f"Failed to instantiate {command_class} from {module_path}: {e}\n"
                f"This usually indicates invalid argument() or option() definitions."
            )
        except Exception as e:
            pytest.fail(f"Failed to instantiate {command_class} from {module_path}: {e}")

        # Verify it's actually a Command
        assert isinstance(command_instance, Command), f"{command_class} is not a Command subclass"

    def test_cli_main_import(self):
        """Test that the main CLI module can be imported.

        This ensures the entire CLI application can be loaded,
        which is what happens when a user runs 'ccwb' command.
        """
        try:
            from claude_code_with_bedrock.cli import create_application

            app = create_application()
            assert app is not None
        except Exception as e:
            pytest.fail(f"Failed to import main CLI module: {e}")

    def test_all_quota_commands_registered(self):
        """Test that all quota commands are properly defined.

        This is a comprehensive check for the quota command module
        since it's the most complex with multiple subcommands.
        """
        from claude_code_with_bedrock.cli.commands.quota import (
            QuotaDeleteCommand,
            QuotaExportCommand,
            QuotaImportCommand,
            QuotaListCommand,
            QuotaSetDefaultCommand,
            QuotaSetGroupCommand,
            QuotaSetUserCommand,
            QuotaShowCommand,
            QuotaUnblockCommand,
            QuotaUsageCommand,
        )

        # Verify each command has required attributes
        quota_commands = [
            QuotaSetUserCommand,
            QuotaSetGroupCommand,
            QuotaSetDefaultCommand,
            QuotaListCommand,
            QuotaDeleteCommand,
            QuotaShowCommand,
            QuotaUsageCommand,
            QuotaUnblockCommand,
            QuotaExportCommand,
            QuotaImportCommand,
        ]

        for cmd_class in quota_commands:
            # Test instantiation
            try:
                cmd = cmd_class()
            except Exception as e:
                pytest.fail(f"Failed to instantiate {cmd_class.__name__}: {e}")

            # Verify required attributes
            assert hasattr(cmd, "name"), f"{cmd_class.__name__} missing 'name' attribute"
            assert hasattr(cmd, "description"), f"{cmd_class.__name__} missing 'description' attribute"
            assert hasattr(cmd, "handle"), f"{cmd_class.__name__} missing 'handle' method"

            # Verify name is not empty
            assert cmd.name, f"{cmd_class.__name__} has empty name"


class TestCommandDefinitions:
    """Test command argument and option definitions."""

    def test_quota_export_argument_syntax(self):
        """Test that quota export command has properly defined optional argument.

        This specifically tests the bug that was fixed: using 'required=False'
        instead of the '?' suffix for optional arguments.
        """
        from claude_code_with_bedrock.cli.commands.quota import QuotaExportCommand

        # Should not raise TypeError during instantiation
        cmd = QuotaExportCommand()

        # Verify the command has arguments defined
        assert hasattr(cmd, "arguments"), "QuotaExportCommand missing arguments"

        # Verify arguments is a list
        assert isinstance(cmd.arguments, list), "arguments should be a list"

    def test_all_commands_have_valid_definitions(self):
        """Test that all commands have valid argument and option definitions.

        This catches common definition errors across all commands.
        """
        from claude_code_with_bedrock.cli.commands import (
            builds,
            cleanup,
            context,
            deploy,
            destroy,
            distribute,
            init,
            package,
            quota,
            status,
            test,
        )

        modules = [builds, cleanup, context, deploy, destroy, distribute, init, package, quota, status, test]

        for module in modules:
            # Get all Command subclasses from the module
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if (
                    isinstance(attr, type)
                    and issubclass(attr, Command)
                    and attr is not Command
                    and attr_name.endswith("Command")
                ):
                    # Try to instantiate
                    try:
                        cmd = attr()
                    except Exception as e:
                        pytest.fail(
                            f"Failed to instantiate {attr_name} from {module.__name__}: {e}\n"
                            f"Check for invalid argument() or option() parameters."
                        )

                    # Basic validation
                    if hasattr(cmd, "arguments"):
                        assert isinstance(cmd.arguments, list), f"{attr_name}.arguments should be a list"

                    if hasattr(cmd, "options"):
                        assert isinstance(cmd.options, list), f"{attr_name}.options should be a list"
