# Region Availability

## Rule
- ELB account IDs differ by region
- CodeBuild Windows not in all regions
- Bedrock models vary by region
- Never hardcode us-east-1 without fallback

## Why
AWS services and features have different availability across regions. Hardcoding region-specific values breaks deployments in other regions.

## Implementation
- Use region-specific ELB access log account IDs
- Check CodeBuild Windows container availability before deployment
- Use `AllowedBedrockRegions` parameter for model availability
- Always provide configurable region fallbacks

## Examples
```yaml
# ✅ Correct - region-specific ELB account ID
Mappings:
  ELBAccountIds:
    us-east-1: { AccountId: "127311923021" }
    us-west-2: { AccountId: "797873946194" }
    eu-west-1: { AccountId: "156460612806" }

# ❌ Wrong - hardcoded us-east-1 account ID
S3BucketPolicy:
  Principal: { AWS: "arn:aws:iam::127311923021:root" }
```

## Related Issues
#125, #187, #212, #213, #262, #354, #382