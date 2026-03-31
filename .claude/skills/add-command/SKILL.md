---
name: add-command
description: "Scaffold a new CLI command with boilerplate, registration, and test file. Use when the user wants to add a new ccwb command, create a new subcommand, or extend the CLI with new functionality."
user-invocable: true
argument-hint: "<command-name>"
---

# Add New CLI Command

Scaffold a complete new CLI command for the `ccwb` tool. Command name: $ARGUMENTS

## Steps

1. **Read existing command for reference** — pick one similar in complexity:
   ```
   source/claude_code_with_bedrock/cli/commands/status.py
   ```

2. **Create the command file** at:
   ```
   source/claude_code_with_bedrock/cli/commands/<name>.py
   ```

   Follow the Cleo pattern:
   - Class inherits from `cleo.commands.Command`
   - `name` and `description` class attributes
   - `arguments` and `options` for CLI args
   - `handle()` method with the command logic
   - Use `self.line()` for output, `rich` for formatting
   - Load config via the project's config module

3. **Register the command** in `source/claude_code_with_bedrock/cli/__init__.py`:
   - Import the command class
   - Add to the application's command list

4. **Create test file** at:
   ```
   source/tests/cli/commands/test_<name>.py
   ```

   Follow existing test patterns:
   - Mock boto3 clients
   - Mock config loading
   - Test happy path and error cases
   - Use `CommandTester` from cleo for CLI testing

5. **Verify** the command works:
   ```bash
   cd source && poetry run ccwb list
   cd source && poetry run pytest tests/cli/commands/test_<name>.py -v
   ```

6. **Remind the user** to update `CLI_REFERENCE.md` with the new command docs.
