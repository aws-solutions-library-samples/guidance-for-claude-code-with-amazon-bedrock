"""AllCode Nexus API - Lambda handler for reading metrics, users, and quotas."""

import json
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key

METRICS_TABLE = os.environ.get("METRICS_TABLE", "ClaudeCodeMetrics")
POLICIES_TABLE = os.environ.get("POLICIES_TABLE", "QuotaPolicies")
QUOTA_TABLE = os.environ.get("QUOTA_TABLE", "UserQuotaMetrics")
ORGS_TABLE = os.environ.get("ORGS_TABLE", "NexusOrganizations")
CORS_ORIGIN = os.environ.get("CORS_ORIGIN", "*")

dynamodb = boto3.resource("dynamodb")
metrics_table = dynamodb.Table(METRICS_TABLE)
policies_table = dynamodb.Table(POLICIES_TABLE)
quota_table = dynamodb.Table(QUOTA_TABLE)
orgs_table = dynamodb.Table(ORGS_TABLE)

# Cache for assumed role sessions
_role_cache: dict = {}


def _get_org_tables(org_id: str):
    """Get DynamoDB table references for an org (cross-account if needed)."""
    global metrics_table, policies_table, quota_table

    if not org_id or org_id == "allcode":
        # Local account — use default tables
        return metrics_table, policies_table, quota_table

    # Look up org
    try:
        result = orgs_table.get_item(Key={"pk": f"ORG#{org_id}", "sk": "DETAILS"})
        org = result.get("Item", {})
    except Exception:
        return None, None, None

    role_arn = org.get("role_arn", "")
    region = org.get("region", "us-east-1")

    if not role_arn:
        # Org exists but hasn't deployed yet — return None to signal empty
        return None, None, None

    # Assume cross-account role (cached)
    cache_key = f"{org_id}:{role_arn}"
    if cache_key not in _role_cache or _role_cache[cache_key]["expiry"] < datetime.now(timezone.utc):
        sts = boto3.client("sts")
        creds = sts.assume_role(
            RoleArn=role_arn,
            RoleSessionName=f"nexus-{org_id}",
            ExternalId=org_id,
            DurationSeconds=900,
        )["Credentials"]
        session = boto3.Session(
            aws_access_key_id=creds["AccessKeyId"],
            aws_secret_access_key=creds["SecretAccessKey"],
            aws_session_token=creds["SessionToken"],
            region_name=region,
        )
        _role_cache[cache_key] = {
            "session": session,
            "expiry": creds["Expiration"].replace(tzinfo=timezone.utc) - timedelta(minutes=5),
        }

    session = _role_cache[cache_key]["session"]
    ddb = session.resource("dynamodb")
    return ddb.Table(METRICS_TABLE), ddb.Table(POLICIES_TABLE), ddb.Table(QUOTA_TABLE)


def _get_org_from_event(event) -> str:
    """Extract org ID from request headers, query params, or user's group membership."""
    headers = event.get("headers", {}) or {}
    params = event.get("queryStringParameters", {}) or {}
    
    # Explicit org header/param takes priority (for super admins switching)
    org = headers.get("x-org-id", headers.get("X-Org-Id", params.get("org", "")))
    if org:
        return org
    
    # Look up user's groups from Cognito to find org membership
    claims = event.get("requestContext", {}).get("authorizer", {}).get("jwt", {}).get("claims", {})
    sub = claims.get("sub", claims.get("username", ""))
    if sub:
        try:
            cognito = boto3.client("cognito-idp")
            pool_id = os.environ.get("COGNITO_USER_POOL_ID", "")
            if pool_id:
                result = cognito.admin_list_groups_for_user(UserPoolId=pool_id, Username=sub, Limit=20)
                for group in result.get("Groups", []):
                    name = group.get("GroupName", "")
                    if name.startswith("org-"):
                        return name.replace("org-", "")
        except Exception:
            pass
    
    return "allcode"



def _query_all_metrics(since, table=None):
    """Paginate through all METRICS records since a timestamp."""
    t = table or metrics_table
    items = []
    kwargs = {"KeyConditionExpression": Key("pk").eq("METRICS") & Key("sk").gte(since), "ScanIndexForward": False}
    try:
        while True:
            result = t.query(**kwargs)
            items.extend(result.get("Items", []))
            if "LastEvaluatedKey" not in result:
                break
            kwargs["ExclusiveStartKey"] = result["LastEvaluatedKey"]
    except Exception:
        pass
    return items


def handle_chat(event):
    """POST /api/chat - send message to Claude via Bedrock."""
    body = json.loads(event.get("body", "{}"))
    message = body.get("message", "")
    history = body.get("history", [])

    if not message:
        return response(400, {"error": "Message is required"})

    bedrock = boto3.client("bedrock-runtime", region_name=os.environ.get("AWS_REGION", "us-east-1"))

    # Build messages array
    messages = []
    for h in history[-10:]:
        messages.append({"role": h.get("role", "user"), "content": h.get("content", "")})
    messages.append({"role": "user", "content": message})

    try:
        model_id = os.environ.get("SELECTED_MODEL", "us.anthropic.claude-sonnet-4-20250514-v1:0")
        resp = bedrock.invoke_model(
            modelId=model_id,
            contentType="application/json",
            accept="application/json",
            body=json.dumps({
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 4096,
                "messages": messages,
            }),
        )
        result = json.loads(resp["body"].read())
        assistant_text = result.get("content", [{}])[0].get("text", "")
        return response(200, {"response": assistant_text})
    except Exception as e:
        return response(500, {"error": str(e)})


def handle_provision_org(event):
    """POST /api/orgs/provision - self-service org creation."""
    body = json.loads(event.get("body", "{}"))
    org_name = body.get("orgName", "")
    role_arn = body.get("roleArn", "")
    user_pool_id = body.get("userPoolId", "")
    client_id = body.get("clientId", "")
    provider_domain = body.get("providerDomain", "")

    if not org_name or not role_arn:
        return response(400, {"error": "orgName and roleArn are required"})

    # Extract account ID from role ARN
    account_id = role_arn.split(":")[4] if ":" in role_arn else ""

    # Create org group in Cognito
    cognito = boto3.client("cognito-idp")
    pool_id = os.environ.get("COGNITO_USER_POOL_ID", "")
    try:
        cognito.create_group(
            GroupName=f"org-{org_name}",
            UserPoolId=pool_id,
            Description=f"{org_name} organization users",
        )
    except Exception:
        pass  # Group might already exist

    # Add to NexusOrganizations table
    orgs_table.put_item(Item={
        "pk": f"ORG#{org_name}",
        "sk": "DETAILS",
        "name": org_name,
        "role_arn": role_arn,
        "region": "us-east-1",
        "account_id": account_id,
        "user_pool_id": user_pool_id,
        "client_id": client_id,
        "provider_domain": provider_domain,
        "status": "active",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })

    # Trigger package generation async
    try:
        lam = boto3.client("lambda")
        lam.invoke(
            FunctionName="nexus-package-gen",
            InvocationType="Event",
            Payload=json.dumps({"org_id": org_name}),
        )
    except Exception:
        pass

    return response(201, {"orgName": org_name, "status": "provisioned"})


