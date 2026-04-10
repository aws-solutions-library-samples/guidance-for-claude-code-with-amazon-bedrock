# Project Structure

```
.
├── source/                                  # All Python source code
│   ├── pyproject.toml                       # Poetry config, dependencies, tool settings
│   ├── claude_code_with_bedrock/            # Main CLI application package
│   │   ├── cli/                             # CLI entry point and command modules
│   │   │   ├── commands/                    # Individual ccwb subcommands
│   │   │   └── utils/                       # CLI helper utilities
│   │   ├── config.py                        # Profile & configuration management
│   │   ├── models.py                        # Bedrock model definitions & inference profiles
│   │   ├── validators.py                    # Input validation logic
│   │   ├── quota_policies.py                # Per-user token quota enforcement
│   │   ├── migration.py                     # Config migration (v1 → v2)
│   │   └── utils/                           # Shared utility modules
│   ├── credential_provider/                 # OIDC credential process (standalone executable)
│   ├── otel_helper/                         # OpenTelemetry metrics helper
│   └── tests/                               # Test suite
│       ├── cli/                             # CLI command tests
│       ├── conftest.py                      # Shared fixtures
│       ├── test_smoke.py                    # Quick smoke tests (run on pre-commit)
│       ├── test_config.py                   # Configuration tests
│       ├── test_models.py                   # Model definition tests
│       ├── test_cloudformation.py           # CFN template validation tests
│       └── ...                              # Other test modules
│
├── deployment/                              # AWS infrastructure
│   ├── infrastructure/                      # CloudFormation templates (YAML)
│   │   ├── bedrock-auth-{okta,azure,auth0,cognito-pool}.yaml  # IdP-specific auth stacks
│   │   ├── cognito-*.yaml                   # Cognito setup templates
│   │   ├── otel-collector.yaml              # OpenTelemetry monitoring stack
│   │   ├── claude-code-dashboard.yaml       # CloudWatch dashboard
│   │   ├── quota-monitoring.yaml            # Token quota DynamoDB + Lambda
│   │   ├── analytics-pipeline.yaml          # S3 data lake + Athena
│   │   ├── landing-page-distribution.yaml   # Self-service download portal
│   │   ├── lambda-functions/                # Lambda source for CFN templates
│   │   │   ├── inference_profile_provisioner/  # Creates per-user inference profiles (server-side)
│   │   │   ├── quota_enforcer/              # Tags profiles enabled/disabled based on quota
│   │   │   └── bedrock_metrics_bridge/      # Bridges Bedrock CW metrics to OTEL log group
│   │   └── ...                              # Other infra templates
│   └── scripts/                             # Deployment helper scripts
│
├── assets/
│   ├── docs/                                # Extended documentation
│   │   ├── ARCHITECTURE.md                  # System design & auth flow decisions
│   │   ├── DEPLOYMENT.md                    # Advanced deployment options
│   │   ├── CLI_REFERENCE.md                 # Full ccwb command reference
│   │   ├── MONITORING.md                    # OpenTelemetry setup guide
│   │   ├── ANALYTICS.md                     # Athena SQL queries on metrics
│   │   ├── QUOTA_MONITORING.md              # Token quota controls
│   │   ├── providers/                       # IdP-specific setup guides
│   │   └── distribution/                    # Distribution method guides
│   ├── claude-code-plugins/                 # Example Claude Code plugins
│   └── images/                              # Architecture diagrams
│
├── README.md                                # Main project overview (IT admin audience)
├── QUICK_START.md                           # Step-by-step deployment walkthrough
├── CONTRIBUTING.md                          # Contribution guidelines
├── CHANGELOG.md                             # Release history (Keep a Changelog format)
└── .pre-commit-config.yaml                  # Pre-commit hook definitions
```

## Key Conventions

- The `source/` directory is the Poetry project root — all `poetry run` commands execute from there
- CLI entry points: `ccwb` and `claude-code-with-bedrock` (both point to `claude_code_with_bedrock.cli:main`)
- `credential_provider` is a separate package — it ships as a standalone executable for end users
- CloudFormation templates live in `deployment/infrastructure/` and are YAML-only
- Documentation is split: `README.md` / `QUICK_START.md` at root for quick access, detailed guides in `assets/docs/`
- Tests mirror source structure — `source/tests/cli/` tests CLI commands, other test files cover core modules
- Inference profile provisioning is Lambda-based (not client-direct) — the `InferenceProfileProvisionerFunction` is the sole principal with `bedrock:CreateInferenceProfile` / `bedrock:TagResource`
- The OTEL collector (`otel-collector.yaml`) is deprecated for token tracking — kept for backward compatibility; Bedrock CloudWatch metrics are now the authoritative token source
- `CHANGES-INFERENCEPROFILE.md` at repo root documents the full migration design from OTEL to inference profiles, including IAM changes, session tag setup, and server-side quota enforcement
