#!/bin/bash
# ABOUTME: Interactive deployment script for Cognito User Pool with optional custom domain
# ABOUTME: Supports both interactive and non-interactive modes for flexible deployment

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Parse arguments
STACK_NAME=""
REGION=""
CUSTOM_DOMAIN=""
HOSTED_ZONE_ID=""
USER_POOL_NAME=""
DOMAIN_PREFIX=""

while [[ $# -gt 0 ]]; do
  case $1 in
    --stack-name)
      STACK_NAME="$2"
      shift 2
      ;;
    --region)
      REGION="$2"
      shift 2
      ;;
    --custom-domain)
      CUSTOM_DOMAIN="$2"
      shift 2
      ;;
    --hosted-zone-id)
      HOSTED_ZONE_ID="$2"
      shift 2
      ;;
    --user-pool-name)
      USER_POOL_NAME="$2"
      shift 2
      ;;
    --domain-prefix)
      DOMAIN_PREFIX="$2"
      shift 2
      ;;
    -h|--help)
      cat << EOF
Deploy Cognito User Pool for Claude Code with Bedrock

Usage:
  Interactive mode:
    $0

  Non-interactive mode:
    $0 --stack-name <name> --region <region> [options]

Options:
  --stack-name <name>         CloudFormation stack name
  --region <region>           AWS region for deployment
  --custom-domain <domain>    Optional custom domain (e.g., auth.3pmod.dev)
  --hosted-zone-id <id>       Route 53 Hosted Zone ID (required with --custom-domain)
  --user-pool-name <name>     Cognito User Pool name (defaults to stack name)
  --domain-prefix <prefix>    Domain prefix for default domain (defaults to stack name)
  -h, --help                  Show this help message

Examples:
  # Interactive mode
  $0

  # Default Cognito domain
  $0 --stack-name my-cognito --region us-east-1

  # Custom domain in us-east-1
  $0 --stack-name my-cognito --region us-east-1 \\
     --custom-domain auth.example.com --hosted-zone-id Z123ABC

  # Custom domain in different region
  $0 --stack-name my-cognito --region us-west-2 \\
     --custom-domain auth.example.com --hosted-zone-id Z123ABC
EOF
      exit 0
      ;;
    *)
      echo "Unknown option: $1"
      echo "Use --help for usage information"
      exit 1
      ;;
  esac
done

# Function to prompt for input
prompt_input() {
  local prompt="$1"
  local default="$2"
  local result

  if [ -n "$default" ]; then
    read -p "$prompt [$default]: " result
    echo "${result:-$default}"
  else
    read -p "$prompt: " result
    echo "$result"
  fi
}

# Function to prompt yes/no
prompt_yn() {
  local prompt="$1"
  local default="$2"
  local result

  if [ "$default" = "y" ]; then
    read -p "$prompt [Y/n]: " result
    result="${result:-y}"
  else
    read -p "$prompt [y/N]: " result
    result="${result:-n}"
  fi

  [[ "$result" =~ ^[Yy] ]]
}