def handle_request_access(event):
    """POST /api/request-access - send access request email via SES + Slack."""
    body = json.loads(event.get("body", "{}"))
    first_name = body.get("firstName", "")
    last_name = body.get("lastName", "")
    email = body.get("email", "")

    if not email:
        return response(400, {"error": "Email is required"})

    # Send email
    ses = boto3.client("ses")
    try:
        ses.send_email(
            Source="nexus@allcode.com",
            Destination={"ToAddresses": ["sales@allcode.com"]},
            Message={
                "Subject": {"Data": f"Nexus Access Request: {first_name} {last_name}"},
                "Body": {"Text": {"Data": f"New access request:\n\nFirst Name: {first_name}\nLast Name: {last_name}\nEmail: {email}"}},
            },
        )
    except Exception:
        pass

    # Send to Slack #allcode-nexus channel
    try:
        import urllib.request
        token_table = dynamodb.Table("IntegrationTokens")
        tok = token_table.get_item(Key={"pk": "ORG#allcode", "sk": "slack"})
        slack_token = tok.get("Item", {}).get("access_token", "")
        if slack_token:
            msg = f"🔔 *New Access Request*\n>Name: {first_name} {last_name}\n>Email: {email}"
            data = json.dumps({"channel": "C0B28HHRMAM", "text": msg}).encode()
            req = urllib.request.Request("https://slack.com/api/chat.postMessage", data=data, headers={"Authorization": f"Bearer {slack_token}", "Content-Type": "application/json"})
            urllib.request.urlopen(req)
    except Exception:
        pass

    return response(200, {"sent": True})


def handle_list_orgs(event):
    """GET /api/orgs - list all organizations."""
    result = orgs_table.scan(Limit=100)
    orgs = []
    for item in result.get("Items", []):
        if item.get("sk") == "DETAILS":
            orgs.append({
                "id": item["pk"].replace("ORG#", ""),
                "name": item.get("name", ""),
                "status": item.get("status", "active"),
                "accountId": item.get("account_id", ""),
                "region": item.get("region", ""),
            })
    return response(200, {"orgs": orgs})


class DecimalEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, Decimal):
            return float(o)
        return super().default(o)


def response(status, body):
    return {
        "statusCode": status,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": CORS_ORIGIN,
            "Access-Control-Allow-Headers": "Authorization,Content-Type",
            "Access-Control-Allow-Methods": "GET,POST,PUT,DELETE,OPTIONS",
        },
        "body": json.dumps(body, cls=DecimalEncoder),
    }


def get_caller_email(event):
    """Extract email from JWT claims passed by API Gateway."""
    import base64
    # API Gateway HTTP API JWT authorizer passes all claims
    claims = event.get("requestContext", {}).get("authorizer", {}).get("jwt", {}).get("claims", {})
    
    # Try email claim directly
    email = claims.get("email", "")
    if email and "@" in email:
        return email

    # Try from Authorization header (decode JWT payload)
    headers = event.get("headers", {}) or {}
    auth_header = headers.get("authorization", headers.get("Authorization", ""))
    if auth_header.startswith("Bearer "):
        try:
            payload = auth_header[7:].split(".")[1]
            payload += "=" * (4 - len(payload) % 4)
            decoded = json.loads(base64.b64decode(payload))
            if decoded.get("email") and "@" in decoded["email"]:
                return decoded["email"]
        except Exception:
            pass

    # Last resort: look up email from Cognito by sub/username
    sub = claims.get("sub", claims.get("cognito:username", ""))
    if sub:
        try:
            cognito = boto3.client("cognito-idp")
            pool_id = os.environ.get("COGNITO_USER_POOL_ID", "")
            if pool_id:
                result = cognito.admin_get_user(UserPoolId=pool_id, Username=sub)
                for attr in result.get("UserAttributes", []):
                    if attr["Name"] == "email":
                        return attr["Value"]
        except Exception:
            pass

    return "unknown"


def handle_summary(event):
    """GET /api/metrics/summary - org-wide usage from CloudWatch."""
    org_id = _get_org_from_event(event)

    if org_id != "allcode":
        org_metrics, _, _ = _get_org_tables(org_id)
        if org_metrics is None:
            return response(200, {"activeUsers": 0, "monthlyTokens": 0, "orgQuotaPercent": 0, "topUsers": [], "tokenHistory": []})

    now = datetime.now(timezone.utc)
    cw = boto3.client("cloudwatch")

    # Get total tokens (30 days) from CloudWatch
    # Display: input + output only (what Anthropic shows)
    # Cost: all types at their respective rates
    PRICING = {"input": 3.0, "output": 15.0, "cacheRead": 0.30, "cacheCreation": 3.75}
    try:
        total_tokens = 0  # Display tokens (input + output only)
        total_cost = 0.0  # Real cost (all types)
        token_history_map = {}
        for token_type, price_per_million in PRICING.items():
            result = cw.get_metric_statistics(
                Namespace="ClaudeCode",
                MetricName="claude_code.token.usage",
                Dimensions=[{"Name": "type", "Value": token_type}, {"Name": "OTelLib", "Value": "com.anthropic.claude_code"}],
                StartTime=now - timedelta(days=30),
                EndTime=now,
                Period=86400,
                Statistics=["Sum"],
            )
            for p in result.get("Datapoints", []):
                tokens = int(p["Sum"])
                total_cost += (tokens / 1_000_000) * price_per_million
                # Only count input + output for display
                if token_type in ("input", "output"):
                    total_tokens += tokens
                    date = p["Timestamp"].strftime("%Y-%m-%d")
                    token_history_map[date] = token_history_map.get(date, 0) + tokens
        token_history = [{"date": k, "tokens": v} for k, v in sorted(token_history_map.items())]
    except Exception:
        total_tokens = 0
        total_cost = 0.0
        token_history = []

    # Get per-user token usage from CloudWatch
    # Note: per-user includes all token types (input+output+cache)
    # We calculate proportional billable tokens based on org total
    top_users = []
    all_emails = set()
    total_all_types = 0
    try:
        metrics = cw.list_metrics(Namespace="ClaudeCode", MetricName="claude_code.token.usage", Dimensions=[{"Name": "user.email"}])
        user_emails = set()
        for m in metrics.get("Metrics", []):
            for d in m.get("Dimensions", []):
                if d["Name"] == "user.email" and "@" in d["Value"] and "anonymous" not in d["Value"] and "example.com" not in d["Value"]:
                    user_emails.add(d["Value"])

        user_raw = {}
        for email in list(user_emails)[:20]:
            try:
                user_result = cw.get_metric_statistics(
                    Namespace="ClaudeCode",
                    MetricName="claude_code.token.usage",
                    Dimensions=[{"Name": "user.email", "Value": email}, {"Name": "OTelLib", "Value": "com.anthropic.claude_code"}],
                    StartTime=now - timedelta(days=30),
                    EndTime=now,
                    Period=2592000,
                    Statistics=["Sum"],
                )
                user_tokens = int(sum(p.get("Sum", 0) for p in user_result.get("Datapoints", [])))
                if user_tokens > 0:
                    user_raw[email] = user_tokens
                    total_all_types += user_tokens
                    all_emails.add(email)
            except Exception:
                pass

        # Calculate proportional billable tokens per user
        for email, raw in sorted(user_raw.items(), key=lambda x: -x[1]):
            proportion = raw / total_all_types if total_all_types > 0 else 0
            billable = int(total_tokens * proportion)
            top_users.append({"email": email, "tokens": billable})

    except Exception:
        pass

    return response(200, {
        "activeUsers": len(all_emails),
        "monthlyTokens": total_tokens,
        "monthlyCost": round(total_cost, 2),
        "orgQuotaPercent": min(int(total_tokens / 2_250_000_000 * 100), 100) if total_tokens else 0,
        "topUsers": top_users[:10],
        "tokenHistory": token_history,
    })


