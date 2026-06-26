# ABOUTME: Maps an AWS region to its ARN partition (commercial, GovCloud, China).
# ABOUTME: Python-side mirror of the ${AWS::Partition} pseudo-parameter used in templates.


def aws_partition_for_region(region: str) -> str:
    """Return the ARN partition for an AWS region.

    GovCloud regions (``us-gov-*``) use ``aws-us-gov``, China regions (``cn-*``)
    use ``aws-cn``, and everything else uses ``aws``. This mirrors the
    ``${AWS::Partition}`` pseudo-parameter that CloudFormation templates rely on,
    so any ARN we have to build by hand in Python stays partition-correct outside
    commercial AWS (e.g. GovCloud deployments).
    """
    r = (region or "").lower()
    if r.startswith("us-gov-"):
        return "aws-us-gov"
    if r.startswith("cn-"):
        return "aws-cn"
    return "aws"
