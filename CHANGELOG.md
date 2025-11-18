# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.0.0] - 2025-11-17

### Added

- **Profile System v2.0**: Multi-deployment management from single machine
  - Manage multiple AWS accounts, regions, or organizations
  - Profile commands: `ccwb context list`, `ccwb context use`, `ccwb context show`
  - Config commands: `ccwb config validate`, `ccwb config export`, `ccwb config import`
  - Per-profile configuration files in `~/.ccwb/profiles/`
  - Active profile tracking with easy switching
  - Common use cases: production vs development, multi-region, multi-tenant
- **Authenticated Landing Page Distribution**: Enterprise-grade package distribution
  - IdP-gated self-service download portal (Okta/Azure AD/Auth0/Cognito)
  - Platform detection with automatic OS recommendation
  - Custom domain support with ACM certificates
  - ALB access logs for audit trail
  - Lambda-generated presigned URLs (1-hour expiry)
  - CloudFormation template: `landing-page-distribution.yaml` (1,038 lines)
- **Distribution Options**: Three methods for sharing packages
  - Manual sharing: Zip dist/ folder, share via email/internal file sharing
  - Presigned S3 URLs: Time-limited URLs (configurable 1-168 hours)
  - Landing page: Self-service portal with IdP authentication
- **QUICK_START.md**: Comprehensive deployment walkthrough (301 lines)
  - Step-by-step deployment instructions
  - Platform build requirements
  - Distribution method comparison
  - Basic troubleshooting
- **Profile Documentation**: Complete documentation for profile system
  - README section explaining profiles and use cases
  - CLI_REFERENCE section with all 7 profile commands
  - Migration notes for v1.x users

### Changed

- **Configuration Location** (BREAKING): Config moved from `source/.ccwb-config/` to `~/.ccwb/`
  - Automatic migration on first run
  - Timestamped backup created: `config.json.backup.YYYYMMDD_HHMMSS`
  - Profile names and active profile preserved
  - No manual steps required
- **Configuration Schema** (BREAKING): Schema version 1.0 → 2.0
  - Single config file → per-profile files
  - Profile stored in `~/.ccwb/profiles/<profile-name>.json`
  - Active profile tracked in `~/.ccwb/config.json`
- **README Refactored**: Focused on architecture and decision-making (575 → 280 lines, 51% reduction)
  - Clear distinction: IdP integration (NOT AWS SSO/IAM Identity Center)
  - Removed deployment steps (→ QUICK_START.md)
  - Removed end user sections (IT admin focus)
  - New "What Gets Deployed" section with infrastructure overview
  - Distribution options include manual sharing (0 minutes setup)
  - Prerequisites split: "For Deployment" and "For End Users"
  - Monitoring section reorganized by metrics categories
- **Distribution Configuration**: `enable_distribution` → `distribution_type`
  - Options: `manual`, `presigned-s3`, `landing-page`
  - Configured during `ccwb init`
  - `ccwb distribute` command works for all automated types
- **Deploy Command**: Support for distribution stack deployment
  - `ccwb deploy distribution` deploys landing page infrastructure
  - Validates IdP configuration before deployment
  - Handles Cognito User Pool automatic client creation

### Migration

**Automatic Migration from v1.x:**
- Runs automatically on first `ccwb` command after upgrade
- Creates timestamped backup of existing config
- Migrates all profiles to new `~/.ccwb/profiles/` structure
- Preserves profile names, active profile, and all settings
- No manual intervention required

**Verification:**
```bash
ccwb context list     # Verify profiles migrated
ccwb context show     # Verify active profile preserved
```

**Rollback if needed:**
```bash
rm -rf ~/.ccwb
cp ~/.ccwb-config/config.json.backup.TIMESTAMP ~/.ccwb-config/config.json
```

### Security

- **Client Secret Storage**: IdP client secrets stored in AWS Secrets Manager
  - Cognito User Pool: Automatic secret storage via CloudFormation
  - Other IdPs: Manual secret entry during init, stored in Secrets Manager
- **ALB Access Logs**: Automatic S3 logging for landing page authentication
- **Presigned URL Expiration**: Configurable 1-168 hours (default 48 hours)
- **S3 Bucket Policies**: Least privilege access for distribution buckets