def handle_users(event):
    """GET /api/users - list users with usage."""
    org_id = _get_org_from_event(event)
    
    # Get users from Cognito - filter by org group
    cognito = boto3.client("cognito-idp")
    pool_id = os.environ.get("COGNITO_USER_POOL_ID", "")
    all_users: dict = {}

    if pool_id:
        try:
            if org_id == "allcode":
                # AllCode: show all users NOT in any org- group (or all users)
                paginator = cognito.get_paginator("list_users")
                for page in paginator.paginate(UserPoolId=pool_id, Limit=60):
                    for user in page.get("Users", []):
                        email = ""
                        for attr in user.get("Attributes", []):
                            if attr["Name"] == "email":
                                email = attr["Value"]
                        if email:
                            last_active_str = ""
                            if hasattr(user.get("UserLastModifiedDate", ""), "isoformat"):
                                last_active_str = user["UserLastModifiedDate"].isoformat()
                            all_users[email] = {
                                "tokens": 0,
                                "last_active": last_active_str,
                                "status": "active" if user.get("UserStatus") == "CONFIRMED" else "inactive",
                                "role": "user",
                                "username": user.get("Username", ""),
                            }
            else:
                # Other orgs: show only users in their org group
                group_name = f"org-{org_id}"
                result = cognito.list_users_in_group(UserPoolId=pool_id, GroupName=group_name, Limit=60)
                for user in result.get("Users", []):
                    email = ""
                    for attr in user.get("Attributes", []):
                        if attr["Name"] == "email":
                            email = attr["Value"]
                    if email:
                        last_active_str = ""
                        if hasattr(user.get("UserLastModifiedDate", ""), "isoformat"):
                            last_active_str = user["UserLastModifiedDate"].isoformat()
                        all_users[email] = {
                            "tokens": 0,
                            "last_active": last_active_str,
                            "status": "active" if user.get("UserStatus") == "CONFIRMED" else "inactive",
                            "role": "org-admin",
                            "username": user.get("Username", ""),
                        }
        except Exception:
            pass

    # For non-allcode orgs, return the users we found in their group
    if org_id != "allcode":
        users = [{"email": e, "monthlyTokens": d["tokens"], "lastActive": d["last_active"], "status": d["status"], "role": d.get("role", "user")} for e, d in all_users.items()]
        return response(200, {"users": users})

    now = datetime.now(timezone.utc)
    thirty_days_ago = (now - timedelta(days=30)).isoformat()

    # Get users in org- groups to exclude from AllCode list
    cognito = boto3.client("cognito-idp")
    pool_id = os.environ.get("COGNITO_USER_POOL_ID", "")
    org_users = set()
    if pool_id and org_id == "allcode":
        try:
            groups_resp = cognito.list_groups(UserPoolId=pool_id, Limit=60)
            for group in groups_resp.get("Groups", []):
                if group["GroupName"].startswith("org-"):
                    members = cognito.list_users_in_group(UserPoolId=pool_id, GroupName=group["GroupName"], Limit=60)
                    for u in members.get("Users", []):
                        for attr in u.get("Attributes", []):
                            if attr["Name"] == "email":
                                org_users.add(attr["Value"])
        except Exception:
            pass

    # Skip the full user list for non-allcode orgs (already populated above)
    if org_id == "allcode":
        all_users: dict = {}

        if pool_id:
            try:
                paginator = cognito.get_paginator("list_users")
                for page in paginator.paginate(UserPoolId=pool_id, Limit=60):
                    for user in page.get("Users", []):
                        email = ""
                        for attr in user.get("Attributes", []):
                            if attr["Name"] == "email":
                                email = attr["Value"]
                        if email and email not in org_users and "@example.com" not in email and "anonymous" not in email and user.get("UserStatus") == "CONFIRMED":
                            last_active_str = ""
                            if hasattr(user.get("UserLastModifiedDate", ""), "isoformat"):
                                last_active_str = user["UserLastModifiedDate"].isoformat()
                            all_users[email] = {
                                "tokens": 0,
                                "last_active": last_active_str,
                                "status": "active" if user.get("UserStatus") == "CONFIRMED" else "inactive",
                                "role": "user",
                                "username": user.get("Username", ""),
                            }
            except Exception:
                pass
            # Check admin group membership
            try:
                super_resp = cognito.list_users_in_group(UserPoolId=pool_id, GroupName="nexus-super-admins", Limit=60)
                for user in super_resp.get("Users", []):
                    for attr in user.get("Attributes", []):
                        if attr["Name"] == "email" and attr["Value"] in all_users:
                            all_users[attr["Value"]]["role"] = "super-admin"
            except Exception:
                pass
            try:
                admin_resp = cognito.list_users_in_group(UserPoolId=pool_id, GroupName="claude-code-admins", Limit=60)
                for user in admin_resp.get("Users", []):
                    for attr in user.get("Attributes", []):
                        if attr["Name"] == "email" and attr["Value"] in all_users:
                            if all_users[attr["Value"]]["role"] != "super-admin":
                                all_users[attr["Value"]]["role"] = "org-admin"
            except Exception:
                pass

    # Overlay usage data from CloudWatch (accurate input+output tokens)
    cw = boto3.client("cloudwatch")
    now = datetime.now(timezone.utc)
    try:
        # Get total billable tokens (input + output)
        total_billable = 0
        for token_type in ["input", "output"]:
            r = cw.get_metric_statistics(
                Namespace="ClaudeCode", MetricName="claude_code.token.usage",
                Dimensions=[{"Name": "type", "Value": token_type}, {"Name": "OTelLib", "Value": "com.anthropic.claude_code"}],
                StartTime=now - timedelta(days=30), EndTime=now, Period=2592000, Statistics=["Sum"],
            )
            total_billable += int(sum(p.get("Sum", 0) for p in r.get("Datapoints", [])))

        # Get per-user proportions
        user_metrics = cw.list_metrics(Namespace="ClaudeCode", MetricName="claude_code.token.usage", Dimensions=[{"Name": "user.email"}])
        total_all = 0
        user_raw = {}
        for m in user_metrics.get("Metrics", []):
            for d in m.get("Dimensions", []):
                if d["Name"] == "user.email" and "@" in d["Value"] and "anonymous" not in d["Value"] and "example.com" not in d["Value"]:
                    email = d["Value"]
                    r = cw.get_metric_statistics(
                        Namespace="ClaudeCode", MetricName="claude_code.token.usage",
                        Dimensions=[{"Name": "user.email", "Value": email}, {"Name": "OTelLib", "Value": "com.anthropic.claude_code"}],
                        StartTime=now - timedelta(days=30), EndTime=now, Period=2592000, Statistics=["Sum"],
                    )
                    tokens = int(sum(p.get("Sum", 0) for p in r.get("Datapoints", [])))
                    if tokens > 0:
                        user_raw[email] = tokens
                        total_all += tokens

        # Apply proportional billable tokens to users
        for email, raw in user_raw.items():
            proportion = raw / total_all if total_all > 0 else 0
            billable = int(total_billable * proportion)
            if email in all_users:
                all_users[email]["tokens"] = billable
            elif email not in org_users and "CONFIRMED" not in email:
                all_users[email] = {"tokens": billable, "last_active": "", "status": "active", "role": "user", "username": ""}
    except Exception:
        pass

    users = []
    for email, data in all_users.items():
        users.append({
            "email": email,
            "monthlyTokens": data["tokens"],
            "lastActive": data["last_active"],
            "status": data["status"],
            "role": data.get("role", "user"),
        })

    return response(200, {"users": sorted(users, key=lambda x: -x["monthlyTokens"])})


