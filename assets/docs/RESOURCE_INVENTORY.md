# AWS Resource Inventory Per Stack

> **Last updated:** 2026-05-29

> **Purpose:** Pre-deployment reference for customers under restrictive SCPs.
> Use this to plan IAM/SCP exemptions or decide which stacks to skip before running `ccwb deploy`.
> This is a static point-in-time list — verify against the actual templates if your deployment uses a newer version.

## Stack Deployment Order

```
auth → networking → s3bucket → monitoring → dashboard → analytics → quota → [codebuild] → [distribution]
```

Stacks in `[]` are optional. Only `auth` is strictly required for basic Claude Code access.

---

## auth (bedrock-auth-{provider})

**Template:** `bedrock-auth-{cognito-pool|okta|azure|auth0|generic}.yaml`
**Required:** Yes (core authentication)

| Resource Type | Service Namespace | Count |
|---|---|---|
| `AWS::Cognito::IdentityPool` | `cognito-identity` | 1 |
| `AWS::Cognito::IdentityPoolRoleAttachment` | `cognito-identity` | 1 |
| `AWS::Cognito::IdentityPoolPrincipalTag` | `cognito-identity` | 1 |
| `AWS::IAM::OIDCProvider` | `iam` | 1 |
| `AWS::IAM::ManagedPolicy` | `iam` | 1 |
| `AWS::IAM::Role` | `iam` | 3 |
| `AWS::Logs::LogGroup` | `logs` | 1 |

**IAM actions required for deployment:**
- `cognito-identity:*`
- `iam:CreateRole`, `iam:PutRolePolicy`, `iam:AttachRolePolicy`, `iam:CreateOpenIDConnectProvider`, `iam:CreatePolicy`
- `logs:CreateLogGroup`, `logs:PutRetentionPolicy`

---

## networking

**Template:** `networking.yaml`
**Required:** Only for central monitoring mode

| Resource Type | Service Namespace | Count |
|---|---|---|
| `AWS::EC2::VPC` | `ec2` | 1 |
| `AWS::EC2::InternetGateway` | `ec2` | 1 |
| `AWS::EC2::VPCGatewayAttachment` | `ec2` | 1 |
| `AWS::EC2::Subnet` | `ec2` | 2 |
| `AWS::EC2::RouteTable` | `ec2` | 1 |
| `AWS::EC2::Route` | `ec2` | 1 |
| `AWS::EC2::SubnetRouteTableAssociation` | `ec2` | 2 |

**IAM actions required for deployment:**
- `ec2:CreateVpc`, `ec2:CreateSubnet`, `ec2:CreateInternetGateway`, `ec2:AttachInternetGateway`
- `ec2:CreateRouteTable`, `ec2:CreateRoute`, `ec2:AssociateRouteTable`
- `ec2:DescribeVpcs`, `ec2:DescribeSubnets`, `ec2:DescribeRouteTables`

---

## s3bucket

**Template:** `s3bucket.yaml`
**Required:** For central monitoring + quota (Lambda packaging)

| Resource Type | Service Namespace | Count |
|---|---|---|
| `AWS::S3::Bucket` | `s3` | 1 |

**IAM actions required for deployment:**
- `s3:CreateBucket`, `s3:PutBucketPolicy`, `s3:PutEncryptionConfiguration`

---

## monitoring (otel-collector)

**Template:** `otel-collector.yaml`
**Required:** For usage tracking and dashboards

| Resource Type | Service Namespace | Count |
|---|---|---|
| `AWS::ECS::Cluster` | `ecs` | 1 |
| `AWS::ECS::Service` | `ecs` | 2 |
| `AWS::ECS::TaskDefinition` | `ecs` | 1 |
| `AWS::EC2::SecurityGroup` | `ec2` | 2 |
| `AWS::ElasticLoadBalancingV2::LoadBalancer` | `elasticloadbalancing` | 1 |
| `AWS::ElasticLoadBalancingV2::Listener` | `elasticloadbalancing` | 2 |
| `AWS::ElasticLoadBalancingV2::TargetGroup` | `elasticloadbalancing` | 1 |
| `AWS::IAM::Role` | `iam` | 2 |
| `AWS::Logs::LogGroup` | `logs` | 2 |
| `AWS::SSM::Parameter` | `ssm` | 2 |
| `AWS::CertificateManager::Certificate` | `acm` | 1 (conditional) |
| `AWS::Route53::RecordSet` | `route53` | 1 (conditional) |
| `AWS::ApplicationAutoScaling::ScalableTarget` | `application-autoscaling` | 1 |
| `AWS::ApplicationAutoScaling::ScalingPolicy` | `application-autoscaling` | 1 |