# Interactive mode if no parameters provided
if [ -z "$STACK_NAME" ] && [ -z "$REGION" ]; then
  echo "╭────────────────────────────────────────────────────────────╮"
  echo "│  Cognito User Pool Deployment for Claude Code with Bedrock │"
  echo "╰────────────────────────────────────────────────────────────╯"
  echo ""

  # Get current AWS account and region
  CURRENT_ACCOUNT=$(aws sts get-caller-identity --query Account --output text 2>/dev/null || echo "unknown")
  CURRENT_REGION=$(aws configure get region 2>/dev/null || echo "us-east-1")

  echo "Current AWS Account: $CURRENT_ACCOUNT"
  echo ""

  # Stack name
  STACK_NAME=$(prompt_input "Stack name" "claude-code-cognito")

  # Region
  REGION=$(prompt_input "AWS Region" "$CURRENT_REGION")

  # User pool name
  USER_POOL_NAME=$(prompt_input "User Pool name" "$STACK_NAME")

  # Custom domain
  echo ""
  if prompt_yn "Use custom domain?" "n"; then
    CUSTOM_DOMAIN=$(prompt_input "Custom domain (e.g., auth.example.com)" "")

    if [ -n "$CUSTOM_DOMAIN" ]; then
      # Try to auto-detect hosted zone
      DOMAIN_PARTS=(${CUSTOM_DOMAIN//./ })
      if [ ${#DOMAIN_PARTS[@]} -ge 2 ]; then
        # Extract root domain (last 2 parts) - portable array indexing
        PARTS_COUNT=${#DOMAIN_PARTS[@]}
        SECOND_LAST_IDX=$((PARTS_COUNT - 2))
        LAST_IDX=$((PARTS_COUNT - 1))
        ROOT_DOMAIN="${DOMAIN_PARTS[$SECOND_LAST_IDX]}.${DOMAIN_PARTS[$LAST_IDX]}"

        echo ""
        echo "Looking for Route 53 hosted zone for $ROOT_DOMAIN..."
        FOUND_ZONE=$(aws route53 list-hosted-zones \
          --query "HostedZones[?Name=='${ROOT_DOMAIN}.'].Id" \
          --output text 2>/dev/null | sed 's/\/hostedzone\///')

        if [ -n "$FOUND_ZONE" ]; then
          echo "Found hosted zone: $FOUND_ZONE"
          HOSTED_ZONE_ID=$(prompt_input "Route 53 Hosted Zone ID" "$FOUND_ZONE")
        else
          echo "No hosted zone found for $ROOT_DOMAIN"
          HOSTED_ZONE_ID=$(prompt_input "Route 53 Hosted Zone ID" "")
        fi
      else
        HOSTED_ZONE_ID=$(prompt_input "Route 53 Hosted Zone ID" "")
      fi
    fi
  else
    DOMAIN_PREFIX=$(prompt_input "Domain prefix for Cognito domain" "$STACK_NAME")
  fi

  # Confirm
  echo ""
  echo "╭─── Configuration Summary ───╮"
  echo "│ Stack Name:    $STACK_NAME"
  echo "│ Region:        $REGION"
  echo "│ User Pool:     $USER_POOL_NAME"
  if [ -n "$CUSTOM_DOMAIN" ]; then
    echo "│ Custom Domain: $CUSTOM_DOMAIN"
    echo "│ Hosted Zone:   $HOSTED_ZONE_ID"
  else
    echo "│ Domain Prefix: $DOMAIN_PREFIX"
    echo "│ Full Domain:   ${DOMAIN_PREFIX}.auth.${REGION}.amazoncognito.com"
  fi
  echo "╰─────────────────────────────╯"
  echo ""

  if ! prompt_yn "Proceed with deployment?" "y"; then
    echo "Deployment cancelled"
    exit 0
  fi

  echo ""
fi

# Validate required parameters
if [ -z "$STACK_NAME" ] || [ -z "$REGION" ]; then
  echo "Error: Missing required parameters"
  echo "Use --help for usage information"
  exit 1
fi

# Set defaults
USER_POOL_NAME=${USER_POOL_NAME:-$STACK_NAME}

# Default domain prefix - avoid reserved word "cognito"
if [ -z "$DOMAIN_PREFIX" ]; then
  # Remove "cognito" from stack name if present
  DOMAIN_PREFIX=$(echo "$STACK_NAME" | sed 's/cognito/auth/gi')
fi

# Validate domain prefix doesn't contain "cognito" (reserved word)
if [ -n "$DOMAIN_PREFIX" ] && echo "$DOMAIN_PREFIX" | grep -qi "cognito"; then
  echo "✗ Error: Domain prefix cannot contain the reserved word 'cognito'"
  echo "  Current value: $DOMAIN_PREFIX"
  echo "  Please use --domain-prefix with a different value"
  exit 1
fi

# Determine if custom domain is being used
if [ -n "$CUSTOM_DOMAIN" ]; then
  USE_CUSTOM_DOMAIN="true"

  if [ -z "$HOSTED_ZONE_ID" ]; then
    echo "Error: --hosted-zone-id is required when using --custom-domain"
    exit 1
  fi

  # Always use two-stack approach for custom domains
  # Certificate stack is always in us-east-1 (Cognito requirement)
  echo "→ Custom domain requires certificate in us-east-1"
  echo "→ Using two-stack deployment approach..."

  # Extract parent domain from custom domain (e.g., "3pmod.dev" from "auth.3pmod.dev")
  DOMAIN_PARTS=(${CUSTOM_DOMAIN//./ })
  PARTS_COUNT=${#DOMAIN_PARTS[@]}
  SECOND_LAST_IDX=$((PARTS_COUNT - 2))
  LAST_IDX=$((PARTS_COUNT - 1))
  PARENT_DOMAIN="${DOMAIN_PARTS[$SECOND_LAST_IDX]}.${DOMAIN_PARTS[$LAST_IDX]}"

  echo "→ Checking parent domain: $PARENT_DOMAIN"

  # Check if parent domain has an A record
  PARENT_A_RECORD=$(aws route53 list-resource-record-sets \
    --hosted-zone-id "$HOSTED_ZONE_ID" \
    --query "ResourceRecordSets[?Name=='${PARENT_DOMAIN}.' && Type=='A']" \
    --output json)

  if [ "$PARENT_A_RECORD" = "[]" ]; then
    echo "⚠ Parent domain has no A record - will create placeholder"
    CREATE_PARENT_RECORD="true"
  else
    echo "✓ Parent domain has A record"
    CREATE_PARENT_RECORD="false"
  fi

  CERT_STACK_NAME="${STACK_NAME}-cert"

  # Deploy or update certificate stack
  if aws cloudformation describe-stacks --region us-east-1 --stack-name "$CERT_STACK_NAME" &>/dev/null; then
    echo "→ Updating certificate stack in us-east-1..."
  else
    echo "→ Creating certificate stack in us-east-1..."
  fi

  aws cloudformation deploy \
    --region us-east-1 \
    --template-file "$SCRIPT_DIR/../infrastructure/cognito-custom-domain-cert.yaml" \
    --stack-name "$CERT_STACK_NAME" \
    --parameter-overrides \
      CustomDomainName="$CUSTOM_DOMAIN" \
      Route53HostedZoneId="$HOSTED_ZONE_ID" \
      ParentDomainName="$PARENT_DOMAIN" \
      CreateParentDomainRecord="$CREATE_PARENT_RECORD" \
    --no-fail-on-empty-changeset

  if [ $? -ne 0 ]; then
    echo "✗ Failed to deploy certificate stack"
    exit 1
  fi

  echo "✓ Certificate stack deployed successfully"

  # Get certificate ARN
  CERT_ARN=$(aws cloudformation describe-stacks \
    --region us-east-1 \
    --stack-name "$CERT_STACK_NAME" \
    --query 'Stacks[0].Outputs[?OutputKey==`CertificateArn`].OutputValue' \
    --output text)

  if [ -z "$CERT_ARN" ]; then
    echo "✗ Failed to get certificate ARN from stack outputs"
    exit 1
  fi

  # Verify certificate is issued
  CERT_STATUS=$(aws acm describe-certificate \
    --certificate-arn "$CERT_ARN" \
    --region us-east-1 \
    --query 'Certificate.Status' \
    --output text)

  echo "→ Certificate status: $CERT_STATUS"

  if [ "$CERT_STATUS" != "ISSUED" ]; then
    echo "⚠ Warning: Certificate is not yet issued. Cognito deployment may fail."
    echo "⚠ Wait for DNS validation to complete, then re-run this script."
  fi

  echo "→ Using certificate: $CERT_ARN"

  CERT_PARAM="CertificateArn=$CERT_ARN"
else
  USE_CUSTOM_DOMAIN="false"
  CERT_PARAM=""
fi

# Deploy Cognito stack
echo ""
echo "→ Deploying Cognito User Pool stack..."

PARAMS="UserPoolName=$USER_POOL_NAME DomainPrefix=$DOMAIN_PREFIX UseCustomDomain=$USE_CUSTOM_DOMAIN"

if [ "$USE_CUSTOM_DOMAIN" = "true" ]; then
  PARAMS="$PARAMS CustomDomainName=$CUSTOM_DOMAIN $CERT_PARAM Route53HostedZoneId=$HOSTED_ZONE_ID"
fi

aws cloudformation deploy \
  --region "$REGION" \
  --template-file "$SCRIPT_DIR/../infrastructure/cognito-user-pool-setup.yaml" \
  --stack-name "$STACK_NAME" \
  --parameter-overrides $PARAMS \
  --capabilities CAPABILITY_IAM

echo ""
echo "✓ Cognito User Pool deployed successfully"
echo ""

# Display outputs
echo "╭─── Claude Code Configuration ───╮"
aws cloudformation describe-stacks \
  --region "$REGION" \
  --stack-name "$STACK_NAME" \
  --query 'Stacks[0].Outputs[?OutputKey==`ClaudeCodeConfiguration`].OutputValue' \
  --output text

# If custom domain, show DNS configuration status
if [ "$USE_CUSTOM_DOMAIN" = "true" ]; then
  echo ""
  echo "╭─── Custom Domain Configured ───╮"

  # Wait a moment for domain to be available
  sleep 2

  echo "✓ Route 53 A record created automatically"
  echo "✓ DNS: $CUSTOM_DOMAIN → CloudFront"
  echo ""
  echo "Note: DNS propagation may take a few minutes"
  echo ""
fi

echo ""
echo "Next steps:"
echo "1. Run: ccwb init"
echo "2. Use the configuration values shown above"
echo "3. Deploy the rest of the infrastructure: ccwb deploy"
echo ""