def handle_user_me(event):
    """GET /api/users/me - current user's data."""
    email = get_caller_email(event)
    org_id = _get_org_from_event(event)

    # Get user's token usage from WINDOW#SUMMARY records
    now = datetime.now(timezone.utc)
    thirty_days_ago = (now - timedelta(days=30)).isoformat()
    one_day_ago = (now - timedelta(days=1)).isoformat()

    result = {"Items": _query_all_metrics(thirty_days_ago)}

    monthly_tokens = 0
    daily_tokens = 0
    for item in result.get("Items", []):
        if "#WINDOW#SUMMARY" not in item.get("sk", ""):
            continue
        for u in item.get("top_users", []):
            if isinstance(u, dict):
                user_email = u.get("email", u.get("user", ""))
                # Match by email or partial match (handle case differences)
                if user_email and (user_email.lower() == email.lower() or email.lower() in user_email.lower()):
                    tokens = int(u.get("tokens", 0))
                    monthly_tokens += tokens
                    if item.get("timestamp", "") >= one_day_ago:
                        daily_tokens += tokens

    # If no match found by email, user has no recorded usage
    if monthly_tokens == 0:
        pass  # Genuinely no usage for this user

    # Get user's policy
    policy_result = policies_table.query(
        IndexName="PolicyTypeIndex",
        KeyConditionExpression=Key("policy_type").eq("user") & Key("identifier").eq(email),
        Limit=1,
    )
    policy = policy_result.get("Items", [{}])[0] if policy_result.get("Items") else {}

    # Fallback to default policy
    if not policy:
        default_result = policies_table.query(
            IndexName="PolicyTypeIndex",
            KeyConditionExpression=Key("policy_type").eq("default"),
            Limit=1,
        )
        policy = default_result.get("Items", [{}])[0] if default_result.get("Items") else {}

    monthly_limit = int(policy.get("monthly_limit", 225_000_000))
    daily_limit = int(policy.get("daily_limit", 0)) or int(monthly_limit / 30)

    return response(200, {
        "org": org_id,
        "monthly": {"used": monthly_tokens, "limit": monthly_limit},
        "daily": {"used": daily_tokens, "limit": daily_limit},
        "model": os.environ.get("SELECTED_MODEL", "Claude Sonnet 4"),
        "status": "active",
    })


def handle_quotas(event):
    """GET /api/quotas - list all quota policies."""
    org_id = _get_org_from_event(event)
    _, org_policies, _ = _get_org_tables(org_id)
    try:
        result = org_policies.scan(Limit=100)
    except Exception:
        return response(200, {"policies": []})
    policies = []
    for item in result.get("Items", []):
        if not item.get("pk", "").startswith("POLICY#"):
            continue
        policies.append({
            "id": item.get("pk", ""),
            "type": item.get("policy_type", "default"),
            "target": item.get("identifier", "All Users"),
            "monthlyLimit": int(item.get("monthly_limit", 225_000_000)),
            "dailyLimit": int(item.get("daily_limit", 0)) or None,
            "enforcement": item.get("enforcement_mode", "block"),
        })
    return response(200, {"policies": policies})


def handle_models(event):
    """GET /api/config/models - available models."""
    # Read current config from DynamoDB (or env defaults)
    try:
        result = policies_table.get_item(Key={"pk": "CONFIG#models", "sk": "CURRENT"})
        config = result.get("Item", {})
    except Exception:
        config = {}

    return response(200, {
        "selectedModel": config.get("selected_model", os.environ.get("SELECTED_MODEL", "us.anthropic.claude-sonnet-4-20250514-v1:0")),
        "region": config.get("region", os.environ.get("AWS_REGION", "us-east-1")),
        "crossRegionProfile": config.get("cross_region_profile", os.environ.get("CROSS_REGION_PROFILE", "us")),
        "availableModels": [
            "us.anthropic.claude-sonnet-4-20250514-v1:0",
            "us.anthropic.claude-sonnet-4-6",
            "us.anthropic.claude-opus-4-20250514-v1:0",
            "us.anthropic.claude-opus-4-7",
            "us.anthropic.claude-haiku-4-5-20251001-v1:0",
        ],
    })


def handle_update_models(event):
    """PUT /api/config/models - update model configuration."""
    body = json.loads(event.get("body", "{}"))

    item = {
        "pk": "CONFIG#models",
        "sk": "CURRENT",
        "selected_model": body.get("selectedModel", ""),
        "region": body.get("region", "us-east-1"),
        "cross_region_profile": body.get("crossRegionProfile", "us"),
    }
    policies_table.put_item(Item=item)
    return response(200, {"updated": True, **item})


def handle_user_detail(event):
    """GET /api/users/{id} - user detail with usage history."""
    path = event.get("requestContext", {}).get("http", {}).get("path", "")
    user_email = path.split("/api/users/", 1)[-1]

    # Get quota metrics
    result = quota_table.query(
        KeyConditionExpression=Key("pk").eq(f"USER#{user_email}"),
        Limit=10,
        ScanIndexForward=False,
    )
    items = result.get("Items", [])
    current = items[0] if items else {}

    # Get user's policy
    policy_result = policies_table.query(
        IndexName="PolicyTypeIndex",
        KeyConditionExpression=Key("policy_type").eq("user") & Key("identifier").eq(user_email),
        Limit=1,
    )
    policy = policy_result.get("Items", [{}])[0] if policy_result.get("Items") else {}

    monthly_limit = int(policy.get("monthly_limit", 225_000_000))
    monthly_used = int(current.get("monthly_tokens", 0))

    return response(200, {
        "email": user_email,
        "monthlyTokens": monthly_used,
        "monthlyLimit": monthly_limit,
        "dailyTokens": int(current.get("daily_tokens", 0)),
        "lastActive": current.get("timestamp", ""),
        "blocked": bool(current.get("blocked")),
        "status": "blocked" if current.get("blocked") else "active",
    })


def handle_create_user(event):
    """POST /api/users - create a new user in Cognito (sends invite email)."""
    body = json.loads(event.get("body", "{}"))
    email = body.get("email", "")
    role = body.get("role", "user")  # "admin" or "user"
    if not email:
        return response(400, {"error": "Email is required"})

    cognito = boto3.client("cognito-idp")
    pool_id = os.environ.get("COGNITO_USER_POOL_ID", "")

    try:
        cognito.admin_create_user(
            UserPoolId=pool_id,
            Username=email,
            UserAttributes=[
                {"Name": "email", "Value": email},
                {"Name": "email_verified", "Value": "true"},
            ],
            DesiredDeliveryMediums=["EMAIL"],
        )

        # Add to admin group if role is admin
        if role == "admin":
            try:
                cognito.admin_add_user_to_group(
                    UserPoolId=pool_id,
                    Username=email,
                    GroupName="claude-code-admins",
                )
            except Exception:
                pass  # Group might not exist yet

        log_audit(get_caller_email(event), "create_user", email, f"role={role}")
        return response(201, {"email": email, "role": role, "status": "invited"})
    except Exception as e:
        return response(400, {"error": str(e)})


def handle_resend_invite(event):
    """PUT /api/users/{id}/resend-invite - resend invitation email."""
    path = event.get("requestContext", {}).get("http", {}).get("path", "")
    user_email = path.replace("/resend-invite", "").split("/api/users/", 1)[-1]

    cognito = boto3.client("cognito-idp")
    pool_id = os.environ.get("COGNITO_USER_POOL_ID", "")

    try:
        result = cognito.list_users(
            UserPoolId=pool_id,
            Filter=f'email = "{user_email}"',
            Limit=1,
        )
        users = result.get("Users", [])
        if not users:
            return response(404, {"error": "User not found"})

        username = users[0]["Username"]
        cognito.admin_create_user(
            UserPoolId=pool_id,
            Username=username,
            MessageAction="RESEND",
            DesiredDeliveryMediums=["EMAIL"],
        )
        log_audit(get_caller_email(event), "resend_invite", user_email, "")
        return response(200, {"email": user_email, "message": "Invitation resent"})
    except Exception as e:
        return response(400, {"error": str(e)})


