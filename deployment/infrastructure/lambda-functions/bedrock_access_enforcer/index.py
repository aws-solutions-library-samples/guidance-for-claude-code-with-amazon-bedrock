# ABOUTME: Lambda that blocks over-quota users at the IAM layer by rewriting the
# ABOUTME: DenyBedrock-users inline policy on BedrockOktaFederatedRole every 30 minutes.

"""Bedrock access enforcer.

Runs on a schedule. Fetches the list of users who are at/over their monthly USD spend
quota from the SmartNews quota-usage-export API, converts each user's email into the
exact ``aws:userid`` pattern their STS session uses, and overwrites the single Deny
inline policy on the federated role so those users are blocked from Bedrock.

Design notes:
  * ONE inline policy (``DenyBedrock-users``) with one Deny statement whose
    ``StringLike aws:userid`` list is the full block list. Idempotent: we only call
    PutRolePolicy when the desired list differs from what's currently attached.
  * FAIL-SAFE: any failure fetching/parsing the API re-raises WITHOUT touching the
    policy, so a transient API outage can never silently unblock everyone.
  * The userid rule mirrors credential_provider/__main__.py exactly: the STS
    RoleSessionName is ``claude-code-<sanitized local-part, truncated to 32 chars>``,
    so aws:userid ends with that. See ``userid_for_email``.
  * Slack: on a successful run that changes the block list, post the newly blocked /
    unblocked users to a channel. On any error, post a sanitized message (no secrets,
    no stack traces) and re-raise so the invocation still shows as failed.

Stdlib + boto3 only (both present in the Lambda python3.12 runtime) — no packaging.
"""

import json
import os
import re
import urllib.request

import boto3

# --- Configuration (from environment) ---------------------------------------
TARGET_ROLE_NAME = os.environ.get("TARGET_ROLE_NAME", "BedrockOktaFederatedRole")
DENY_POLICY_NAME = os.environ.get("DENY_POLICY_NAME", "DenyBedrock-users")
QUOTA_API_URL = os.environ["QUOTA_API_URL"]  # e.g. https://.../api/quota-usage-export
BLOCK_THRESHOLD_PERCENT = os.environ.get("BLOCK_THRESHOLD_PERCENT", "100")
SECRET_ID = os.environ.get("SECRET_ID", "shared/claude-code-quota-api-token")
SECRET_JSON_KEY = os.environ.get("SECRET_JSON_KEY", "quota_api_token")
HTTP_TIMEOUT_SECONDS = int(os.environ.get("HTTP_TIMEOUT_SECONDS", "10"))

# Slack (optional). If SLACK_CHANNEL is unset, Slack notifications are skipped.
SLACK_SECRET_ID = os.environ.get("SLACK_SECRET_ID", "shared/claude-code-alerts-slack-bot-token")
SLACK_SECRET_JSON_KEY = os.environ.get("SLACK_SECRET_JSON_KEY", "slack_bot_token")
SLACK_CHANNEL = os.environ.get("SLACK_CHANNEL", "")

# Sentinel userid used when nobody is over quota. IAM rejects an empty StringLike list,
# and this value can never match a real session name (`__none__` is not a valid email
# local part shape we'd ever produce), so the Deny statement stays valid but inert.
NONE_SENTINEL = "*:claude-code-__none__"

# Matches RoleSessionName sanitization in credential_provider/__main__.py:
#   email_part = email.split("@")[0][:32]
#   re.sub(r"[^\w+=,.@-]", "-", email_part)
_INVALID_SESSION_CHARS = re.compile(r"[^\w+=,.@-]")

iam = boto3.client("iam")
_secrets = boto3.client("secretsmanager")


def userid_for_email(email):
    """Return the ``aws:userid`` StringLike pattern for a user's email.

    Must stay byte-for-byte identical to the RoleSessionName logic in
    credential_provider/__main__.py, or the Deny won't match the user's session.
    """
    local_part = email.split("@")[0][:32]
    sanitized = _INVALID_SESSION_CHARS.sub("-", local_part)
    return f"*:claude-code-{sanitized}"


def _secret_json(secret_id, json_key):
    """Fetch a secret and return the value at ``json_key`` (or the raw string)."""
    resp = _secrets.get_secret_value(SecretId=secret_id)
    secret_string = resp["SecretString"]
    try:
        data = json.loads(secret_string)
    except (ValueError, TypeError):
        return secret_string.strip()
    if isinstance(data, dict):
        return data[json_key]
    return str(data)


def get_api_token():
    """Fetch the bearer token for the quota API from Secrets Manager."""
    return _secret_json(SECRET_ID, SECRET_JSON_KEY)


def fetch_over_quota_emails(token):
    """Call the quota-usage-export API and return the list of over-threshold emails.

    Raises on any non-200 / network / parse error (fail-safe: caller must not modify
    the policy when this raises).
    """
    url = f"{QUOTA_API_URL}?min_percent={BLOCK_THRESHOLD_PERCENT}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_SECONDS) as resp:
        if resp.status != 200:
            raise RuntimeError(f"Quota API returned HTTP {resp.status}")
        payload = json.loads(resp.read().decode("utf-8"))

    rows = payload.get("rows", [])
    emails = []
    for row in rows:
        email = (row.get("email") or "").strip()
        if email:
            emails.append(email)
    return emails


def build_deny_document(userids):
    """Build the DenyBedrock-users policy document for the given userid list."""
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "DenyBedrockOverQuota",
                "Effect": "Deny",
                "Action": "bedrock:*",
                "Resource": "*",
                "Condition": {"StringLike": {"aws:userid": userids}},
            }
        ],
    }