### Infrastructure

- **Landing Page Stack**: Complete ALB + Lambda + S3 infrastructure
  - Application Load Balancer with OIDC authentication
  - Lambda function for presigned URL generation
  - S3 bucket for package storage
  - Security groups and VPC integration
  - Optional custom domain with ACM certificate
- **Distribution Bucket**: Created for both presigned-s3 and landing-page
  - Lifecycle policies for object expiration
  - Versioning enabled
  - Server-side encryption

### Documentation

- **New Guides**:
  - QUICK_START.md: Complete deployment walkthrough
  - assets/docs/distribution/comparison.md: Distribution method comparison
  - assets/docs/distribution/deployment-guide.md: Landing page setup
- **Updated Guides**:
  - README.md: Refactored for clarity, IT admin focus
  - CLI_REFERENCE.md: Added profile management commands
  - DEPLOYMENT.md: Updated with distribution options
- **Provider Guides**: Landing page setup for all IdPs
  - Okta web application configuration
  - Azure AD app registration
  - Auth0 regular web application
  - Cognito User Pool web client (automated)

### Deprecation

- **Legacy Distribution Flag**: `enable_distribution` deprecated, use `distribution_type`
  - Migration logic handles legacy field automatically
  - No breaking change for existing deployments

## [1.1.4] - 2025-11-04

### Fixed

- **Auth0 OIDC provider URL format**: Fixed issuer validation failures during token exchange
  - Added trailing slash to Auth0 OIDC provider URL (`https://${Auth0Domain}/`)
  - Auth0's OIDC issuer includes trailing slash per OAuth 2.0 spec
  - Prevents "issuer mismatch" errors during Direct IAM federation
  - Updated CloudFormation template parameter documentation with supported domain formats

- **Auth0 session name sanitization**: Fixed AssumeRoleWithWebIdentity errors for Auth0 users
  - Auth0 uses pipe-delimited format in sub claims (e.g., `auth0|12345`)
  - AWS RoleSessionName regex `[\w+=,.@-]*` doesn't allow pipe characters
  - Automatically sanitize invalid characters to hyphens in session names
  - Prevents "Member must satisfy regular expression pattern" validation errors

- **Bedrock list permissions**: Fixed permission errors for model listing operations
  - Changed Resource from specific ARNs to `'*'` for list operations
  - Affects `ListFoundationModels`, `GetFoundationModel`, `GetFoundationModelAvailability`, `ListInferenceProfiles`, `GetInferenceProfile`
  - AWS Bedrock list operations require `Resource: '*'` per AWS IAM documentation
  - Applied fix to all provider templates (Auth0, Azure AD, Okta, Cognito User Pool)

- **Dashboard region configuration**: Fixed monitoring dashboards for multi-region deployments
  - Replaced hardcoded `us-east-1` with `${MetricsRegion}` parameter in log widgets
  - Deploy command now passes `MetricsRegion` parameter from `profile.aws_region`
  - Prevents `ResourceNotFoundException` for deployments outside us-east-1
  - Affects CloudWatch Logs Insights widgets in monitoring dashboard

### Changed

- **Code quality improvements**:
  - Moved `subprocess` import to module level in `deploy.py`
  - Fixed variable shadowing: `platform_choice` → `platform_name` in `package.py`

### Documentation

- Enhanced Auth0 setup documentation
  - Added comprehensive table of supported Auth0 domain formats (standard and regional)
  - Added troubleshooting section for AssumeRoleWithWebIdentity validation errors
  - Documented automatic handling of Auth0 pipe character issue
  - Added examples of valid and invalid domain formats
  - Clarified that https:// prefix and trailing slash are added automatically

## [1.1.3] - 2025-11-03

### Fixed

- **Azure AD tenant ID extraction**: Fixed deployment failures when using Azure AD provider with various URL formats
  - Regex pattern matching now extracts tenant GUID from multiple input formats
  - Supports full URLs (with/without /v2.0), just tenant ID, and with https:// prefix
  - Updated CloudFormation template to use correct Microsoft OIDC v2.0 endpoint (`login.microsoftonline.com/{tenant}/v2.0`)
  - Added documentation for supported Azure provider domain formats with comprehensive examples
  - Added troubleshooting section for "Parameter AzureTenantId failed to satisfy constraint" error