def handle_reset_password(event):
    """PUT /api/users/{id}/reset-password - reset user's password (sends email)."""
    path = event.get("requestContext", {}).get("http", {}).get("path", "")
    user_email = path.replace("/reset-password", "").split("/api/users/", 1)[-1]

    cognito = boto3.client("cognito-idp")
    pool_id = os.environ.get("COGNITO_USER_POOL_ID", "")

    try:
        # Find username by email
        result = cognito.list_users(
            UserPoolId=pool_id,
            Filter=f'email = "{user_email}"',
            Limit=1,
        )
        users = result.get("Users", [])
        if not users:
            return response(404, {"error": "User not found"})

        username = users[0]["Username"]
        cognito.admin_reset_user_password(UserPoolId=pool_id, Username=username)
        log_audit(get_caller_email(event), "reset_password", user_email, "")
        return response(200, {"email": user_email, "message": "Password reset email sent"})
    except Exception as e:
        return response(400, {"error": str(e)})


def handle_delete_user(event):
    """DELETE /api/users/{id} - delete a user from Cognito."""
    path = event.get("requestContext", {}).get("http", {}).get("path", "")
    user_email = path.split("/api/users/", 1)[-1]

    cognito = boto3.client("cognito-idp")
    pool_id = os.environ.get("COGNITO_USER_POOL_ID", "")

    try:
        # Find the username by email
        result = cognito.list_users(
            UserPoolId=pool_id,
            Filter=f'email = "{user_email}"',
            Limit=1,
        )
        users = result.get("Users", [])
        if not users:
            return response(404, {"error": "User not found"})

        username = users[0]["Username"]
        cognito.admin_delete_user(UserPoolId=pool_id, Username=username)
        log_audit(get_caller_email(event), "delete_user", user_email, "")
        return response(200, {"deleted": user_email})
    except Exception as e:
        return response(400, {"error": str(e)})


def handle_toggle_user(event):
    """PUT /api/users/{id}/toggle - block or unblock a user."""
    path = event.get("requestContext", {}).get("http", {}).get("path", "")
    user_email = path.replace("/toggle", "").split("/api/users/", 1)[-1]
    body = json.loads(event.get("body", "{}"))
    blocked = body.get("blocked", False)

    # Create/update a user-level quota policy with block enforcement
    if blocked:
        policies_table.put_item(Item={
            "pk": f"POLICY#user#{user_email}",
            "sk": "CURRENT",
            "policy_type": "user",
            "identifier": user_email,
            "monthly_limit": 0,
            "daily_limit": 0,
            "enforcement_mode": "block",
        })
    else:
        # Remove the blocking policy
        try:
            policies_table.delete_item(Key={"pk": f"POLICY#user#{user_email}", "sk": "CURRENT"})
        except Exception:
            pass

    log_audit(get_caller_email(event), "block_user" if blocked else "unblock_user", user_email, "")
    return response(200, {"email": user_email, "blocked": blocked})


def handle_activity(event):
    """GET /api/users/me/activity - recent activity for current user."""
    email = get_caller_email(event)
    now = datetime.now(timezone.utc)
    seven_days_ago = (now - timedelta(days=7)).isoformat()

    # Get recent WINDOW#SUMMARY records with activity
    result = {"Items": _query_all_metrics(seven_days_ago)}

    activities = []
    for item in result.get("Items", []):
        sk = item.get("sk", "")
        if "#WINDOW#SUMMARY" in sk and int(item.get("total_tokens", 0)) > 0:
            # Check if this user is in top_users
            for u in item.get("top_users", []):
                if isinstance(u, dict):
                    user_email = u.get("email", u.get("user", ""))
                    if user_email and user_email.lower() == email.lower():
                        activities.append({
                            "timestamp": item.get("timestamp", ""),
                            "tokens": int(u.get("tokens", 0)),
                            "model": "",
                            "type": "session",
                        })

    # Sort by timestamp descending
    activities.sort(key=lambda x: x["timestamp"], reverse=True)
    return response(200, {"activities": activities[:50]})


def handle_export_users(event):
    """GET /api/users/export - CSV export of all users."""
    import csv
    import io

    now = datetime.now(timezone.utc)
    thirty_days_ago = (now - timedelta(days=30)).isoformat()

    result = {"Items": _query_all_metrics(thirty_days_ago)}

    user_data: dict = {}
    for item in result.get("Items", []):
        if "#WINDOW#SUMMARY" in item.get("sk", ""):
            for u in item.get("top_users", []):
                if isinstance(u, dict):
                    email = u.get("email", u.get("user", ""))
                    tokens = int(u.get("tokens", 0))
                    if email:
                        if email not in user_data:
                            user_data[email] = {"tokens": 0, "last_active": ""}
                        user_data[email]["tokens"] += tokens
                        ts = item.get("timestamp", "")
                        if ts > user_data[email]["last_active"]:
                            user_data[email]["last_active"] = ts

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Email", "Monthly Tokens", "Last Active", "Status"])
    for email, data in sorted(user_data.items(), key=lambda x: -x[1]["tokens"]):
        writer.writerow([email, data["tokens"], data["last_active"], "active"])

    return {
        "statusCode": 200,
        "headers": {
            "Content-Type": "text/csv",
            "Content-Disposition": f"attachment; filename=users-export-{now.strftime('%Y-%m-%d')}.csv",
            "Access-Control-Allow-Origin": CORS_ORIGIN,
        },
        "body": output.getvalue(),
    }


def handle_budget_alerts(event):
    """POST /api/config/alerts - configure budget alert threshold."""
    body = json.loads(event.get("body", "{}"))
    threshold_percent = int(body.get("thresholdPercent", 80))
    email = body.get("email", "")

    if not email:
        return response(400, {"error": "Email is required"})

    # Subscribe email to the existing SNS quota alert topic
    sns = boto3.client("sns")
    topic_arn = os.environ.get("ALERT_TOPIC_ARN", "")

    if not topic_arn:
        return response(404, {"error": "Alert topic not configured"})

    try:
        sns.subscribe(TopicArn=topic_arn, Protocol="email", Endpoint=email)
    except Exception as e:
        return response(500, {"error": f"Failed to subscribe: {str(e)}"})

    # Save threshold config
    policies_table.put_item(Item={
        "pk": "CONFIG#alerts",
        "sk": "CURRENT",
        "threshold_percent": threshold_percent,
        "alert_email": email,
    })

    return response(200, {"subscribed": email, "thresholdPercent": threshold_percent})


def handle_get_alerts(event):
    """GET /api/config/alerts - get current alert config."""
    try:
        result = policies_table.get_item(Key={"pk": "CONFIG#alerts", "sk": "CURRENT"})
        item = result.get("Item", {})
        return response(200, {
            "thresholdPercent": int(item.get("threshold_percent", 80)),
            "email": item.get("alert_email", ""),
        })
    except Exception:
        return response(200, {"thresholdPercent": 80, "email": ""})


