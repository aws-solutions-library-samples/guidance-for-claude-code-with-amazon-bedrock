# Stack Ordering

## Rule
Networking must deploy before distribution/monitoring. Never assume stack outputs exist — check and fail with clear error.

## Why
CloudFormation stack dependencies must be explicitly managed. Stacks that reference outputs from other stacks will fail if those dependencies aren't deployed first.

## Implementation
- Deploy networking stacks before any stacks that reference their outputs
- Check for required stack outputs before attempting to reference them
- Fail gracefully with clear error messages pointing to missing dependencies

## Examples
```python
# ✅ Correct - check dependencies
try:
    vpc_id = get_stack_output('networking-stack', 'VpcId')
    if not vpc_id:
        raise ValueError("VPC stack must be deployed first")
except StackNotFoundError:
    raise ValueError("Deploy networking stack before distribution stack")

# ❌ Wrong - assumes output exists
vpc_id = get_stack_output('networking-stack', 'VpcId')  # May not exist
```

## Related Issues
#116, #214, #383, #417
## ECS Force Redeploy

CloudFormation updates to `TaskDefinition` (e.g., OTEL collector config changes)
create a new task definition revision but do NOT replace the running task.

**Rule:** Any change to otel-collector.yaml container definitions or environment
variables requires either:
- A `ForceDeploymentOnChange` custom resource, or
- Documentation telling admins to run `aws ecs update-service --force-new-deployment`

Without this, config changes are invisible until the next scheduled task replacement.