def _current_userids():
    """Return the sorted userid list currently in the deny policy, or None if absent."""
    try:
        resp = iam.get_role_policy(RoleName=TARGET_ROLE_NAME, PolicyName=DENY_POLICY_NAME)
    except iam.exceptions.NoSuchEntityException:
        return None
    doc = resp["PolicyDocument"]
    # boto3 returns the policy document as a dict (already URL-decoded).
    for stmt in doc.get("Statement", []):
        cond = stmt.get("Condition", {}).get("StringLike", {})
        ids = cond.get("aws:userid")
        if ids is not None:
            if isinstance(ids, str):
                ids = [ids]
            return sorted(ids)
    return []


def desired_userids(emails):
    """Map emails -> sorted, de-duplicated userid list (with sentinel if empty)."""
    userids = sorted({userid_for_email(e) for e in emails})
    return userids or [NONE_SENTINEL]


def _userid_to_label(userid):
    """Strip the ``*:claude-code-`` prefix for a human-readable Slack label."""
    return userid.replace("*:claude-code-", "", 1)


def post_slack(text):
    """Best-effort Slack post to SLACK_CHANNEL. Never raises (logs on failure)."""
    if not SLACK_CHANNEL:
        return
    try:
        token = _secret_json(SLACK_SECRET_ID, SLACK_SECRET_JSON_KEY)
        body = json.dumps({"channel": SLACK_CHANNEL, "text": text}).encode("utf-8")
        req = urllib.request.Request(
            "https://slack.com/api/chat.postMessage",
            data=body,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json; charset=utf-8",
            },
        )
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_SECONDS) as resp:
            result = json.loads(resp.read().decode("utf-8"))
        if not result.get("ok"):
            # Slack API errors (e.g. "channel_not_found") are not sensitive.
            print(f"bedrock-access-enforcer: slack post failed: {result.get('error')}")
    except Exception as exc:  # noqa: BLE001 - notifications must never break enforcement
        print(f"bedrock-access-enforcer: slack post error: {type(exc).__name__}")


def _notify_change(added, removed, total_blocked):
    """Post a Slack message describing the block-list change.

    ``total_blocked`` is the number of users blocked *after* this run (excludes the
    sentinel), reported in the header so the message isn't just an ambiguous delta.

    Pure reformat churn is suppressed: if a removed userid maps to the same person
    (same label) as an added userid — e.g. correcting ``*:claude-code-tomita@czukay.jp``
    to ``*:claude-code-tomita`` — it is NOT reported as an unblock, because the person's
    effective access didn't change. Only genuine adds/drops are shown.
    """
    added_labels = {_userid_to_label(u) for u in added if u != NONE_SENTINEL}
    removed_labels = {_userid_to_label(u) for u in removed if u != NONE_SENTINEL}
    newly_blocked = sorted(added_labels - removed_labels)
    newly_unblocked = sorted(removed_labels - added_labels)
    if not newly_blocked and not newly_unblocked:
        return
    lines = [
        f":lock: *Bedrock access enforcement* — now blocking {total_blocked} "
        f"user{'s' if total_blocked != 1 else ''} (threshold {BLOCK_THRESHOLD_PERCENT}%)"
    ]
    if newly_blocked:
        lines.append(f"*Newly blocked ({len(newly_blocked)}):* " + ", ".join(newly_blocked))
    if newly_unblocked:
        lines.append(f"*Newly unblocked ({len(newly_unblocked)}):* " + ", ".join(newly_unblocked))
    post_slack("\n".join(lines))


def _enforce(event, context):
    token = get_api_token()

    # FAIL-SAFE: if this raises, we never touch the policy.
    emails = fetch_over_quota_emails(token)
    desired = desired_userids(emails)

    current = _current_userids()
    print(
        f"bedrock-access-enforcer: threshold={BLOCK_THRESHOLD_PERCENT}% "
        f"over_quota_users={len(emails)} desired_userids={len(desired)} "
        f"current_userids={0 if current is None else len(current)}"
    )

    if current is not None and current == desired:
        print("bedrock-access-enforcer: no change; policy already up to date")
        return {"statusCode": 200, "changed": False, "blocked": len([u for u in desired if u != NONE_SENTINEL])}

    added = sorted(set(desired) - set(current or []))
    removed = sorted(set(current or []) - set(desired))
    if added:
        print(f"bedrock-access-enforcer: adding {added}")
    if removed:
        print(f"bedrock-access-enforcer: removing {removed}")

    iam.put_role_policy(
        RoleName=TARGET_ROLE_NAME,
        PolicyName=DENY_POLICY_NAME,
        PolicyDocument=json.dumps(build_deny_document(desired)),
    )
    print(f"bedrock-access-enforcer: updated {DENY_POLICY_NAME} on {TARGET_ROLE_NAME}")

    total_blocked = len([u for u in desired if u != NONE_SENTINEL])
    _notify_change(added, removed, total_blocked)

    return {
        "statusCode": 200,
        "changed": True,
        "blocked": total_blocked,
        "added": added,
        "removed": removed,
    }


def lambda_handler(event, context):
    try:
        return _enforce(event, context)
    except Exception as exc:
        # Notify Slack with a sanitized message (type + short str, no traceback,
        # no secrets), then re-raise so the invocation is marked failed and the
        # deny policy is left untouched.
        detail = str(exc)[:200]
        post_slack(
            f":warning: *Bedrock access enforcement failed* — {type(exc).__name__}: {detail}\n"
            "Block list left unchanged (fail-safe)."
        )
        raise
