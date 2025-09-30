# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
