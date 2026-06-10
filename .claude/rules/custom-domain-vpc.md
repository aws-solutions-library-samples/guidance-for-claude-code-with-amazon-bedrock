# Custom Domain VPC

## Rule
- OTEL HTTPS listener needs custom domain + ACM cert OR conditional
- Distribution landing page: handle None domain gracefully
- Don't require Route53 in same account
- "Use existing VPC" must read nested config correctly

## Why
Custom domains are optional but when present require proper certificate management. VPC configuration has nested structure that must be parsed correctly.

## Implementation
- Make OTEL HTTPS listener conditional on custom domain presence
- Handle `None` domain values gracefully in landing pages
- Support Route53 hosted zones in different AWS accounts
- Parse nested VPC configuration structure correctly

## Examples
```yaml
# ✅ Correct - conditional HTTPS listener
Conditions:
  HasCustomDomain: !Not [!Equals [!Ref CustomDomainName, ""]]

Resources:
  HTTPSListener:
    Type: AWS::ElasticLoadBalancingV2::Listener
    Condition: HasCustomDomain
```

```python
# ✅ Correct - handle None domain
if profile.custom_domain:
    landing_page_url = f"https://{profile.custom_domain}"
else:
    landing_page_url = "https://default-domain.example.com"
```

## Related Issues
#55, #102, #120, #216, #286, #394