def handle_billing_report(event):
    """GET /api/billing/report - CSV export of usage by user."""
    import csv
    import io

    org_id = _get_org_from_event(event)
    org_metrics, _, _ = _get_org_tables(org_id)
    if org_metrics is None:
        return {
            "statusCode": 200,
            "headers": {"Content-Type": "text/csv", "Content-Disposition": "attachment; filename=billing-report.csv", "Access-Control-Allow-Origin": CORS_ORIGIN},
            "body": "User,Tokens,Bedrock Cost ($),Nexus Fee ($),Total ($)\r\n",
        }

    now = datetime.now(timezone.utc)
    thirty_days_ago = (now - timedelta(days=30)).isoformat()

    # Query metrics for the period
    result = {"Items": _query_all_metrics(thirty_days_ago)}
    items = result.get("Items", [])

    # Aggregate by user from top_users
    user_totals: dict = {}
    for item in items:
        for u in item.get("top_users", []):
            if isinstance(u, dict):
                email = u.get("email", u.get("user", "unknown"))
                tokens = int(u.get("tokens", 0))
                user_totals[email] = user_totals.get(email, 0) + tokens

    # Generate CSV
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["User", "Tokens", "Bedrock Cost ($)", "Nexus Fee (30%)", "Total ($)"])
    total_tokens = 0
    total_cost = 0
    for email, tokens in sorted(user_totals.items(), key=lambda x: -x[1]):
        bedrock_cost = (tokens / 1_000_000) * 8
        nexus_fee = bedrock_cost * 0.30
        row_total = bedrock_cost + nexus_fee
        writer.writerow([email, tokens, f"{bedrock_cost:.2f}", f"{nexus_fee:.2f}", f"{row_total:.2f}"])
        total_tokens += tokens
        total_cost += row_total
    writer.writerow([])
    writer.writerow(["TOTAL", total_tokens, "", "", f"{total_cost:.2f}"])
    writer.writerow([])
    writer.writerow(["Report Period", f"{thirty_days_ago[:10]} to {now.strftime('%Y-%m-%d')}"])
    writer.writerow(["Organization", org_id])

    csv_content = output.getvalue()

    return {
        "statusCode": 200,
        "headers": {
            "Content-Type": "text/csv",
            "Content-Disposition": f"attachment; filename=billing-report-{now.strftime('%Y-%m-%d')}.csv",
            "Access-Control-Allow-Origin": CORS_ORIGIN,
        },
        "body": csv_content,
    }


def handle_download(event):
    """GET /api/download - generate presigned URL for latest package."""
    bucket = os.environ.get("DISTRIBUTION_BUCKET", "")
    if not bucket:
        return response(404, {"error": "Distribution bucket not configured"})

    # Get platform from query params (default: auto-detect or mac)
    params = event.get("queryStringParameters", {}) or {}
    platform = params.get("platform", "mac")

    s3 = boto3.client("s3")

    # Handle cowork config downloads
    cowork_files = {
        "cowork-macos": "cowork/cowork-3p.mobileconfig",
        "cowork-windows": "cowork/cowork-3p.reg",
        "cowork-json": "cowork/cowork-3p-config.json",
    }
    if platform in cowork_files:
        try:
            url = s3.generate_presigned_url("get_object", Params={"Bucket": bucket, "Key": cowork_files[platform]}, ExpiresIn=3600)
            return response(200, {"url": url, "filename": cowork_files[platform].split("/")[-1], "platform": platform})
        except Exception as e:
            return response(500, {"error": str(e)})

    try:
        # Check for org-specific package first
        org_id = _get_org_from_event(event)
        if org_id and org_id != "allcode":
            org_prefix = f"packages/{org_id}/{platform}/"
            org_result = s3.list_objects_v2(Bucket=bucket, Prefix=org_prefix)
            org_zips = [o["Key"] for o in org_result.get("Contents", []) if o["Key"].endswith(".zip")]
            if org_zips:
                org_zips.sort(reverse=True)
                url = s3.generate_presigned_url("get_object", Params={"Bucket": bucket, "Key": org_zips[0]}, ExpiresIn=3600)
                return response(200, {"url": url, "filename": org_zips[0].split("/")[-1], "platform": platform})

        # Look for platform-specific package first
        platform_prefix = f"packages/{platform}/"
        result = s3.list_objects_v2(Bucket=bucket, Prefix=platform_prefix)
        zips = [o["Key"] for o in result.get("Contents", []) if o["Key"].endswith(".zip")]

        # Fall back to latest general package
        if not zips:
            result = s3.list_objects_v2(Bucket=bucket, Prefix="packages/", Delimiter="/")
            prefixes = sorted([p["Prefix"] for p in result.get("CommonPrefixes", [])], reverse=True)
            if not prefixes:
                return response(404, {"error": "No packages found"})
            latest = prefixes[0]
            objects = s3.list_objects_v2(Bucket=bucket, Prefix=latest)
            zips = [o["Key"] for o in objects.get("Contents", []) if o["Key"].endswith(".zip")]

        if not zips:
            return response(404, {"error": "No zip file found"})

        # Use the most recent zip
        zips.sort(reverse=True)
        url = s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket, "Key": zips[0]},
            ExpiresIn=3600,
        )
        return response(200, {"url": url, "filename": zips[0].split("/")[-1], "platform": platform})
    except Exception as e:
        return response(500, {"error": f"Failed to generate download URL: {str(e)}"})


def handle_create_quota(event):
    """POST /api/quotas - create quota policy."""
    body = json.loads(event.get("body", "{}"))
    policy_type = body.get("type", "default")
    identifier = body.get("target", "")
    pk = f"POLICY#{policy_type}#{identifier}" if identifier else f"POLICY#{policy_type}"

    item = {
        "pk": pk,
        "sk": "CURRENT",
        "policy_type": policy_type,
        "identifier": identifier,
        "monthly_limit": int(body.get("monthlyLimit", 225_000_000)),
        "daily_limit": int(body.get("dailyLimit", 0)),
        "enforcement_mode": body.get("enforcement", "block"),
    }
    policies_table.put_item(Item=item)
    log_audit(get_caller_email(event), "create_quota", identifier, f"type={policy_type}, limit={item['monthly_limit']}")
    return response(201, {"id": pk, **body})


def handle_update_quota(event):
    """PUT /api/quotas/{id} - update quota policy."""
    path = event.get("requestContext", {}).get("http", {}).get("path", "")
    policy_id = path.split("/api/quotas/", 1)[-1]
    body = json.loads(event.get("body", "{}"))

    updates = {}
    if "monthlyLimit" in body:
        updates["monthly_limit"] = {"Value": int(body["monthlyLimit"]), "Action": "PUT"}
    if "dailyLimit" in body:
        updates["daily_limit"] = {"Value": int(body["dailyLimit"]), "Action": "PUT"}
    if "enforcement" in body:
        updates["enforcement_mode"] = {"Value": body["enforcement"], "Action": "PUT"}

    if updates:
        policies_table.update_item(
            Key={"pk": policy_id, "sk": "CURRENT"},
            AttributeUpdates=updates,
        )
    return response(200, {"id": policy_id, "updated": list(updates.keys())})


def handle_delete_quota(event):
    """DELETE /api/quotas/{id} - delete quota policy."""
    path = event.get("requestContext", {}).get("http", {}).get("path", "")
    policy_id = path.split("/api/quotas/", 1)[-1]
    policies_table.delete_item(Key={"pk": policy_id, "sk": "CURRENT"})
    log_audit(get_caller_email(event), "delete_quota", policy_id, "")
    return response(200, {"deleted": policy_id})