## [1.1.1] - 2025-10-09

### Added

- **Fast Credential Access**: Session mode now uses `~/.aws/credentials` for 99.7% performance improvement
  - Credentials file I/O methods with atomic writes
  - CLI flags: `--check-expiration` and `--refresh-if-needed`
  - Expiration tracking with 30-second safety buffer
  - ConfigParser-based INI file handling
- **Code Quality Infrastructure**: Ruff pre-commit hooks for automated linting
  - Auto-fix import ordering, spacing, and formatting
  - Consistent code style enforcement on commit
- **UX Improvements**: Enhanced package command
  - Interactive platform selection with questionary checkbox
  - Co-authorship preference prompt (opt-in, defaults to False)
  - `--build-verbose` flag for detailed build logging
  - Unique Docker image tags for reliable builds

### Changed

- **Session Storage Mode**: Now writes to `~/.aws/credentials` instead of custom cache files
  - Eliminates credential_process overhead (300ms → 1ms retrieval time)
  - Better credential persistence across terminal sessions
  - Standard AWS CLI tooling compatibility
  - Automatic upgrade for existing session mode users
- **Package Command**: Improved user interaction with interactive prompts

### Security

- **Atomic Writes**: Temp file + `os.replace()` pattern prevents credential file corruption
- **File Permissions**: Credentials file automatically set to 0600 (owner read/write only)
- **Fail-Safe Expiration**: Assumes expired on any error (security-first approach)

### Performance

- **Credential Retrieval**: 99.7% improvement for session mode (300ms → 1ms)
- **No Breaking Changes**: Keyring mode unchanged, session mode automatically upgraded

## [1.1.0] - 2025-09-30

### Added

- **Direct IAM Federation**: Alternative to Cognito Identity Pool for authentication (#32)
  - Support for Okta, Azure AD, Auth0, and Cognito User Pools
  - Session duration configurable up to 12 hours
  - Provider-specific CloudFormation templates
  - Automatic federation type detection
- **Claude Sonnet 4.5 Support**: Full support for the latest Claude Sonnet 4.5 model
  - US CRIS profile (us-east-1, us-east-2, us-west-1, us-west-2)
  - EU CRIS profile (8 European regions: Frankfurt, Zurich, Stockholm, Ireland, London, Paris, Milan, Spain)
  - Japan CRIS profile (Tokyo, Osaka)
  - Global CRIS profile (23 regions worldwide including North America, Europe, Asia Pacific, and South America)
- **Inference Profile Permissions**: Added bedrock:ListInferenceProfiles and bedrock:GetInferenceProfile (#33, #34)
- **CloudFormation Utilities**: New exception handling and CloudFormation helper utilities
- **Global Endpoint Support**: IAM policies now properly support global inference profile ARNs

### Changed

- **Module Rename**: `cognito_auth` → `credential_provider` (more accurate naming)
- **IAM Policy Structure**: Split IAM policy statements into separate regional and global statements
  - Regional resources use `aws:RequestedRegion` condition
  - Global resources have no region condition
- **Deploy Command**: Refactored deploy.py with improved error handling and provider template support
- **Region Configuration**: Init wizard now dynamically uses regions from model profiles instead of hardcoded fallbacks
- **CloudWatch Metrics**: Fixed Resource specification to use '\*' instead of Bedrock ARNs
- **Configuration Schema**: Added federation_type and federated_role_arn fields

### Fixed

- Global endpoint access now works correctly without region condition blocking
- CloudFormation error handling improved across all commands
- Region condition no longer incorrectly applied to regionless global endpoints
- Init process properly handles all CRIS profile regions for selected model

### Infrastructure

- 4 new provider-specific CloudFormation templates (Okta, Azure AD, Auth0, Cognito User Pool)
- Improved IAM role structure with provider-specific roles
- CloudFormation exception handling and utilities

### Documentation

- Updated README, ARCHITECTURE, DEPLOYMENT, and CLI_REFERENCE
- Clear explanations of both authentication methods
- Documented configuration options for all providers

## [1.0.0] - Previous Release

Initial release with enterprise authentication support.
