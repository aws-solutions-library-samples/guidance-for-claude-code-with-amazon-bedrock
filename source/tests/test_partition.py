# ABOUTME: Unit tests for aws_partition_for_region (Python mirror of ${AWS::Partition}).

import pytest

from claude_code_with_bedrock.utils.partition import aws_partition_for_region


@pytest.mark.parametrize(
    "region,expected",
    [
        ("us-east-1", "aws"),
        ("us-west-2", "aws"),
        ("eu-west-1", "aws"),
        ("US-EAST-1", "aws"),  # case-insensitive
        ("us-gov-west-1", "aws-us-gov"),
        ("us-gov-east-1", "aws-us-gov"),
        ("US-GOV-WEST-1", "aws-us-gov"),
        ("cn-north-1", "aws-cn"),
        ("cn-northwest-1", "aws-cn"),
        ("", "aws"),
        (None, "aws"),
    ],
)
def test_partition_for_region(region, expected):
    assert aws_partition_for_region(region) == expected