def handle_recent_activity(event):
    """GET /api/metrics/activity - recent activity feed for dashboard."""
    now = datetime.now(timezone.utc)
    one_hour_ago = (now - timedelta(hours=1)).isoformat()

    result = metrics_table.query(
        KeyConditionExpression=Key("pk").eq("METRICS") & Key("sk").gte(one_hour_ago),
        Limit=50,
        ScanIndexForward=False,
    )

    activities = []
    for item in result.get("Items", []):
        sk = item.get("sk", "")
        if "#WINDOW#SUMMARY" in sk:
            tokens = int(item.get("total_tokens", 0))
            users = int(item.get("unique_users", 0))
            if tokens > 0:
                activities.append({
                    "timestamp": item.get("timestamp", ""),
                    "type": "usage",
                    "message": f"{users} user(s) consumed {tokens:,} tokens",
                    "tokens": tokens,
                })
        elif "#USER#" in sk:
            email = sk.split("#USER#")[-1]
            activities.append({
                "timestamp": item.get("timestamp", sk.split("#")[0]),
                "type": "session",
                "message": f"{email} active",
                "tokens": 0,
            })

    return response(200, {"activities": activities[:20]})


def handle_audit_log(event):
    """GET /api/audit - admin action audit log."""
    org_id = _get_org_from_event(event)
    _, org_policies, _ = _get_org_tables(org_id)
    if org_policies is None:
        return response(200, {"entries": []})
    try:
        result = org_policies.query(
            KeyConditionExpression=Key("pk").eq("AUDIT"),
            Limit=50,
            ScanIndexForward=False,
        )
    except Exception:
        return response(200, {"entries": []})
    entries = []
    for item in result.get("Items", []):
        entries.append({
            "timestamp": item.get("sk", ""),
            "action": item.get("action", ""),
            "actor": item.get("actor", ""),
            "target": item.get("target", ""),
            "details": item.get("details", ""),
        })
    return response(200, {"entries": entries})


def log_audit(actor: str, action: str, target: str, details: str = ""):
    """Write an audit log entry."""
    now = datetime.now(timezone.utc).isoformat()
    policies_table.put_item(Item={
        "pk": "AUDIT",
        "sk": now,
        "actor": actor,
        "action": action,
        "target": target,
        "details": details,
    })


def handle_slack_connect(event):
    """GET /api/integrations/slack/connect - redirect to Slack OAuth."""
    import urllib.parse
    sm = boto3.client("secretsmanager")
    secret = json.loads(sm.get_secret_value(SecretId="nexus/slack")["SecretString"])
    client_id = secret["client_id"]
    redirect_uri = "https://dtxfifv2cj.execute-api.us-east-1.amazonaws.com/api/integrations/slack/callback"
    scopes = "channels:history,channels:read,users:read,users:read.email,team:read"
    org_id = _get_org_from_event(event)
    state = org_id
    url = f"https://slack.com/oauth/v2/authorize?client_id={client_id}&scope={scopes}&redirect_uri={redirect_uri}&state={state}"
    return {"statusCode": 302, "headers": {"Location": url, "Access-Control-Allow-Origin": "*"}, "body": ""}


def handle_slack_callback(event):
    """GET /api/integrations/slack/callback - exchange code for token."""
    import urllib.request
    params = event.get("queryStringParameters", {}) or {}
    code = params.get("code", "")
    org_id = params.get("state", "allcode")

    if not code:
        return response(400, {"error": "missing code"})

    sm = boto3.client("secretsmanager")
    secret = json.loads(sm.get_secret_value(SecretId="nexus/slack")["SecretString"])
    redirect_uri = "https://dtxfifv2cj.execute-api.us-east-1.amazonaws.com/api/integrations/slack/callback"

    # Exchange code for token
    data = urllib.parse.urlencode({
        "client_id": secret["client_id"],
        "client_secret": secret["client_secret"],
        "code": code,
        "redirect_uri": redirect_uri,
    }).encode()
    req = urllib.request.Request("https://slack.com/api/oauth.v2.access", data=data)
    resp = json.loads(urllib.request.urlopen(req).read())

    if not resp.get("ok"):
        return response(400, {"error": resp.get("error", "oauth failed")})

    # Store token
    token_table = dynamodb.Table("IntegrationTokens")
    token_table.put_item(Item={
        "pk": f"ORG#{org_id}",
        "sk": "slack",
        "access_token": resp["access_token"],
        "team_id": resp.get("team", {}).get("id", ""),
        "team_name": resp.get("team", {}).get("name", ""),
        "bot_user_id": resp.get("bot_user_id", ""),
        "connected_at": datetime.now(timezone.utc).isoformat(),
    })

    # Redirect back to Nexus integrations page
    return {"statusCode": 302, "headers": {"Location": "https://nexus.allcode.com/integrations?connected=slack"}, "body": ""}


def handle_slack_status(event):
    """GET /api/integrations/slack/status - check if Slack is connected."""
    org_id = _get_org_from_event(event)
    token_table = dynamodb.Table("IntegrationTokens")
    try:
        result = token_table.get_item(Key={"pk": f"ORG#{org_id}", "sk": "slack"})
        item = result.get("Item")
        if item:
            return response(200, {"connected": True, "team_name": item.get("team_name", ""), "connected_at": item.get("connected_at", "")})
    except Exception:
        pass
    return response(200, {"connected": False})


def handle_slack_insights(event):
    """GET /api/integrations/slack/insights - activity summary."""
    org_id = _get_org_from_event(event)

    # Check if this org has Slack connected
    token_table = dynamodb.Table("IntegrationTokens")
    try:
        tok_result = token_table.get_item(Key={"pk": f"ORG#{org_id}", "sk": "slack"})
        if not tok_result.get("Item"):
            return response(200, {"total_messages": 0, "active_users": 0, "active_channels": 0, "peak_hour": 0, "top_users": [], "hourly_distribution": {}})
    except Exception:
        return response(200, {"total_messages": 0, "active_users": 0, "active_channels": 0, "peak_hour": 0, "top_users": [], "hourly_distribution": {}})

    metrics = dynamodb.Table("ClaudeCodeMetrics")
    try:
        result = metrics.scan(
            FilterExpression="begins_with(pk, :prefix)",
            ExpressionAttributeValues={":prefix": "SLACK#"},
        )
    except Exception:
        result = {"Items": []}

    items = result.get("Items", [])
    users = {}
    channels = {}
    hours = {}
    for item in items:
        uid = item.get("user_id", "")
        ch = item.get("channel", "")
        ts = item.get("timestamp", "")
        if uid:
            users[uid] = users.get(uid, 0) + 1
        if ch:
            channels[ch] = channels.get(ch, 0) + 1
        if ts:
            try:
                hour = int(float(ts)) % 86400 // 3600
                hours[hour] = hours.get(hour, 0) + 1
            except Exception:
                pass

    # Resolve user IDs to names via Slack API
    token_table = dynamodb.Table("IntegrationTokens")
    slack_token = ""
    try:
        tok_result = token_table.get_item(Key={"pk": f"ORG#{org_id}", "sk": "slack"})
        slack_token = tok_result.get("Item", {}).get("access_token", "")
    except Exception:
        pass

    top_users = sorted(users.items(), key=lambda x: x[1], reverse=True)[:5]
    resolved_users = []
    if slack_token:
        import urllib.request
        for uid, count in top_users:
            try:
                req = urllib.request.Request(f"https://slack.com/api/users.info?user={uid}", headers={"Authorization": f"Bearer {slack_token}"})
                resp = json.loads(urllib.request.urlopen(req).read())
                if resp.get("ok"):
                    profile = resp["user"].get("profile", {})
                    name = profile.get("real_name", resp["user"].get("name", uid))
                    resolved_users.append({"user_id": uid, "name": name, "count": count})
                else:
                    resolved_users.append({"user_id": uid, "name": uid, "count": count})
            except Exception:
                resolved_users.append({"user_id": uid, "name": uid, "count": count})
    else:
        resolved_users = [{"user_id": u, "name": u, "count": c} for u, c in top_users]

    return response(200, {
        "total_messages": len(items),
        "active_users": len(users),
        "active_channels": len(channels),
        "peak_hour": max(hours, key=hours.get) if hours else 0,
        "top_users": resolved_users,
        "hourly_distribution": hours,
    })