**IAM actions required for deployment:**
- `ecs:CreateCluster`, `ecs:CreateService`, `ecs:RegisterTaskDefinition`
- `ec2:CreateSecurityGroup`, `ec2:AuthorizeSecurityGroupIngress`
- `elasticloadbalancing:CreateLoadBalancer`, `elasticloadbalancing:CreateTargetGroup`, `elasticloadbalancing:CreateListener`
- `iam:CreateRole`, `iam:PutRolePolicy`, `iam:PassRole`
- `logs:CreateLogGroup`
- `ssm:PutParameter`
- `acm:RequestCertificate` (if custom domain)
- `route53:ChangeResourceRecordSets` (if custom domain)
- `application-autoscaling:RegisterScalableTarget`, `application-autoscaling:PutScalingPolicy`

**Runtime service-linked role required:**
- `AWSServiceRoleForECS` (created automatically by `ccwb deploy`, or manually: `aws iam create-service-linked-role --aws-service-name ecs.amazonaws.com`)

---

## dashboard

**Template:** `claude-code-dashboard.yaml`
**Required:** No (optional visualization)

| Resource Type | Service Namespace | Count |
|---|---|---|
| `AWS::CloudWatch::Dashboard` | `cloudwatch` | 1 |

**IAM actions required for deployment:**
- `cloudwatch:PutDashboard`

---

## cowork-dashboard

**Template:** `cowork-dashboard.yaml`
**Required:** No (optional, CoWork-specific)

| Resource Type | Service Namespace | Count |
|---|---|---|
| `AWS::CloudWatch::Dashboard` | `cloudwatch` | 1 |

**IAM actions required for deployment:**
- `cloudwatch:PutDashboard`

---

## analytics

**Template:** `analytics-pipeline.yaml`
**Required:** No (optional, for SQL queries on usage data)

| Resource Type | Service Namespace | Count |
|---|---|---|
| `AWS::S3::Bucket` | `s3` | 2 |
| `AWS::IAM::Role` | `iam` | 3 |
| `AWS::Lambda::Function` | `lambda` | 1 |
| `AWS::KinesisFirehose::DeliveryStream` | `firehose` | 1 |
| `AWS::Logs::SubscriptionFilter` | `logs` | 1 |
| `AWS::Glue::Database` | `glue` | 1 |
| `AWS::Glue::Table` | `glue` | 1 |
| `AWS::Athena::WorkGroup` | `athena` | 1 |
| `AWS::Athena::NamedQuery` | `athena` | 10 |

**IAM actions required for deployment:**
- `s3:CreateBucket`
- `iam:CreateRole`, `iam:PutRolePolicy`, `iam:PassRole`
- `lambda:CreateFunction`, `lambda:AddPermission`
- `firehose:CreateDeliveryStream`
- `logs:PutSubscriptionFilter`
- `glue:CreateDatabase`, `glue:CreateTable`
- `athena:CreateWorkGroup`, `athena:CreateNamedQuery`

---

## quota

**Template:** `quota-monitoring.yaml`
**Required:** No (optional, for per-user token limits)

| Resource Type | Service Namespace | Count |
|---|---|---|
| `AWS::DynamoDB::Table` | `dynamodb` | 2 |
| `AWS::Lambda::Function` | `lambda` | 2 |
| `AWS::Lambda::Permission` | `lambda` | 2 |
| `AWS::IAM::Role` | `iam` | 2 |
| `AWS::SNS::Topic` | `sns` | 1 |
| `AWS::Events::Rule` | `events` | 1 |
| `AWS::ApiGatewayV2::Api` | `apigateway` | 1 |
| `AWS::ApiGatewayV2::Authorizer` | `apigateway` | 1 |
| `AWS::ApiGatewayV2::Integration` | `apigateway` | 1 |
| `AWS::ApiGatewayV2::Route` | `apigateway` | 1 |
| `AWS::ApiGatewayV2::Stage` | `apigateway` | 1 |

**IAM actions required for deployment:**
- `dynamodb:CreateTable`, `dynamodb:DescribeTable`
- `lambda:CreateFunction`, `lambda:AddPermission`
- `iam:CreateRole`, `iam:PutRolePolicy`, `iam:PassRole`
- `sns:CreateTopic`
- `events:PutRule`, `events:PutTargets`
- `apigateway:CreateApi`, `apigateway:CreateRoute`, `apigateway:CreateIntegration`, `apigateway:CreateStage`, `apigateway:CreateAuthorizer`

