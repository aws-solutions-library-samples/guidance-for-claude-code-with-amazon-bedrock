# Contributing Guidelines

Thank you for your interest in contributing to our project. Whether it's a bug report, new feature, correction, or additional
documentation, we greatly value feedback and contributions from our community.

Please read through this document before submitting any issues or pull requests to ensure we have all the necessary
information to effectively respond to your bug report or contribution.


## Reporting Bugs/Feature Requests

We welcome you to use the GitHub issue tracker to report bugs or suggest features.

When filing an issue, please check existing open, or recently closed, issues to make sure somebody else hasn't already
reported the issue. Please try to include as much information as you can. Details like these are incredibly useful:

* A reproducible test case or series of steps
* The version of our code being used
* Any modifications you've made relevant to the bug
* Anything unusual about your environment or deployment


## Contributing with Claude Code (AI-Assisted)

This repository is configured with Claude Code skills, agents, and hooks to help contributors of all skill levels. If you have [Claude Code](https://claude.ai/code) installed, you can use the following slash commands to get started quickly:

| Command | Description |
|---------|-------------|
| `/setup` | Set up your development environment (checks Python, installs dependencies, runs smoke tests) |
| `/validate` | Run the full validation suite: linting, formatting, CloudFormation validation, and smoke tests |
| `/test [path]` | Run tests with coverage and get plain-English explanations of any failures |
| `/troubleshoot [area]` | Diagnose common issues (areas: `env`, `auth`, `deploy`, `tests`) |
| `/add-command <name>` | Scaffold a new CLI command with boilerplate, registration, and test file |
| `/add-provider <name>` | Scaffold support for a new identity provider with CloudFormation template and docs |
| `/check-cfn [template]` | Deep-validate CloudFormation templates for common issues |

Three specialized agents are also available and will be used automatically when relevant:
- **cfn-expert** — CloudFormation template specialist (multi-partition patterns, IAM, cross-stack references)
- **auth-expert** — OIDC/OAuth2 authentication flow specialist
- **test-runner** — Test execution and failure analysis specialist

Automated hooks run in the background to help catch issues early:
- **Auto-validation** — After editing Python files, ruff checks run automatically. After editing CloudFormation templates, cfn-lint runs automatically.
- **Config protection** — Warnings are surfaced before editing critical files like `models.py` or `config.py`.

Path-specific rules in `.claude/rules/` provide contextual guidance when working on CloudFormation templates, CLI commands, tests, the credential provider, or model configuration.


## Contributing via Pull Requests
Contributions via pull requests are much appreciated. Before sending us a pull request, please ensure that:

1. You are working against the latest source on the *main* branch.
2. You check existing open, and recently merged, pull requests to make sure someone else hasn't addressed the problem already.
3. You open an issue to discuss any significant work - we would hate for your time to be wasted.

To send us a pull request, please:

1. Fork the repository.
2. Modify the source; please focus on the specific change you are contributing. If you also reformat all the code, it will be hard for us to focus on your change.
3. Ensure local tests pass. (Tip: use `/validate` in Claude Code to run all checks at once.)
4. If your change warrants a version bump, update **both** `source/pyproject.toml` and `CHANGELOG.md` in the same PR.
5. Commit to your fork using clear commit messages.
6. Send us a pull request, answering any default questions in the pull request interface.
7. Pay attention to any automated CI failures reported in the pull request, and stay involved in the conversation.

GitHub provides additional document on [forking a repository](https://help.github.com/articles/fork-a-repo/) and
[creating a pull request](https://help.github.com/articles/creating-a-pull-request/).


## Finding contributions to work on
Looking at the existing issues is a great way to find something to contribute on. As our projects, by default, use the default GitHub issue labels (enhancement/bug/duplicate/help wanted/invalid/question/wontfix), looking at any 'help wanted' issues is a great place to start.


## Code of Conduct
This project has adopted the [Amazon Open Source Code of Conduct](https://aws.github.io/code-of-conduct).
For more information see the [Code of Conduct FAQ](https://aws.github.io/code-of-conduct-faq) or contact
opensource-codeofconduct@amazon.com with any additional questions or comments.


## Security issue notifications
If you discover a potential security issue in this project we ask that you notify AWS/Amazon Security via our [vulnerability reporting page](http://aws.amazon.com/security/vulnerability-reporting/). Please do **not** create a public github issue.


## Licensing

See the [LICENSE](LICENSE) file for our project's licensing. We will ask you to confirm the licensing of your contribution.