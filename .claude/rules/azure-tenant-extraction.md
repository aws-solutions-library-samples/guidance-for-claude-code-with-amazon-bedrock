# Azure Tenant Extraction

## Rule
Never pass raw `profile.*_domain` as CloudFormation parameter. Always use `_extract_azure_tenant_id()` helper.

## Why
Provider domains contain full URLs (e.g., `login.microsoftonline.com/tenant-id/v2.0`). CloudFormation parameters often expect just the tenant GUID or bare domain.

## Examples
```python
# ❌ Wrong - passes full URL
f"AzureTenantId={profile.distribution_idp_domain}"

# ✅ Correct - extracts tenant GUID
f"AzureTenantId={_extract_azure_tenant_id(profile.distribution_idp_domain)}"
```

## Related Issues
#351, #52, #53