def handle_slack_events(event):
    """POST /api/integrations/slack/events - receive Slack webhook events."""
    body = json.loads(event.get("body", "{}"))
    print(f"SLACK EVENT: {json.dumps(body)[:500]}")

    # Slack URL verification challenge
    if body.get("type") == "url_verification":
        return response(200, {"challenge": body.get("challenge", "")})

    # Process events
    slack_event = body.get("event", {})
    if slack_event.get("type") == "message" and not slack_event.get("bot_id"):
        team_id = body.get("team_id", "")
        user_id = slack_event.get("user", "")
        ts = slack_event.get("ts", "")
        # Store activity signal (no message content)
        metrics_table = dynamodb.Table("ClaudeCodeMetrics")
        metrics_table.put_item(Item={
            "pk": f"SLACK#{team_id}",
            "sk": f"{ts}#{user_id}",
            "type": "message",
            "channel": slack_event.get("channel", ""),
            "user_id": user_id,
            "timestamp": ts,
        })
        print(f"SLACK: stored message from {user_id} in {slack_event.get('channel')}")

    return response(200, {"ok": True})


def handle_transform_event(event):
    """Handle EventBridge Transform job state change events."""
    detail = event.get("detail", {})
    job_id = detail.get("jobId", "unknown")
    status = detail.get("status", "UNKNOWN")
    tokens = int(detail.get("tokenCount", 0))
    job_type = detail.get("jobType", "unknown")
    role_arn = detail.get("roleArn", "")
    cost = (tokens / 1_000_000) * 8 * 1.30

    # Store in metrics table
    metrics_table.put_item(Item={
        "pk": f"TRANSFORM#{job_type}",
        "sk": f"{job_id}#{detail.get('completedAt', datetime.now(timezone.utc).isoformat())}",
        "job_type": job_type,
        "tokens": tokens,
        "cost_usd": str(round(cost, 2)),
        "status": status,
        "team_id": detail.get("teamId", ""),
        "timestamp": detail.get("completedAt", datetime.now(timezone.utc).isoformat()),
    })
    return {"statusCode": 200}


def handle_transform_jobs(event):
    """GET /api/transform/jobs - list Transform modernization jobs."""
    # Query known transform job types
    items = []
    job_types = ["python-boto2-to-boto3", "java-version-upgrade", "nodejs-version-upgrade", "custom", "mainframe", "dotnet", "attribution"]
    for jt in job_types:
        try:
            result = metrics_table.query(KeyConditionExpression=Key("pk").eq(f"TRANSFORM#{jt}"))
            items.extend(result.get("Items", []))
        except Exception:
            pass
    # Also try a general scan with limit
    if not items:
        try:
            result = metrics_table.scan(
                FilterExpression="begins_with(pk, :prefix)",
                ExpressionAttributeValues={":prefix": "TRANSFORM#"},
                Limit=100,
            )
            items = result.get("Items", [])
        except Exception:
            pass

    jobs = []
    total_tokens = 0
    total_cost = 0.0
    for item in items:
        tokens = int(item.get("tokens", 0))
        cost = float(item.get("cost_usd", 0))
        total_tokens += tokens
        total_cost += cost
        jobs.append({
            "jobId": item.get("sk", "").split("#")[0] if "#" in item.get("sk", "") else item.get("sk", ""),
            "jobType": item.get("job_type", "unknown"),
            "team": item.get("team_id", ""),
            "tokens": tokens,
            "cost": cost,
            "status": item.get("status", "COMPLETED"),
            "timestamp": item.get("timestamp", ""),
        })

    return response(200, {"jobs": sorted(jobs, key=lambda x: x.get("timestamp", ""), reverse=True), "totalTokens": total_tokens, "totalCost": total_cost})


ROUTES = {
    "GET /api/orgs": handle_list_orgs,
    "GET /api/debug/claims": lambda event: response(200, {"claims": event.get("requestContext", {}).get("authorizer", {}), "headers": list((event.get("headers", {}) or {}).keys()), "email": get_caller_email(event)}),
    "POST /api/request-access": handle_request_access,
    "POST /api/chat": handle_chat,
    "POST /api/orgs/provision": handle_provision_org,
    "GET /api/metrics/summary": handle_summary,
    "GET /api/users": handle_users,
    "GET /api/users/me": handle_user_me,
    "GET /api/quotas": handle_quotas,
    "POST /api/quotas": handle_create_quota,
    "GET /api/config/models": handle_models,
    "GET /api/download": handle_download,
    "GET /api/billing/report": handle_billing_report,
    "GET /api/users/me/activity": handle_activity,
    "GET /api/users/export": handle_export_users,
    "GET /api/config/alerts": handle_get_alerts,
    "POST /api/config/alerts": handle_budget_alerts,
    "GET /api/metrics/activity": handle_recent_activity,
    "GET /api/audit": handle_audit_log,
    "GET /api/transform/jobs": handle_transform_jobs,
    "GET /api/integrations/slack/connect": handle_slack_connect,
    "GET /api/integrations/slack/callback": handle_slack_callback,
    "GET /api/integrations/slack/status": handle_slack_status,
    "GET /api/integrations/slack/insights": handle_slack_insights,
    "POST /api/integrations/slack/events": handle_slack_events,
}


def lambda_handler(event, context):
    """Main Lambda handler - routes requests."""
    # Handle EventBridge Transform events
    if event.get("source") == "aws.transform":
        return handle_transform_event(event)

    method = event.get("requestContext", {}).get("http", {}).get("method", "GET")
    path = event.get("requestContext", {}).get("http", {}).get("path", "")
    route_key = f"{method} {path}"

    # Handle OPTIONS for CORS
    if method == "OPTIONS":
        return response(200, {})

    # Exact match first
    handler = ROUTES.get(route_key)

    # Path-parameter routes for quotas
    if not handler and path.startswith("/api/quotas/"):
        if method == "PUT":
            handler = handle_update_quota
        elif method == "DELETE":
            handler = handle_delete_quota

    # User detail, toggle, and delete
    if not handler and path.startswith("/api/users/") and path != "/api/users/me" and not path.endswith("/activity") and path != "/api/users/export":
        if path.endswith("/toggle") and method == "PUT":
            handler = handle_toggle_user
        elif path.endswith("/reset-password") and method == "PUT":
            handler = handle_reset_password
        elif path.endswith("/resend-invite") and method == "PUT":
            handler = handle_resend_invite
        elif method == "GET":
            handler = handle_user_detail
        elif method == "DELETE":
            handler = handle_delete_user

    # Create user
    if not handler and path == "/api/users" and method == "POST":
        handler = handle_create_user

    # Model config update
    if not handler and path == "/api/config/models" and method == "PUT":
        handler = handle_update_models

    if not handler:
        return response(404, {"error": "Not found", "route": route_key})

    try:
        return handler(event)
    except Exception as e:
        return response(500, {"error": str(e)})
