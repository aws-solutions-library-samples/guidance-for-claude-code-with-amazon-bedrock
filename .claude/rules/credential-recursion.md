# Credential Recursion

## Rule
credential-process is called BY the AWS SDK. Never use boto3 inside it (infinite recursion).

## Why
The credential process binary is invoked BY the AWS SDK to get credentials. If the binary itself calls an AWS API that triggers credential resolution, you get infinite recursion.

## Implementation
- Use direct HTTPS calls (not boto3) for token exchange
- Pre-resolve any AWS credentials needed inside the process
- Never import or use AWS SDK within credential process

## Examples
```python
# ✅ Correct - direct HTTPS call
import requests
response = requests.post(token_endpoint, data=token_data)

# ❌ Wrong - will cause infinite recursion
import boto3
sts = boto3.client('sts')  # This will call credential-process again!
```

## Related Issues
#58