---

## codebuild

**Template:** `codebuild-windows.yaml`
**Required:** No (optional, for Windows binary builds)
**Region restriction:** us-east-1, us-east-2, us-west-2, eu-west-1, ap-southeast-2 only

| Resource Type | Service Namespace | Count |
|---|---|---|
| `AWS::S3::Bucket` | `s3` | 2 |
| `AWS::IAM::Role` | `iam` | 1 |
| `AWS::Logs::LogGroup` | `logs` | 1 |
| `AWS::CodeBuild::Project` | `codebuild` | 1 |

**IAM actions required for deployment:**
- `s3:CreateBucket`
- `iam:CreateRole`, `iam:PutRolePolicy`, `iam:PassRole`
- `logs:CreateLogGroup`
- `codebuild:CreateProject`

---

## distribution (presigned-s3)

**Template:** `presigned-s3-distribution.yaml`
**Required:** No (optional, for binary distribution via presigned URLs)

| Resource Type | Service Namespace | Count |
|---|---|---|
| `AWS::S3::Bucket` | `s3` | 2 |
| `AWS::IAM::User` | `iam` | 1 |
| `AWS::IAM::AccessKey` | `iam` | 1 |
| `AWS::IAM::Policy` | `iam` | 1 |
| `AWS::SecretsManager::Secret` | `secretsmanager` | 1 |

**IAM actions required for deployment:**
- `s3:CreateBucket`
- `iam:CreateUser`, `iam:CreateAccessKey`, `iam:PutUserPolicy`
- `secretsmanager:CreateSecret`

---

## distribution (landing-page)

**Template:** `landing-page-distribution.yaml`
**Required:** No (optional, ALB-based landing page with IdP auth)

| Resource Type | Service Namespace | Count |
|---|---|---|
| `AWS::S3::Bucket` | `s3` | 2 |
| `AWS::S3::BucketPolicy` | `s3` | 1 |
| `AWS::EC2::SecurityGroup` | `ec2` | 1 |
| `AWS::ElasticLoadBalancingV2::LoadBalancer` | `elasticloadbalancing` | 1 |
| `AWS::ElasticLoadBalancingV2::Listener` | `elasticloadbalancing` | 1 |
| `AWS::ElasticLoadBalancingV2::TargetGroup` | `elasticloadbalancing` | 1 |
| `AWS::Lambda::Function` | `lambda` | 2 |
| `AWS::Lambda::Permission` | `lambda` | 1 |
| `AWS::IAM::Role` | `iam` | 2 |
| `AWS::Logs::LogGroup` | `logs` | 1 |
| `AWS::CertificateManager::Certificate` | `acm` | 1 |
| `AWS::Route53::RecordSet` | `route53` | 1 |
| `AWS::CloudFormation::CustomResource` | `cloudformation` | 1 |

**IAM actions required for deployment:**
- `s3:CreateBucket`, `s3:PutBucketPolicy`
- `ec2:CreateSecurityGroup`, `ec2:AuthorizeSecurityGroupIngress`
- `elasticloadbalancing:CreateLoadBalancer`, `elasticloadbalancing:CreateTargetGroup`, `elasticloadbalancing:CreateListener`
- `lambda:CreateFunction`, `lambda:AddPermission`
- `iam:CreateRole`, `iam:PutRolePolicy`, `iam:PassRole`
- `logs:CreateLogGroup`
- `acm:RequestCertificate`
- `route53:ChangeResourceRecordSets`

---

## logs-insights-queries

**Template:** `logs-insights-queries.yaml`
**Required:** No (optional, pre-built CloudWatch Insights queries)

| Resource Type | Service Namespace | Count |
|---|---|---|
| `AWS::Logs::QueryDefinition` | `logs` | 19 |

**IAM actions required for deployment:**
- `logs:PutQueryDefinition`

---

## SCP Service Namespace Summary

Minimum services required for **basic deployment** (auth only):
```
cognito-identity, iam, logs, cloudformation, sts
```

Full deployment adds:
```
ec2, ecs, elasticloadbalancing, s3, ssm, acm, route53,
application-autoscaling, cloudwatch, dynamodb, lambda,
sns, events, apigateway, athena, glue, firehose, codebuild,
secretsmanager
```

**CloudFormation itself** always requires:
```
cloudformation:CreateStack, cloudformation:UpdateStack, cloudformation:DescribeStacks,
cloudformation:DescribeStackEvents, cloudformation:GetTemplate
```
