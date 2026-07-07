import os
import json
import base64
import hmac
import hashlib
import time
import html as html_module
import urllib.request
import urllib.parse
import boto3

s3_client = boto3.client('s3')
bedrock_client = boto3.client('bedrock')
sso_admin_client = boto3.client('sso-admin')
identity_store_client = boto3.client('identitystore')
secretsmanager_client = boto3.client('secretsmanager')

BUCKET_NAME = os.environ['S3_BUCKET_NAME']
COGNITO_DOMAIN = os.environ['COGNITO_DOMAIN']
COGNITO_CLIENT_ID = os.environ['COGNITO_CLIENT_ID']
COGNITO_USER_POOL_ID = os.environ.get('COGNITO_USER_POOL_ID', '')
COGNITO_BOOTSTRAP_CLIENT_ID = os.environ.get('COGNITO_BOOTSTRAP_CLIENT_ID', '')
REGION = os.environ['REGION']
ADMIN_GROUP = os.environ.get('ADMIN_GROUP', 'Claude-Code-Admins')
SESSION_SIGNING_SECRET_ARN = os.environ.get('SESSION_SIGNING_SECRET_ARN', '')
PRESIGNED_URL_EXPIRY = 3600

_session_signing_secret_cache = None


def _get_session_signing_secret():
    """Fetch (and cache for the life of the execution environment) the HMAC
    key used to sign session cookies. Cached at module scope so we only call
    Secrets Manager once per warm Lambda instance, not once per request."""
    global _session_signing_secret_cache
    if _session_signing_secret_cache is None:
        if not SESSION_SIGNING_SECRET_ARN:
            raise RuntimeError('SESSION_SIGNING_SECRET_ARN is not configured')
        response = secretsmanager_client.get_secret_value(SecretId=SESSION_SIGNING_SECRET_ARN)
        _session_signing_secret_cache = response['SecretString'].encode('utf-8')
    return _session_signing_secret_cache


def _sign(payload_b64: str) -> str:
    """HMAC-SHA256 sign a base64url payload, return a base64url signature."""
    key = _get_session_signing_secret()
    digest = hmac.new(key, payload_b64.encode('utf-8'), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip('=')


def esc(value) -> str:
    """HTML-escape a value before interpolating it into an HTML response.

    Use this for any data that isn't a hardcoded string literal, including
    JWT/session-derived values (email, name) and IDC-sourced display names
    (groups, permission set names) - none of these should be trusted as
    pre-sanitized HTML.
    """
    return html_module.escape(str(value), quote=True)


def internal_error_response(status_code=500):
    """A generic error response safe to return to any caller (including
    admins). Real exception detail (which can contain S3 bucket names,
    ARNs, or other AWS resource identifiers) belongs in CloudWatch logs via
    print(), never in the HTTP response body."""
    return json_response({'error': 'An internal error occurred. Please try again later.'}, status_code)


def log_safe(value) -> str:
    """Strip newlines/carriage-returns from a value before logging it.

    Prevents an attacker-controlled string (e.g. a JWT/session email claim)
    from injecting fake log lines or breaking CloudWatch log parsing by
    embedding '\\n[INFO] fake message' sequences.
    """
    return str(value).replace('\n', ' ').replace('\r', ' ')


def verify_request_origin(headers, base_url):
    """CSRF defense-in-depth: verify a state-changing request's Origin (or
    Referer, as a fallback) header matches our own base_url.

    SameSite=Lax on the session cookie already blocks classic cross-site
    form-based CSRF, but doesn't protect against every cross-site vector
    (e.g. a request from a sibling subdomain sharing the same eTLD+1, or
    browser SameSite bugs/misconfigurations). This is a second, independent
    layer: a same-origin browser request will always carry a matching
    Origin header for POST requests; a cross-site request will not.
    """
    expected = base_url.rstrip('/')
    # A degenerate/empty base_url (e.g. no Host header resolved) must never
    # match - otherwise `origin.startswith(expected)` would be trivially
    # true for any origin, defeating the whole check.
    if not expected or not expected.startswith(('http://', 'https://')):
        return False

    origin = headers.get('Origin', headers.get('origin', ''))
    if not origin:
        origin = headers.get('Referer', headers.get('referer', ''))
    if not origin:
        # No Origin/Referer at all - reject rather than fail open. Browsers
        # always send Origin on cross-origin and same-origin POST requests.
        return False
    return origin.rstrip('/') == expected or origin.rstrip('/').startswith(expected + '/')


def lambda_handler(event, context):
    """Handle API Gateway requests"""
    try:
        path = event.get('path', '/')
        query_params = event.get('queryStringParameters') or {}
        headers = event.get('headers', {})
        http_method = event.get('httpMethod', 'GET')
        body = event.get('body', '')

        cloudfront_domain = os.environ.get('CLOUDFRONT_DOMAIN', '')
        if cloudfront_domain:
            base_url = f"https://{cloudfront_domain}"
        else:
            host = headers.get('Host', headers.get('host', ''))
            base_url = f"https://{host}"

        if path == '/callback':
            code = query_params.get('code')
            if code:
                return handle_callback(code, base_url)
            else:
                return redirect_to_login(base_url)

        if path == '/logout':
            return handle_logout(base_url)

        cookie_header = headers.get('Cookie', headers.get('cookie', ''))
        cookies = parse_cookies(cookie_header)
        session_token = cookies.get('session')

        # Bootstrap API endpoint - returns dynamic config for Claude Desktop
        # Auth methods: OIDC JWT (bootstrapOidc) or session cookie
        if path == '/api/bootstrap':
            # OIDC JWT auth (Claude Desktop with bootstrapOidc)
            auth_header = headers.get('Authorization', headers.get('authorization', ''))
            if auth_header.startswith('Bearer '):
                return api_bootstrap_with_jwt(auth_header[7:])

            # Session cookie auth (browser)
            if session_token:
                user_info = validate_session(session_token)
                if user_info:
                    return api_bootstrap(user_info, base_url)

            return json_response({'error': 'Authentication required', 'code': 'UNAUTHENTICATED'}, 401)

        if not session_token:
            return redirect_to_login(base_url)

        user_info = validate_session(session_token)
        if not user_info:
            return redirect_to_login(base_url)

        if path.startswith('/download/'):
            platform = path.split('/download/', 1)[-1].strip('/')
            return handle_download(platform, user_info)

        if path.startswith('/admin'):
            user_email = user_info.get('email', '')
            # Always look up groups from IDC
            user_groups = get_user_idc_groups(user_email) if user_email else []
            is_admin = any(ADMIN_GROUP.lower() == g.lower() for g in user_groups)
            if not is_admin:
                return {
                    'statusCode': 403,
                    'headers': {'Content-Type': 'text/html'},
                    'body': f'<html><body><h1>Access Denied</h1><p>Admin access required</p><p>Email: {esc(user_email)}</p><p>Groups: {esc(user_groups)}</p><p><a href="/">Back</a></p></body></html>'
                }

            # CSRF defense-in-depth for state-changing requests: SameSite=Lax
            # on the session cookie already blocks classic cross-site form
            # POSTs, but doesn't cover every cross-site scenario (e.g. a
            # sibling subdomain on the same eTLD+1). Require the request's
            # Origin to match our own domain for any admin POST.
            if http_method == 'POST' and not verify_request_origin(headers, base_url):
                return json_response({'error': 'Invalid request origin'}, 403)

            if path == '/admin':
                return serve_admin_page(user_info, base_url)
            elif path == '/admin/api/groups':
                return api_list_groups()
            elif path == '/admin/api/models':
                return api_list_models()
            elif path == '/admin/api/config':
                if http_method == 'GET':
                    return api_get_config()
                elif http_method == 'POST':
                    return api_save_config(body)
            elif path == '/admin/api/permission-sets':
                return api_list_permission_sets()
            elif path.startswith('/admin/api/permission-set/'):
                ps_name = path.split('/admin/api/permission-set/')[-1]
                return api_get_permission_set_details(ps_name)
            elif path == '/admin/api/deploy':
                if http_method == 'POST':
                    return api_deploy_config(body, base_url)

        return serve_landing_page(user_info, base_url)

    except Exception:
        import traceback
        print(f"Error: {traceback.format_exc()}")
        # Never leak internal exception detail (AWS resource names, ARNs,
        # IAM error messages) to the caller - this handler wraps every
        # request including unauthenticated ones. Full detail is in
        # CloudWatch logs above for debugging.
        return {
            'statusCode': 500,
            'headers': {'Content-Type': 'text/html'},
            'body': '<html><body><h1>Internal Server Error</h1><p>Something went wrong. Please try again later.</p></body></html>'
        }


def build_bootstrap_managed_mcp_servers(stored_config):
    """Build the managedMcpServers list for a bootstrap response.

    Bootstrap responses can only deliver network-based MCP servers (http/sse
    transport) - Claude Desktop drops stdio-transport entries returned via
    bootstrap as a security measure (a remote response cannot nominate local
    code to run). Local/stdio servers must be delivered via MDM instead.

    This combines two sources from the stored group config:
      - managedMcpServers already in http/sse form (e.g. AWS Knowledge MCP,
        AgentCore Gateway-backed servers) - passed through as-is.
      - mcpServerTemplates (stdio, local command+args) - converted to stdio
        managedMcpServers entries for MDM/mobileconfig generation elsewhere,
        but harmless to include here too since Desktop will drop them.

    Args:
        stored_config: The group's bootstrap.json / admin config dict

    Returns:
        List of managedMcpServers entries, or [] if none configured
    """
    result = []

    for server in stored_config.get('managedMcpServers') or []:
        if isinstance(server, dict) and server.get('transport') in ('http', 'sse'):
            result.append(server)

    for server in stored_config.get('mcpServerTemplates') or []:
        mcp_entry = {
            "name": server.get('name', 'unnamed'),
            "transport": "stdio",
            "command": server.get('command', ''),
            "args": server.get('args', []),
        }
        if server.get('env'):
            mcp_entry["env"] = server['env']
        result.append(mcp_entry)

    return result


def parse_cookies(cookie_header):
    cookies = {}
    if cookie_header:
        for item in cookie_header.split(';'):
            if '=' in item:
                key, value = item.strip().split('=', 1)
                cookies[key] = value
    return cookies


def redirect_to_login(base_url):
    login_url = (
        f"https://{COGNITO_DOMAIN}/login?"
        f"client_id={COGNITO_CLIENT_ID}&"
        f"response_type=code&"
        f"scope=openid+email+profile&"
        f"redirect_uri={urllib.parse.quote(base_url + '/callback')}"
    )
    return {
        'statusCode': 302,
        'headers': {'Location': login_url},
        'body': ''
    }


def handle_logout(base_url):
    """Clear session and show logout confirmation with instructions"""
    # Get IDC portal URL
    idc_portal_url = ""
    idc_logout_url = ""
    try:
        instances = sso_admin_client.list_instances()
        if instances.get('Instances'):
            identity_store_id = instances['Instances'][0].get('IdentityStoreId', '')
            if identity_store_id:
                idc_portal_url = f"https://{identity_store_id}.awsapps.com/start"
                idc_logout_url = f"https://{identity_store_id}.awsapps.com/start/#/signout"
    except Exception:
        pass

    # Cognito logout URL - clears Cognito session and redirects back
    cognito_logout_url = (
        f"https://{COGNITO_DOMAIN}/logout?"
        f"client_id={COGNITO_CLIENT_ID}&"
        f"logout_uri={urllib.parse.quote(base_url + '/logout-complete')}"
    )

    html = f'''<!DOCTYPE html>
<html>
<head>
    <title>Logged Out</title>
    <style>
        body {{ font-family: -apple-system, sans-serif; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); }}
        .logout-box {{ background: white; padding: 40px; border-radius: 12px; box-shadow: 0 4px 20px rgba(0,0,0,0.2); text-align: center; max-width: 450px; }}
        h2 {{ margin-bottom: 20px; color: #333; }}
        p {{ color: #666; margin-bottom: 15px; line-height: 1.6; }}
        .btn {{ display: inline-block; background: #667eea; color: white; padding: 12px 24px; border-radius: 8px; text-decoration: none; margin: 8px 5px; font-size: 14px; }}
        .btn:hover {{ background: #5a6fd6; }}
        .btn-outline {{ background: white; color: #667eea; border: 2px solid #667eea; }}
        .btn-outline:hover {{ background: #f5f5ff; }}
        .btn-warning {{ background: #ff9800; }}
        .btn-warning:hover {{ background: #f57c00; }}
        .divider {{ margin: 20px 0; padding-top: 20px; border-top: 1px solid #eee; }}
        .note {{ font-size: 13px; color: #888; line-height: 1.5; }}
        .switch-user {{ background: #fff3e0; border: 1px solid #ffcc80; border-radius: 8px; padding: 16px; margin-top: 20px; }}
        .switch-user h3 {{ color: #e65100; font-size: 14px; margin: 0 0 10px 0; }}
    </style>
</head>
<body>
    <div class="logout-box">
        <h2>Logged Out</h2>
        <p>You have been logged out of this application.</p>
        <a href="{base_url}" class="btn">Sign In Again</a>

        {f"""<div class="switch-user">
            <h3>Want to sign in as a different user?</h3>
            <p class="note">To switch accounts, you need to sign out from IAM Identity Center first:</p>
            <a href="{idc_logout_url}" class="btn btn-warning" target="_blank" onclick="setTimeout(function(){{ window.location.href='{base_url}'; }}, 2000);">
                Sign Out from SSO &amp; Switch User
            </a>
            <p class="note" style="margin-top: 12px; font-size: 12px;">
                This opens the IDC sign-out page. Once complete, you'll be redirected back to sign in with a different account.
            </p>
        </div>""" if idc_logout_url else ''}
    </div>
</body>
</html>'''

    return {
        'statusCode': 200,
        'headers': {
            'Content-Type': 'text/html',
            'Set-Cookie': 'session=; Path=/; Secure; HttpOnly; SameSite=Lax; Max-Age=0'
        },
        'body': html
    }


def handle_callback(code, base_url):
    token_url = f"https://{COGNITO_DOMAIN}/oauth2/token"

    data = urllib.parse.urlencode({
        'grant_type': 'authorization_code',
        'client_id': COGNITO_CLIENT_ID,
        'code': code,
        'redirect_uri': base_url + '/callback'
    }).encode('utf-8')

    req = urllib.request.Request(token_url, data=data, method='POST')
    req.add_header('Content-Type', 'application/x-www-form-urlencoded')

    try:
        # URL is built from COGNITO_DOMAIN (a deploy-time env var set by our own
        # CDK stack), not from request input — no attacker-controlled scheme/host.
        with urllib.request.urlopen(req, timeout=10) as response:  # nosec B310
            tokens = json.loads(response.read().decode('utf-8'))
    except Exception as e:
        print(f"Token exchange failed: {e}")
        return redirect_to_login(base_url)

    # Verify the access token against Cognito itself (signature, expiry, and
    # revocation are all checked server-side by Cognito) rather than trusting
    # a locally-decoded, unverified JWT payload.
    access_token = tokens.get('access_token', '')
    user_info = verify_cognito_access_token(access_token)
    if not user_info:
        return redirect_to_login(base_url)

    email = user_info.get('email', '')
    name = user_info.get('name', '')
    if not email:
        return redirect_to_login(base_url)

    # Group membership is always resolved server-side from IDC (see
    # get_user_idc_groups) rather than trusted from any token claim, so we
    # don't need to store groups in the session at all.
    session_token = create_session_token(email=email, name=name, ttl_seconds=3600)

    return {
        'statusCode': 302,
        'headers': {
            'Location': base_url,
            'Set-Cookie': f'session={session_token}; Path=/; Secure; HttpOnly; SameSite=Lax; Max-Age=3600'
        },
        'body': ''
    }


def create_session_token(email: str, name: str = '', ttl_seconds: int = 3600) -> str:
    """Build an HMAC-signed session token: base64url(payload).base64url(signature).

    The payload is never trusted without verifying the signature first (see
    validate_session), so this is not forgeable without the signing secret.
    """
    payload = json.dumps({'email': email, 'name': name, 'exp': int(time.time()) + ttl_seconds})
    payload_b64 = base64.urlsafe_b64encode(payload.encode()).decode().rstrip('=')
    signature_b64 = _sign(payload_b64)
    return f"{payload_b64}.{signature_b64}"


def verify_cognito_access_token(access_token):
    """Verify a Cognito access token by calling Cognito's own OIDC userInfo
    endpoint (GET /oauth2/userInfo).

    This validates the token's signature, expiry, and revocation status
    server-side (Cognito rejects expired/revoked/malformed tokens with a
    non-2xx response), rather than locally parsing an unverified JWT
    payload. Deliberately NOT using the GetUser API here: it requires the
    reserved 'aws.cognito.signin.user.admin' scope, which our app clients
    don't (and shouldn't need to) request - userInfo only requires the
    'openid' scope already present on every token we issue.

    Returns a dict with 'email' and 'username' on success, or None if the
    token is invalid.
    """
    if not access_token:
        return None

    req = urllib.request.Request(f"https://{COGNITO_DOMAIN}/oauth2/userInfo", method='GET')
    req.add_header('Authorization', f'Bearer {access_token}')

    try:
        # URL is built from COGNITO_DOMAIN (a deploy-time env var set by our own
        # CDK stack), not from request input — no attacker-controlled scheme/host.
        with urllib.request.urlopen(req, timeout=10) as response:  # nosec B310
            user_attrs = json.loads(response.read().decode('utf-8'))
    except Exception as e:
        print(f"Access token verification failed: {e}")
        return None

    return {
        'email': user_attrs.get('email', ''),
        'username': user_attrs.get('username', user_attrs.get('sub', '')),
    }


def validate_session(session_token):
    """Verify an HMAC-signed session token created by create_session_token().

    Returns the decoded payload dict if the signature is valid and the token
    has not expired, otherwise None.
    """
    try:
        payload_b64, signature_b64 = session_token.split('.', 1)
    except ValueError:
        return None

    expected_signature = _sign(payload_b64)
    if not hmac.compare_digest(signature_b64, expected_signature):
        return None

    try:
        padded = payload_b64 + '=' * (-len(payload_b64) % 4)
        session_data = json.loads(base64.urlsafe_b64decode(padded))
    except Exception:
        return None

    if session_data.get('exp', 0) < time.time():
        return None

    return session_data


def get_user_idc_groups(email):
    """Look up user's groups from IAM Identity Center by email"""
    try:
        instances = sso_admin_client.list_instances()
        if not instances.get('Instances'):
            print("No IDC instances found")
            return []

        identity_store_id = instances['Instances'][0]['IdentityStoreId']

        # Extract username from email (part before @)
        username = email.split('@')[0] if '@' in email else email

        # Find user by username
        users = identity_store_client.list_users(
            IdentityStoreId=identity_store_id,
            Filters=[{'AttributePath': 'UserName', 'AttributeValue': username}]
        )

        if not users.get('Users'):
            # Also try full email as username
            users = identity_store_client.list_users(
                IdentityStoreId=identity_store_id,
                Filters=[{'AttributePath': 'UserName', 'AttributeValue': email}]
            )

        if not users.get('Users'):
            print(f"No user found for username: {log_safe(username)} or email: {log_safe(email)}")
            return []

        user_id = users['Users'][0]['UserId']
        print(f"Found user {log_safe(username)} with ID {user_id}")

        # Get group memberships
        memberships = identity_store_client.list_group_memberships_for_member(
            IdentityStoreId=identity_store_id,
            MemberId={'UserId': user_id}
        )

        groups = []
        for membership in memberships.get('GroupMemberships', []):
            group_id = membership['GroupId']
            try:
                group = identity_store_client.describe_group(
                    IdentityStoreId=identity_store_id,
                    GroupId=group_id
                )
                groups.append(group['DisplayName'])
            except Exception:
                pass

        print(f"User {log_safe(username)} groups: {groups}")
        return groups
    except Exception as e:
        print(f"Error getting IDC groups: {e}")
        import traceback
        traceback.print_exc()
        return []


def _group_name_matches_config_key(config_key: str, group_name: str) -> bool:
    """True if an IDC group display name corresponds to a config_key, using
    the same loose matching used when config_keys were derived from group
    names elsewhere in this file (see e.g. generate_mdm_configs)."""
    gk = group_name.lower()
    ck = config_key.lower()
    return ck in gk or gk.replace('-', '').replace('_', '') in ck.replace('-', '')


def get_authorized_config_keys(user_email, all_config_keys):
    """Resolve which config_keys a user is authorized to see/download.

    Fails closed: a user whose IDC group lookup returns nothing is
    authorized for nothing, not everything. Admins (exact ADMIN_GROUP
    match) are authorized for every config_key unconditionally.
    """
    user_groups = []
    if user_email and user_email != 'authenticated-user':
        user_groups = get_user_idc_groups(user_email)

    is_admin = any(ADMIN_GROUP.lower() == g.lower() for g in user_groups)
    if is_admin:
        return set(all_config_keys), True

    authorized = set()
    for config_key in all_config_keys:
        if any(_group_name_matches_config_key(config_key, ug) for ug in user_groups):
            authorized.add(config_key)
    return authorized, False


def serve_landing_page(user_info, base_url):
    user_email = user_info.get('email', 'authenticated-user')

    config_groups = list_config_groups()
    authorized_keys, is_admin = get_authorized_config_keys(user_email, config_groups.keys())

    user_config_groups = {
        key: group_info for key, group_info in config_groups.items() if key in authorized_keys
    }

    html = generate_landing_page(user_email, user_config_groups, is_admin)

    return {
        'statusCode': 200,
        'headers': {'Content-Type': 'text/html; charset=utf-8'},
        'body': html
    }


def handle_download(platform, user_info):
    """Serve a presigned download URL for a group's MDM config file.

    Requires a valid session (enforced by the caller in lambda_handler) AND
    that the caller is authorized for the specific config_key requested -
    either as an admin, or as a member of the corresponding IDC group. This
    prevents any authenticated user from downloading every other group's
    MDM profile (which contains AWS account ID, IDC SSO details, bootstrap
    OIDC client config, and tool/MCP policies) just by guessing config_keys.
    """
    parts = platform.rsplit('-', 1)
    if len(parts) != 2:
        return {
            'statusCode': 404,
            'headers': {'Content-Type': 'text/html'},
            'body': '<html><body><h1>File not available</h1></body></html>'
        }

    config_key, fmt = parts
    format_map = {
        'json': ('default.json', f'{config_key}-config.json'),
        'macos': ('Claude.mobileconfig', f'Claude-{config_key}.mobileconfig'),
        'windows': ('Claude.reg', f'Claude-{config_key}.reg'),
    }
    if fmt not in format_map:
        return {
            'statusCode': 404,
            'headers': {'Content-Type': 'text/html'},
            'body': '<html><body><h1>File not available</h1></body></html>'
        }

    user_email = user_info.get('email', '')
    authorized_keys, _is_admin = get_authorized_config_keys(user_email, [config_key])
    if config_key not in authorized_keys:
        return {
            'statusCode': 403,
            'headers': {'Content-Type': 'text/html'},
            'body': '<html><body><h1>Access Denied</h1><p>You are not authorized to download this configuration.</p></body></html>'
        }

    file_name, download_name = format_map[fmt]
    # download_name embeds config_key in a Content-Disposition header value;
    # strip characters that could break out of the quoted filename.
    download_name = download_name.replace('"', '').replace('\r', '').replace('\n', '')
    s3_key = f"config/{config_key}/{file_name}"
    try:
        s3_client.head_object(Bucket=BUCKET_NAME, Key=s3_key)
        url = s3_client.generate_presigned_url(
            'get_object',
            Params={
                'Bucket': BUCKET_NAME,
                'Key': s3_key,
                'ResponseContentDisposition': f'attachment; filename="{download_name}"',
            },
            ExpiresIn=PRESIGNED_URL_EXPIRY
        )
        return {
            'statusCode': 302,
            'headers': {'Location': url},
            'body': ''
        }
    except Exception as e:
        print(f"Error downloading {s3_key}: {e}")
        return {
            'statusCode': 404,
            'headers': {'Content-Type': 'text/html'},
            'body': '<html><body><h1>File not available</h1></body></html>'
        }


def list_config_groups():
    """List all config groups from S3, getting model info from permission sets"""
    groups = {}

    # Build model lookup from permission sets
    model_by_group = {}
    try:
        instances = sso_admin_client.list_instances()
        if instances.get('Instances'):
            instance_arn = instances['Instances'][0]['InstanceArn']
            identity_store_id = instances['Instances'][0]['IdentityStoreId']
            account_id = boto3.client('sts').get_caller_identity()['Account']

            # Get all permission sets and their group assignments
            paginator = sso_admin_client.get_paginator('list_permission_sets')
            for page in paginator.paginate(InstanceArn=instance_arn):
                for ps_arn in page.get('PermissionSets', []):
                    try:
                        # Get assignments for this permission set
                        assignments = sso_admin_client.list_account_assignments(
                            InstanceArn=instance_arn,
                            AccountId=account_id,
                            PermissionSetArn=ps_arn
                        )
                        group_ids = [a['PrincipalId'] for a in assignments.get('AccountAssignments', [])
                                     if a.get('PrincipalType') == 'GROUP']

                        if not group_ids:
                            continue

                        # Get models from inline policy - extract inference profile IDs
                        model_names = []
                        try:
                            policy_response = sso_admin_client.get_inline_policy_for_permission_set(
                                InstanceArn=instance_arn,
                                PermissionSetArn=ps_arn
                            )
                            if policy_response.get('InlinePolicy'):
                                policy = json.loads(policy_response['InlinePolicy'])
                                for stmt in policy.get('Statement', []):
                                    if stmt.get('Sid') == 'AllowBedrockModel':
                                        resources = stmt.get('Resource', [])
                                        if isinstance(resources, str):
                                            resources = [resources]
                                        # Extract unique inference profile IDs from resources
                                        # Look for cross-region profiles (us. or global.)
                                        seen_profiles = set()
                                        for resource in resources:
                                            # Match inference-profile ARNs: arn:aws:bedrock:*:*:inference-profile/us.anthropic.claude-*
                                            import re
                                            match = re.search(r'inference-profile/((?:us|global)\.anthropic\.[^*]+)', resource)
                                            if match:
                                                profile_id = match.group(1)
                                                if profile_id in seen_profiles:
                                                    continue
                                                seen_profiles.add(profile_id)
                                                # Look up actual name from Bedrock
                                                try:
                                                    profile_resp = bedrock_client.get_inference_profile(inferenceProfileIdentifier=profile_id)
                                                    profile_name = profile_resp.get('inferenceProfileName', profile_id)
                                                    model_names.append(profile_name)
                                                except Exception:
                                                    # Fallback: format the ID nicely
                                                    model_names.append(profile_id)
                                        break
                        except Exception:
                            pass

                        # Map group IDs to group names and config keys
                        for gid in group_ids:
                            try:
                                group = identity_store_client.describe_group(
                                    IdentityStoreId=identity_store_id,
                                    GroupId=gid
                                )
                                group_name = group.get('DisplayName', '')
                                # Convert "Claude-Code-Developers" -> "developer"
                                config_key = group_name.lower().replace('claude-code-', '').replace('claude-', '').replace(' ', '-')
                                # Remove trailing 's' for consistency
                                if config_key.endswith('s') and len(config_key) > 3:
                                    config_key = config_key[:-1]
                                if model_names:
                                    model_by_group[config_key] = ', '.join(model_names)
                            except Exception:
                                pass
                    except Exception:
                        pass
    except Exception as e:
        print(f"Error getting models from permission sets: {e}")

    # List S3 config folders
    try:
        response = s3_client.list_objects_v2(Bucket=BUCKET_NAME, Prefix='config/', Delimiter='/')
        for prefix in response.get('CommonPrefixes', []):
            config_key = prefix['Prefix'].replace('config/', '').rstrip('/')
            if config_key == 'admin':
                continue

            files = {}
            for fmt, filename in [('json', 'default.json'), ('macos', 'Claude.mobileconfig'), ('windows', 'Claude.reg')]:
                try:
                    s3_client.head_object(Bucket=BUCKET_NAME, Key=f"config/{config_key}/{filename}")
                    files[fmt] = True
                except Exception:
                    pass

            if files:
                groups[config_key] = {
                    'name': config_key.replace('-', ' ').title(),
                    'model': model_by_group.get(config_key, model_by_group.get(config_key + 's', 'Unknown Model')),
                    'formats': files
                }
    except Exception as e:
        print(f"Error listing config groups: {e}")

    return groups


# Admin API Functions

def api_list_groups():
    """List IAM Identity Center groups (filtered to Claude-related groups)"""
    print("api_list_groups: starting")
    try:
        instances = sso_admin_client.list_instances()
        if not instances.get('Instances'):
            return json_response({'error': 'No IDC instance found'}, 404)

        identity_store_id = instances['Instances'][0]['IdentityStoreId']

        groups = []
        paginator = identity_store_client.get_paginator('list_groups')
        for page in paginator.paginate(IdentityStoreId=identity_store_id):
            for group in page.get('Groups', []):
                # Only include groups with "Claude" in the name
                if 'claude' in group['DisplayName'].lower():
                    groups.append({
                        'groupId': group['GroupId'],
                        'displayName': group['DisplayName'],
                        'description': group.get('Description', '')
                    })

        print(f"api_list_groups: found {len(groups)} groups")
        return json_response({'groups': groups})
    except Exception as e:
        print(f"Error listing groups: {e}")
        return internal_error_response()


def api_list_permission_sets():
    """List existing IAM Identity Center permission sets with group assignments"""
    print("api_list_permission_sets: starting")
    try:
        instances = sso_admin_client.list_instances()
        if not instances.get('Instances'):
            return json_response({'error': 'No IDC instance found'}, 404)

        instance_arn = instances['Instances'][0]['InstanceArn']
        identity_store_id = instances['Instances'][0]['IdentityStoreId']
        account_id = boto3.client('sts').get_caller_identity()['Account']

        permission_sets = []
        paginator = sso_admin_client.get_paginator('list_permission_sets')
        ps_count = 0
        for page in paginator.paginate(InstanceArn=instance_arn):
            for ps_arn in page.get('PermissionSets', []):
                ps_count += 1
                print(f"api_list_permission_sets: processing PS {ps_count}: {ps_arn[-20:]}")
                try:
                    ps = sso_admin_client.describe_permission_set(
                        InstanceArn=instance_arn,
                        PermissionSetArn=ps_arn
                    )
                    ps_info = ps['PermissionSet']

                    # Get group assignments for this permission set
                    assigned_groups = []
                    try:
                        assignments = sso_admin_client.list_account_assignments(
                            InstanceArn=instance_arn,
                            AccountId=account_id,
                            PermissionSetArn=ps_arn
                        )
                        for assignment in assignments.get('AccountAssignments', []):
                            if assignment.get('PrincipalType') == 'GROUP':
                                group_id = assignment.get('PrincipalId')
                                try:
                                    group = identity_store_client.describe_group(
                                        IdentityStoreId=identity_store_id,
                                        GroupId=group_id
                                    )
                                    assigned_groups.append({
                                        'groupId': group_id,
                                        'groupName': group.get('DisplayName', '')
                                    })
                                except Exception:
                                    pass
                    except Exception as e:
                        print(f"Error getting assignments for {ps_arn}: {e}")

                    # Try to get model from inline policy
                    model_resources = []
                    try:
                        policy_response = sso_admin_client.get_inline_policy_for_permission_set(
                            InstanceArn=instance_arn,
                            PermissionSetArn=ps_arn
                        )
                        if policy_response.get('InlinePolicy'):
                            policy = json.loads(policy_response['InlinePolicy'])
                            for stmt in policy.get('Statement', []):
                                if stmt.get('Sid') == 'AllowBedrockModel':
                                    resources = stmt.get('Resource', [])
                                    if isinstance(resources, str):
                                        resources = [resources]
                                    model_resources = resources
                    except Exception:
                        pass

                    permission_sets.append({
                        'arn': ps_arn,
                        'name': ps_info.get('Name', ''),
                        'description': ps_info.get('Description', ''),
                        'sessionDuration': ps_info.get('SessionDuration', 'PT1H'),
                        'assignedGroups': assigned_groups,
                        'modelResources': model_resources
                    })
                except Exception as e:
                    print(f"Error describing permission set {ps_arn}: {e}")

        permission_sets.sort(key=lambda p: p['name'])
        print(f"api_list_permission_sets: returning {len(permission_sets)} permission sets")
        return json_response({'permissionSets': permission_sets})
    except Exception as e:
        print(f"Error listing permission sets: {e}")
        return internal_error_response()


def api_get_permission_set_details(ps_name):
    """Get detailed info about a permission set including its inline policy"""
    try:
        instances = sso_admin_client.list_instances()
        if not instances.get('Instances'):
            return json_response({'error': 'No IDC instance found'}, 404)

        instance_arn = instances['Instances'][0]['InstanceArn']

        # Find permission set by name
        ps_arn = None
        paginator = sso_admin_client.get_paginator('list_permission_sets')
        for page in paginator.paginate(InstanceArn=instance_arn):
            for arn in page.get('PermissionSets', []):
                ps = sso_admin_client.describe_permission_set(
                    InstanceArn=instance_arn,
                    PermissionSetArn=arn
                )
                if ps['PermissionSet']['Name'] == ps_name:
                    ps_arn = arn
                    break
            if ps_arn:
                break

        if not ps_arn:
            return json_response({'error': f'Permission set {ps_name} not found'}, 404)

        # Get permission set details
        ps = sso_admin_client.describe_permission_set(
            InstanceArn=instance_arn,
            PermissionSetArn=ps_arn
        )

        # Get inline policy
        inline_policy = None
        try:
            policy_response = sso_admin_client.get_inline_policy_for_permission_set(
                InstanceArn=instance_arn,
                PermissionSetArn=ps_arn
            )
            inline_policy = policy_response.get('InlinePolicy', '')
            if inline_policy:
                inline_policy = json.loads(inline_policy)
        except Exception as e:
            print(f"Error getting inline policy: {e}")

        return json_response({
            'name': ps['PermissionSet']['Name'],
            'description': ps['PermissionSet'].get('Description', ''),
            'sessionDuration': ps['PermissionSet'].get('SessionDuration', 'PT1H'),
            'arn': ps_arn,
            'inlinePolicy': inline_policy
        })
    except Exception as e:
        print(f"Error getting permission set details: {e}")
        return internal_error_response()


def api_list_models():
    """List available Anthropic models from Bedrock (excluding deprecated)"""
    try:
        models = []

        # Deprecated model patterns to exclude
        deprecated_patterns = [
            'claude-v1', 'claude-v2', 'claude-instant',
            'claude-2.0', 'claude-2.1',
            'claude-3-sonnet-20240229', 'claude-3-haiku-20240307', 'claude-3-opus-20240229'
        ]

        def is_deprecated(model_id):
            model_lower = model_id.lower()
            for pattern in deprecated_patterns:
                if pattern in model_lower:
                    return True
            return False

        # Only list inference profiles (cross-region) - these are what we use for policies
        # Show both US and Global variants so admins can choose
        try:
            profiles_response = bedrock_client.list_inference_profiles()
            for profile in profiles_response.get('inferenceProfileSummaries', []):
                profile_id = profile.get('inferenceProfileId', '')
                profile_name = profile.get('inferenceProfileName', '')
                status = profile.get('status', 'ACTIVE')
                if ('claude' in profile_id.lower() or 'anthropic' in profile_id.lower()) and not is_deprecated(profile_id) and status == 'ACTIVE':
                    models.append({
                        'modelId': profile_id,
                        'modelName': profile_name,
                        'type': 'inference-profile',
                        'status': status
                    })
        except Exception as e:
            print(f"Error listing inference profiles: {e}")

        models.sort(key=lambda m: m['modelName'])

        return json_response({'models': models})
    except Exception as e:
        print(f"Error listing models: {e}")
        return internal_error_response()


def api_get_config():
    """Get current group-model configuration from S3"""
    try:
        config = load_admin_config()
        return json_response(config)
    except Exception as e:
        print(f"Error getting config: {e}")
        return internal_error_response()


def api_save_config(body):
    """Save group-model configuration to S3"""
    try:
        config = json.loads(body) if body else {}
        save_admin_config(config)
        return json_response({'success': True, 'message': 'Configuration saved'})
    except Exception as e:
        print(f"Error saving config: {e}")
        return internal_error_response()


def api_bootstrap(user_info, base_url):
    """Bootstrap API endpoint - returns user-specific config for Claude Desktop

    Claude Desktop polls this endpoint every 30 minutes via the bootstrapUrl MDM key.
    Returns the current config for the user's group, allowing dynamic updates without
    users needing to re-download MDM profiles.
    """
    import time

    try:
        user_email = user_info.get('email', '')
        if not user_email:
            return json_response({'error': 'User email not found'}, 401)

        # Get user's groups from IDC
        user_groups = get_user_idc_groups(user_email)
        if not user_groups:
            return json_response({'error': 'User not in any groups'}, 403)

        # Load admin config to find user's group mapping
        admin_config = load_admin_config()
        mappings = admin_config.get('mappings', [])

        # Find the first matching group config
        user_config = None
        matched_group = None
        for mapping in mappings:
            group_name = mapping.get('groupName', '')
            if group_name in user_groups:
                matched_group = group_name
                # Convert group name to config key
                config_key = group_name.lower().replace('claude-code-', '').replace('claude-', '').replace(' ', '-').replace('_', '-')
                if config_key.endswith('s') and len(config_key) > 3:
                    config_key = config_key[:-1]

                # Try to load the bootstrap config for this group
                try:
                    response = s3_client.get_object(
                        Bucket=BUCKET_NAME,
                        Key=f"config/{config_key}/bootstrap.json"
                    )
                    user_config = json.loads(response['Body'].read().decode('utf-8'))
                    break
                except s3_client.exceptions.NoSuchKey:
                    print(f"No bootstrap config for {config_key}, checking next group")
                    continue

        if not user_config:
            return json_response({
                'error': 'No configuration found for user groups',
                'groups': user_groups
            }, 404)

        # Return full config including SSO fields
        # The redirect policy error was caused by port mismatch, not SSO fields
        config = {}
        policy_keys = [
            # Required by Claude Desktop for interactive auth
            'inferenceProvider',
            'inferenceCredentialKind',
            'inferenceBedrockRegion',
            'inferenceBedrockSsoStartUrl',
            'inferenceBedrockSsoRegion',
            'inferenceBedrockSsoAccountId',
            'inferenceBedrockSsoRoleName',
            'inferenceModels',
            'deploymentOrganizationUuid',
            # Policy settings
            'disabledBuiltinTools',
            'builtinToolPolicy',
            'isLocalDevMcpEnabled',
            'isDesktopExtensionEnabled',
            'isDesktopExtensionSignatureRequired',
            'coworkTabEnabled',
            'disableBundledSkills',
            'disableDeploymentModeChooser',
            'allowedWorkspaceFolders',
            'coworkEgressAllowedHosts',
            # NOTE: managedMcpServers deliberately excluded from this allowlist -
            # handled separately below via build_bootstrap_managed_mcp_servers(),
            # which forwards only http/sse entries (stdio must go through MDM).
        ]
        for key in policy_keys:
            if key in user_config:
                config[key] = user_config[key]

        managed_mcp_list = build_bootstrap_managed_mcp_servers(user_config)
        if managed_mcp_list:
            config['managedMcpServers'] = managed_mcp_list

        # Add dynamic expiration (config valid for 1 hour, re-polled every 30 min)
        config['expiresAt'] = int(time.time()) + 3600

        return json_response(config)

    except Exception as e:
        print(f"Bootstrap API error: {e}")
        import traceback
        print(traceback.format_exc())
        return internal_error_response()


def api_bootstrap_with_jwt(jwt_token):
    """Bootstrap API with Cognito OIDC JWT authentication for Claude Desktop

    Claude Desktop sends an OAuth access token from the bootstrap Cognito
    client in the Authorization header. We verify it against Cognito itself
    (signature, expiry, revocation) rather than trusting a locally-decoded,
    unverified JWT payload, then look up the user's group and return config.
    """
    print(f"Bootstrap JWT API called, token length: {len(jwt_token) if jwt_token else 0}")

    try:
        user_info = verify_cognito_access_token(jwt_token)
        if not user_info:
            print("Invalid or unverifiable access token")
            return json_response({'error': 'Invalid token'}, 401)

        user_email = user_info.get('email', '')
        if not user_email:
            username = user_info.get('username', '')
            if username and '@' in username:
                user_email = username.split('_', 1)[1] if '_' in username else username

        if not user_email:
            return json_response({'error': 'No email in token'}, 401)

        # Get user's groups from IDC
        user_groups = get_user_idc_groups(user_email)
        if not user_groups:
            return json_response({'error': 'User not in any groups', 'email': user_email}, 403)

        # Load admin config to find user's group mapping
        admin_config = load_admin_config()
        mappings = admin_config.get('mappings', [])

        # Find the first matching group config
        for mapping in mappings:
            group_name = mapping.get('groupName', '')
            if group_name in user_groups:
                # Convert group name to config key
                config_key = group_name.lower().replace('claude-code-', '').replace('claude-', '').replace(' ', '-').replace('_', '-')
                if config_key.endswith('s') and len(config_key) > 3:
                    config_key = config_key[:-1]

                # Load the bootstrap config
                try:
                    response = s3_client.get_object(
                        Bucket=BUCKET_NAME,
                        Key=f"config/{config_key}/bootstrap.json"
                    )
                    full_config = json.loads(response['Body'].read().decode('utf-8'))

                    # Return full config including SSO fields
                    # The redirect policy error was caused by port mismatch, not SSO fields
                    config = {}
                    policy_keys = [
                        # Required by Claude Desktop for interactive auth
                        'inferenceProvider',
                        'inferenceCredentialKind',
                        'inferenceBedrockRegion',
                        'inferenceBedrockSsoStartUrl',
                        'inferenceBedrockSsoRegion',
                        'inferenceBedrockSsoAccountId',
                        'inferenceBedrockSsoRoleName',
                        'inferenceModels',
                        'deploymentOrganizationUuid',
                        # Policy settings
                        'disabledBuiltinTools',
                        'builtinToolPolicy',
                        'isLocalDevMcpEnabled',
                        'isDesktopExtensionEnabled',
                        'isDesktopExtensionSignatureRequired',
                        'coworkTabEnabled',
                        'disableBundledSkills',
                        'disableDeploymentModeChooser',
                        'allowedWorkspaceFolders',
                        'coworkEgressAllowedHosts',
                        # NOTE: managedMcpServers deliberately excluded from this allowlist -
                        # handled separately below via build_bootstrap_managed_mcp_servers(),
                        # which forwards only http/sse entries (stdio must go through MDM).
                    ]
                    for key in policy_keys:
                        if key in full_config:
                            config[key] = full_config[key]

                    # Bootstrap CANNOT deliver stdio MCP servers (security restriction) -
                    # Claude Desktop itself drops stdio entries from bootstrap responses to
                    # prevent remote responses from nominating arbitrary local binaries to
                    # run. Local/stdio servers must be delivered via MDM (mobileconfig).
                    # http/sse-transport entries (e.g. AWS Knowledge MCP, AgentCore Gateway)
                    # ARE safe over bootstrap and are forwarded here.
                    managed_mcp_list = build_bootstrap_managed_mcp_servers(full_config)
                    if managed_mcp_list:
                        config['managedMcpServers'] = managed_mcp_list

                    # Ensure MCP-related settings allow user/MDM MCP servers
                    if 'isLocalDevMcpEnabled' not in config:
                        config['isLocalDevMcpEnabled'] = True
                    if 'isDesktopExtensionEnabled' not in config:
                        config['isDesktopExtensionEnabled'] = True

                    config['expiresAt'] = int(time.time()) + 3600

                    print(f"Bootstrap JWT returning config for {log_safe(user_email)}, group {group_name}, keys: {list(config.keys())}")
                    if 'managedMcpServers' in config:
                        print(f"managedMcpServers value: {json.dumps(config['managedMcpServers'])}")
                    return json_response(config)

                except s3_client.exceptions.NoSuchKey:
                    continue

        return json_response({
            'error': 'No configuration found for user groups',
            'email': user_email,
            'groups': user_groups
        }, 404)

    except Exception as e:
        print(f"Bootstrap JWT API error: {e}")
        import traceback
        print(traceback.format_exc())
        return internal_error_response()


def api_deploy_config(body, base_url=None):
    """Deploy configuration: update permission sets and generate MDM configs

    New format supports multiple models per group plus policies and MCP servers:
    {
        mappings: [
            {
                groupId: "...",
                groupName: "Claude-Code-Developers",
                roleName: "ClaudeCodeDeveloper",
                models: [{modelId: "...", modelName: "..."}, ...],
                createNew: false
            }
        ],
        policies: {
            disabledBuiltinTools: [...],
            builtinToolPolicy: {...},
            isLocalDevMcpEnabled: true,
            ...
        },
        managedMcpServers: [...],
        mcpServerTemplates: [...]
    }

    Args:
        body: JSON body with config
        base_url: Base URL for bootstrap endpoint (enables dynamic config updates)
    """
    import time

    try:
        config = json.loads(body) if body else load_admin_config()
        mappings = config.get('mappings', [])

        if not mappings:
            return json_response({'error': 'No group-model mappings configured'}, 400)

        # Extract policy and MCP settings
        policies = config.get('policies', {})
        managed_mcp_servers = config.get('managedMcpServers', [])
        mcp_server_templates = config.get('mcpServerTemplates', [])

        results = []
        account_id = boto3.client('sts').get_caller_identity()['Account']

        instances = sso_admin_client.list_instances()
        if not instances.get('Instances'):
            return json_response({'error': 'No IDC instance found'}, 404)

        instance_arn = instances['Instances'][0]['InstanceArn']
        identity_store_id = instances['Instances'][0]['IdentityStoreId']

        # Use IdentityStoreId for the start URL (e.g., d-9067c6b186)
        idc_start_url = f"https://{identity_store_id}.awsapps.com/start"

        # Process each mapping sequentially to avoid SSO conflicts
        for mapping in mappings:
            group_name = mapping.get('groupName', '')
            group_id = mapping.get('groupId', '')
            role_name = mapping.get('roleName', f'ClaudeCode-{group_name}')

            # Support both old format (single model) and new format (multiple models)
            models_list = mapping.get('models', [])
            if not models_list:
                # Old format fallback
                model_id = mapping.get('modelId', '')
                model_name = mapping.get('modelName', '')
                if model_id:
                    models_list = [{'modelId': model_id, 'modelName': model_name}]

            if not group_id or not models_list:
                continue

            try:
                print(f"Processing {group_name}...")

                # Create or update permission set (without provisioning)
                ps_arn = create_or_update_permission_set_no_provision(
                    instance_arn, role_name, models_list
                )

                # Assign to group
                assign_permission_set(instance_arn, ps_arn, group_id, account_id)

                # Provision with retry - one at a time
                provision_with_retry(instance_arn, ps_arn, account_id, role_name)

                # Generate MDM configs with all models in the list
                # Convert "Claude-Code-Developers" -> "developers"
                config_key = group_name.lower().replace('claude-code-', '').replace('claude-', '').replace(' ', '-').replace('_', '-')
                # Remove trailing 's' for consistency (developers -> developer)
                if config_key.endswith('s') and len(config_key) > 3:
                    config_key = config_key[:-1]
                print(f"Generating MDM configs for {group_name} -> config_key={config_key}, models={[m['modelName'] for m in models_list]}")
                generate_mdm_configs(
                    config_key, idc_start_url, REGION, account_id, role_name,
                    models_list,
                    policies=policies,
                    managed_mcp_servers=managed_mcp_servers,
                    mcp_server_templates=mcp_server_templates,
                    base_url=base_url
                )

                model_names = ', '.join([m['modelName'] for m in models_list])
                results.append({
                    'group': group_name,
                    'model': model_names,
                    'status': 'success',
                    'permissionSet': role_name
                })

                # Small delay between permission sets to avoid conflicts
                time.sleep(1)

            except Exception as e:
                print(f"Error deploying for group {group_name}: {e}")
                results.append({
                    'group': group_name,
                    'model': '',
                    'status': 'error',
                    'error': str(e)
                })

        # Save config after successful deploy
        save_admin_config(config)

        return json_response({'success': True, 'results': results})
    except Exception as e:
        print(f"Error deploying config: {e}")
        return internal_error_response()


def provision_with_retry(instance_arn, ps_arn, account_id, name):
    """Provision permission set with exponential backoff retry and wait for completion"""
    import time
    max_retries = 10

    # Start provisioning with retry on conflict
    request_id = None
    for attempt in range(max_retries):
        try:
            response = sso_admin_client.provision_permission_set(
                InstanceArn=instance_arn,
                PermissionSetArn=ps_arn,
                TargetType='AWS_ACCOUNT',
                TargetId=account_id
            )
            request_id = response.get('PermissionSetProvisioningStatus', {}).get('RequestId')
            print(f"Provisioning {name} started (request_id: {request_id})")
            break
        except sso_admin_client.exceptions.ConflictException:
            if attempt < max_retries - 1:
                wait_time = 2 + attempt * 2  # 2, 4, 6, 8... seconds
                print(f"Conflict provisioning {name}, waiting {wait_time}s (attempt {attempt + 1}/{max_retries})...")
                time.sleep(wait_time)
            else:
                raise

    # Wait for provisioning to complete (best effort - don't fail if status check unavailable)
    if request_id:
        for _ in range(30):  # Wait up to 60 seconds
            try:
                status_response = sso_admin_client.describe_permission_set_provisioning_status(
                    InstanceArn=instance_arn,
                    ProvisionPermissionSetRequestId=request_id
                )
                status = status_response.get('PermissionSetProvisioningStatus', {}).get('Status')
                if status == 'SUCCEEDED':
                    print(f"Provisioned {name} successfully")
                    return
                elif status == 'FAILED':
                    failure_reason = status_response.get('PermissionSetProvisioningStatus', {}).get('FailureReason', 'Unknown')
                    print(f"Provisioning {name} failed: {failure_reason}")
                    # Don't raise - provisioning might have partially succeeded or is a transient error
                    # Continue with config generation
                    return
                else:
                    print(f"Provisioning {name} status: {status}, waiting...")
                    time.sleep(2)
            except sso_admin_client.exceptions.ResourceNotFoundException:
                # Request not found, might have completed quickly
                print(f"Provisioned {name} (request completed)")
                return
            except Exception as e:
                if 'AccessDeniedException' in str(e):
                    # Don't have permission to check status, just wait a bit and continue
                    print(f"Cannot check provisioning status (permission denied), waiting 5s...")
                    time.sleep(5)
                    print(f"Provisioned {name} (status check skipped)")
                    return
                raise
        print(f"Provisioning {name} timed out, continuing anyway")


def create_or_update_permission_set_no_provision(instance_arn, name, models_list):
    """Create or update a permission set with access to multiple Bedrock models.

    Does NOT provision - caller must provision separately.

    Args:
        instance_arn: SSO instance ARN
        name: Permission set name
        models_list: List of {modelId, modelName} dicts
    """
    # Find existing permission set
    ps_arn = None
    paginator = sso_admin_client.get_paginator('list_permission_sets')
    for page in paginator.paginate(InstanceArn=instance_arn):
        for arn in page.get('PermissionSets', []):
            ps = sso_admin_client.describe_permission_set(
                InstanceArn=instance_arn, PermissionSetArn=arn
            )
            if ps['PermissionSet']['Name'] == name:
                ps_arn = arn
                break
        if ps_arn:
            break

    # Create if doesn't exist
    if not ps_arn:
        model_names = ', '.join([m['modelName'] for m in models_list[:3]])
        response = sso_admin_client.create_permission_set(
            InstanceArn=instance_arn,
            Name=name,
            Description=f'Access to {model_names}',
            SessionDuration='PT8H'
        )
        ps_arn = response['PermissionSet']['PermissionSetArn']

    # Build resources for ALL models in the list
    # Include both inference-profile AND foundation-model ARNs
    # because Claude Desktop resolves inference profiles to foundation models
    all_resources = []
    for model in models_list:
        model_id = model['modelId']
        # Extract base model name (e.g., "claude-sonnet-4-6" from "global.anthropic.claude-sonnet-4-6")
        base_model = model_id.replace('us.anthropic.', '').replace('global.anthropic.', '').replace('eu.anthropic.', '')

        # Add the exact inference profile selected
        all_resources.append(f"arn:aws:bedrock:*:*:inference-profile/{model_id}*")

        # Add the underlying foundation model (required for actual invocation)
        all_resources.append(f"arn:aws:bedrock:*::foundation-model/anthropic.{base_model}*")

    # Deduplicate
    all_resources = list(dict.fromkeys(all_resources))

    # Build new policy (replaces existing)
    policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "AllowBedrockModel",
                "Effect": "Allow",
                "Action": ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
                "Resource": all_resources
            },
            {
                "Sid": "AllowBedrockList",
                "Effect": "Allow",
                "Action": ["bedrock:ListFoundationModels", "bedrock:GetFoundationModel"],
                "Resource": "*"
            }
        ]
    }

    # Apply policy
    sso_admin_client.put_inline_policy_to_permission_set(
        InstanceArn=instance_arn,
        PermissionSetArn=ps_arn,
        InlinePolicy=json.dumps(policy)
    )

    return ps_arn


def assign_permission_set(instance_arn, ps_arn, group_id, account_id):
    """Assign permission set to a group"""
    try:
        sso_admin_client.create_account_assignment(
            InstanceArn=instance_arn,
            PermissionSetArn=ps_arn,
            PrincipalType='GROUP',
            PrincipalId=group_id,
            TargetId=account_id,
            TargetType='AWS_ACCOUNT'
        )
    except sso_admin_client.exceptions.ConflictException:
        pass

    sso_admin_client.provision_permission_set(
        InstanceArn=instance_arn,
        PermissionSetArn=ps_arn,
        TargetType='AWS_ACCOUNT',
        TargetId=account_id
    )


def generate_mdm_configs(config_key, idc_start_url, region, account_id, role_name, models_list,
                         policies=None, managed_mcp_servers=None, mcp_server_templates=None,
                         base_url=None):
    """Generate and upload MDM configuration files

    Args:
        models_list: List of dicts with 'modelId' and 'modelName' keys
        policies: Dict of policy settings (disabledBuiltinTools, builtinToolPolicy, etc.)
        managed_mcp_servers: List of remote HTTPS MCP server configs
        mcp_server_templates: List of local MCP server templates
        base_url: Base URL for the bootstrap API endpoint (enables dynamic config updates)
    """
    import uuid

    policies = policies or {}
    managed_mcp_servers = managed_mcp_servers or []
    mcp_server_templates = mcp_server_templates or []

    deployment_uuid = str(uuid.uuid4()).upper()

    # Bootstrap URL (without token - OIDC handles auth)
    bootstrap_url = f"{base_url}/api/bootstrap" if base_url else None

    # Bootstrap OIDC config for Claude Desktop authentication
    # Must match the callback URL configured in Cognito bootstrap client (http://127.0.0.1:8080/callback)
    bootstrap_oidc = None
    if base_url and COGNITO_BOOTSTRAP_CLIENT_ID and COGNITO_USER_POOL_ID:
        bootstrap_oidc = {
            "clientId": COGNITO_BOOTSTRAP_CLIENT_ID,
            "issuer": f"https://cognito-idp.{REGION}.amazonaws.com/{COGNITO_USER_POOL_ID}",
            "scopes": "openid email profile",
            "redirectPort": 8080
        }

    # Build inferenceModels array from all models
    inference_models = []
    for model in models_list:
        model_id = model.get('modelId', '')
        model_name = model.get('modelName', model_id)

        # Ensure model_id has proper prefix for Bedrock
        if model_id and not model_id.startswith(('us.', 'global.')):
            if model_id.startswith('anthropic.'):
                model_id = f"us.{model_id}"
            else:
                model_id = f"us.anthropic.{model_id}"

        inference_models.append({
            "name": model_id,
            "labelOverride": model_name
        })

    model_names_str = ', '.join([m['modelName'] for m in models_list])
    print(f"Generating config with {len(models_list)} models: {model_names_str}")

    # Base config with Bedrock settings
    config = {
        "inferenceProvider": "bedrock",
        "inferenceCredentialKind": "interactive",
        "inferenceBedrockRegion": region,
        "inferenceBedrockSsoStartUrl": idc_start_url,
        "inferenceBedrockSsoRegion": region,
        "inferenceBedrockSsoAccountId": account_id,
        "inferenceBedrockSsoRoleName": role_name,
        "inferenceModels": inference_models,
        "deploymentOrganizationUuid": deployment_uuid
    }

    # Add policy settings if configured
    if policies.get('disabledBuiltinTools'):
        config['disabledBuiltinTools'] = policies['disabledBuiltinTools']

    if policies.get('builtinToolPolicy'):
        config['builtinToolPolicy'] = policies['builtinToolPolicy']

    # Feature toggles (only add if not default)
    if not policies.get('isLocalDevMcpEnabled', True):
        config['isLocalDevMcpEnabled'] = False

    if not policies.get('isDesktopExtensionEnabled', True):
        config['isDesktopExtensionEnabled'] = False

    if policies.get('isDesktopExtensionSignatureRequired', False):
        config['isDesktopExtensionSignatureRequired'] = True

    if not policies.get('coworkTabEnabled', True):
        config['coworkTabEnabled'] = False

    if policies.get('disableBundledSkills', False):
        config['disableBundledSkills'] = True

    if policies.get('disableDeploymentModeChooser', True):
        config['disableDeploymentModeChooser'] = True

    # Workspace and network restrictions
    if policies.get('allowedWorkspaceFolders'):
        config['allowedWorkspaceFolders'] = policies['allowedWorkspaceFolders']

    if policies.get('coworkEgressAllowedHosts'):
        config['coworkEgressAllowedHosts'] = policies['coworkEgressAllowedHosts']

    # Add managed MCP servers (remote HTTPS)
    if managed_mcp_servers:
        config['managedMcpServers'] = managed_mcp_servers

    # Add local MCP server templates
    if mcp_server_templates:
        config['mcpServerTemplates'] = mcp_server_templates

    # Save JSON config (static download version)
    json_content = json.dumps(config, indent=2)
    s3_client.put_object(
        Bucket=BUCKET_NAME,
        Key=f"config/{config_key}/default.json",
        Body=json_content.encode('utf-8'),
        ContentType='application/json'
    )

    # Save bootstrap.json - the dynamic config served by /api/bootstrap
    # This is the full config that Claude Desktop will fetch periodically.
    #
    # IMPORTANT: Bootstrap responses do NOT inherit from MDM for omitted keys.
    # Per Claude Desktop docs, "a bootstrap-settable key that your response
    # omits is treated as unset, not inherited from MDM" - unlike the MDM/
    # default.json config above, which only needs non-default values because
    # the app already defaults to them locally. So every feature toggle must
    # be explicit here, even when it matches the default (e.g. True).
    bootstrap_config = dict(config)
    bootstrap_config['isLocalDevMcpEnabled'] = policies.get('isLocalDevMcpEnabled', True)
    bootstrap_config['isDesktopExtensionEnabled'] = policies.get('isDesktopExtensionEnabled', True)
    bootstrap_config['isDesktopExtensionSignatureRequired'] = policies.get('isDesktopExtensionSignatureRequired', False)
    bootstrap_config['coworkTabEnabled'] = policies.get('coworkTabEnabled', True)
    bootstrap_config['disableBundledSkills'] = policies.get('disableBundledSkills', False)
    bootstrap_config['disableDeploymentModeChooser'] = policies.get('disableDeploymentModeChooser', True)
    bootstrap_config['_configKey'] = config_key
    bootstrap_config['_version'] = deployment_uuid
    s3_client.put_object(
        Bucket=BUCKET_NAME,
        Key=f"config/{config_key}/bootstrap.json",
        Body=json.dumps(bootstrap_config, indent=2).encode('utf-8'),
        ContentType='application/json'
    )
    print(f"Saved bootstrap config for {config_key}")

    # Generate and save mobileconfig (macOS MDM) with bootstrap OIDC
    mobileconfig = generate_mobileconfig(config, deployment_uuid, config_key, bootstrap_url, bootstrap_oidc)
    s3_client.put_object(
        Bucket=BUCKET_NAME,
        Key=f"config/{config_key}/Claude.mobileconfig",
        Body=mobileconfig.encode('utf-8'),
        ContentType='application/x-apple-aspen-config'
    )

    # Generate and save registry file (Windows) with bootstrap OIDC
    reg_content = generate_reg_file(config, config_key, bootstrap_url, bootstrap_oidc)
    s3_client.put_object(
        Bucket=BUCKET_NAME,
        Key=f"config/{config_key}/Claude.reg",
        Body=reg_content.encode('utf-16-le'),
        ContentType='text/plain; charset=utf-16le'
    )

    # If there are local MCP server templates, also generate a claude_desktop_config.json
    if mcp_server_templates:
        mcp_config = {"mcpServers": {}}
        for server in mcp_server_templates:
            mcp_config["mcpServers"][server.get('name', 'unnamed')] = {
                "command": server.get('command', ''),
                "args": server.get('args', []),
                "env": server.get('env', {})
            }
        s3_client.put_object(
            Bucket=BUCKET_NAME,
            Key=f"config/{config_key}/claude_desktop_config.json",
            Body=json.dumps(mcp_config, indent=2).encode('utf-8'),
            ContentType='application/json'
        )


def generate_mobileconfig(config, deployment_uuid, config_key, bootstrap_url=None, bootstrap_oidc=None):
    """Generate macOS mobileconfig XML in the correct format for Claude Desktop

    Args:
        bootstrap_url: URL for dynamic config updates (without token - used with OIDC)
        bootstrap_oidc: Dict with OIDC config {clientId, issuer, scopes, redirectPort}
    """
    import uuid
    payload_uuid = str(uuid.uuid4()).upper()

    # Build inferenceModels JSON string
    inference_models_json = json.dumps(config.get('inferenceModels', []))

    # Use role name for profile display (e.g., "Developer", "Contractor")
    role_display = config_key.replace('-', ' ').title()

    # Build optional policy keys
    policy_keys = []

    # Bootstrap configuration for dynamic updates with OIDC authentication
    if bootstrap_url and bootstrap_oidc:
        policy_keys.append(f'''				<key>bootstrapEnabled</key>
				<true/>''')
        policy_keys.append(f'''				<key>bootstrapUrl</key>
				<string>{bootstrap_url}</string>''')
        policy_keys.append(f'''				<key>bootstrapOidc</key>
				<string>{json.dumps(bootstrap_oidc)}</string>''')

    if config.get('disabledBuiltinTools'):
        policy_keys.append(f'''				<key>disabledBuiltinTools</key>
				<string>{json.dumps(config['disabledBuiltinTools'])}</string>''')

    if config.get('builtinToolPolicy'):
        policy_keys.append(f'''				<key>builtinToolPolicy</key>
				<string>{json.dumps(config['builtinToolPolicy'])}</string>''')

    if 'isLocalDevMcpEnabled' in config:
        policy_keys.append(f'''				<key>isLocalDevMcpEnabled</key>
				<{'true' if config['isLocalDevMcpEnabled'] else 'false'}/>''')

    if 'isDesktopExtensionEnabled' in config:
        policy_keys.append(f'''				<key>isDesktopExtensionEnabled</key>
				<{'true' if config['isDesktopExtensionEnabled'] else 'false'}/>''')

    if config.get('isDesktopExtensionSignatureRequired'):
        policy_keys.append(f'''				<key>isDesktopExtensionSignatureRequired</key>
				<true/>''')

    if 'coworkTabEnabled' in config:
        policy_keys.append(f'''				<key>coworkTabEnabled</key>
				<{'true' if config['coworkTabEnabled'] else 'false'}/>''')

    if config.get('disableBundledSkills'):
        policy_keys.append(f'''				<key>disableBundledSkills</key>
				<true/>''')

    if config.get('disableDeploymentModeChooser'):
        policy_keys.append(f'''				<key>disableDeploymentModeChooser</key>
				<true/>''')

    if config.get('allowedWorkspaceFolders'):
        policy_keys.append(f'''				<key>allowedWorkspaceFolders</key>
				<string>{json.dumps(config['allowedWorkspaceFolders'])}</string>''')

    if config.get('coworkEgressAllowedHosts'):
        policy_keys.append(f'''				<key>coworkEgressAllowedHosts</key>
				<string>{json.dumps(config['coworkEgressAllowedHosts'])}</string>''')

    # Build managedMcpServers from both existing managedMcpServers and mcpServerTemplates
    # managedMcpServers must be an ARRAY of objects with name, transport, command, args, env
    managed_mcp_list = []

    # Add existing managedMcpServers (if already in array format)
    if config.get('managedMcpServers'):
        if isinstance(config['managedMcpServers'], list):
            managed_mcp_list.extend(config['managedMcpServers'])

    # Add local MCP server templates (command-line servers)
    if config.get('mcpServerTemplates'):
        for server in config['mcpServerTemplates']:
            mcp_entry = {
                "name": server.get('name', 'unnamed'),
                "transport": "stdio",
                "command": server.get('command', ''),
                "args": server.get('args', []),
            }
            if server.get('env'):
                mcp_entry["env"] = server['env']
            managed_mcp_list.append(mcp_entry)

    if managed_mcp_list:
        policy_keys.append(f'''				<key>managedMcpServers</key>
				<string>{json.dumps(managed_mcp_list)}</string>''')

    policy_keys_str = '\n'.join(policy_keys)

    return f'''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
	<dict>
		<key>PayloadContent</key>
		<array>
			<dict>
				<key>PayloadType</key>
				<string>com.anthropic.claudefordesktop</string>
				<key>PayloadIdentifier</key>
				<string>com.anthropic.claudefordesktop.settings</string>
				<key>PayloadUUID</key>
				<string>{payload_uuid}</string>
				<key>PayloadVersion</key>
				<integer>1</integer>
				<key>PayloadDisplayName</key>
				<string>Claude Desktop</string>
				<key>inferenceProvider</key>
				<string>bedrock</string>
				<key>inferenceCredentialKind</key>
				<string>{config.get('inferenceCredentialKind', 'interactive')}</string>
				<key>inferenceBedrockRegion</key>
				<string>{config.get('inferenceBedrockRegion', 'us-east-1')}</string>
				<key>inferenceBedrockSsoStartUrl</key>
				<string>{config.get('inferenceBedrockSsoStartUrl', '')}</string>
				<key>inferenceBedrockSsoRegion</key>
				<string>{config.get('inferenceBedrockSsoRegion', 'us-east-1')}</string>
				<key>inferenceBedrockSsoAccountId</key>
				<string>{config.get('inferenceBedrockSsoAccountId', '')}</string>
				<key>inferenceBedrockSsoRoleName</key>
				<string>{config.get('inferenceBedrockSsoRoleName', '')}</string>
				<key>inferenceModels</key>
				<string>{inference_models_json}</string>
				<key>deploymentOrganizationUuid</key>
				<string>{deployment_uuid}</string>
{policy_keys_str}
			</dict>
		</array>
		<key>PayloadDisplayName</key>
		<string>Claude Desktop - {role_display}</string>
		<key>PayloadIdentifier</key>
		<string>com.anthropic.claudefordesktop.{config_key}</string>
		<key>PayloadType</key>
		<string>Configuration</string>
		<key>PayloadUUID</key>
		<string>{deployment_uuid}</string>
		<key>PayloadVersion</key>
		<integer>1</integer>
		<key>PayloadScope</key>
		<string>User</string>
	</dict>
</plist>'''


def generate_reg_file(config, config_key, bootstrap_url=None, bootstrap_oidc=None):
    """Generate Windows registry file in UTF-16 LE format

    Args:
        bootstrap_url: URL for dynamic config updates (without token - used with OIDC)
        bootstrap_oidc: Dict with OIDC config {clientId, issuer, scopes, redirectPort}
    """
    inference_models_json = json.dumps(config.get('inferenceModels', [])).replace('"', '\\"')

    # Build optional policy entries
    policy_entries = []

    # Bootstrap configuration for dynamic updates with OIDC authentication
    if bootstrap_url and bootstrap_oidc:
        policy_entries.append('"bootstrapEnabled"=dword:00000001')
        policy_entries.append(f'"bootstrapUrl"="{bootstrap_url}"')
        oidc_escaped = json.dumps(bootstrap_oidc).replace('"', '\\"')
        policy_entries.append(f'"bootstrapOidc"="{oidc_escaped}"')

    if config.get('disabledBuiltinTools'):
        escaped = json.dumps(config['disabledBuiltinTools']).replace('"', '\\"')
        policy_entries.append(f'"disabledBuiltinTools"="{escaped}"')

    if config.get('builtinToolPolicy'):
        escaped = json.dumps(config['builtinToolPolicy']).replace('"', '\\"')
        policy_entries.append(f'"builtinToolPolicy"="{escaped}"')

    if 'isLocalDevMcpEnabled' in config:
        val = "1" if config['isLocalDevMcpEnabled'] else "0"
        policy_entries.append(f'"isLocalDevMcpEnabled"=dword:0000000{val}')

    if 'isDesktopExtensionEnabled' in config:
        val = "1" if config['isDesktopExtensionEnabled'] else "0"
        policy_entries.append(f'"isDesktopExtensionEnabled"=dword:0000000{val}')

    if config.get('isDesktopExtensionSignatureRequired'):
        policy_entries.append('"isDesktopExtensionSignatureRequired"=dword:00000001')

    if 'coworkTabEnabled' in config:
        val = "1" if config['coworkTabEnabled'] else "0"
        policy_entries.append(f'"coworkTabEnabled"=dword:0000000{val}')

    if config.get('disableBundledSkills'):
        policy_entries.append('"disableBundledSkills"=dword:00000001')

    if config.get('disableDeploymentModeChooser'):
        policy_entries.append('"disableDeploymentModeChooser"=dword:00000001')

    if config.get('allowedWorkspaceFolders'):
        escaped = json.dumps(config['allowedWorkspaceFolders']).replace('"', '\\"')
        policy_entries.append(f'"allowedWorkspaceFolders"="{escaped}"')

    if config.get('coworkEgressAllowedHosts'):
        escaped = json.dumps(config['coworkEgressAllowedHosts']).replace('"', '\\"')
        policy_entries.append(f'"coworkEgressAllowedHosts"="{escaped}"')

    # Build managedMcpServers from both existing managedMcpServers and mcpServerTemplates
    # managedMcpServers must be an ARRAY of objects with name, transport, command, args, env
    managed_mcp_list = []

    if config.get('managedMcpServers'):
        if isinstance(config['managedMcpServers'], list):
            managed_mcp_list.extend(config['managedMcpServers'])

    if config.get('mcpServerTemplates'):
        for server in config['mcpServerTemplates']:
            mcp_entry = {
                "name": server.get('name', 'unnamed'),
                "transport": "stdio",
                "command": server.get('command', ''),
                "args": server.get('args', []),
            }
            if server.get('env'):
                mcp_entry["env"] = server['env']
            managed_mcp_list.append(mcp_entry)

    if managed_mcp_list:
        escaped = json.dumps(managed_mcp_list).replace('"', '\\"')
        policy_entries.append(f'"managedMcpServers"="{escaped}"')

    policy_entries_str = '\n'.join(policy_entries)

    reg_content = f'''Windows Registry Editor Version 5.00

[HKEY_CURRENT_USER\\SOFTWARE\\Policies\\Claude]
"inferenceProvider"="bedrock"
"inferenceCredentialKind"="{config.get('inferenceCredentialKind', 'interactive')}"
"inferenceBedrockRegion"="{config.get('inferenceBedrockRegion', 'us-east-1')}"
"inferenceBedrockSsoStartUrl"="{config.get('inferenceBedrockSsoStartUrl', '')}"
"inferenceBedrockSsoRegion"="{config.get('inferenceBedrockSsoRegion', 'us-east-1')}"
"inferenceBedrockSsoAccountId"="{config.get('inferenceBedrockSsoAccountId', '')}"
"inferenceBedrockSsoRoleName"="{config.get('inferenceBedrockSsoRoleName', '')}"
"inferenceModels"="{inference_models_json}"
"deploymentOrganizationUuid"="{config.get('deploymentOrganizationUuid', '')}"
{policy_entries_str}
'''
    return reg_content


def load_admin_config():
    """Load admin configuration from S3"""
    try:
        response = s3_client.get_object(Bucket=BUCKET_NAME, Key='admin/config.json')
        return json.loads(response['Body'].read().decode('utf-8'))
    except s3_client.exceptions.NoSuchKey:
        return {'mappings': []}
    except Exception:
        return {'mappings': []}


def save_admin_config(config):
    """Save admin configuration to S3"""
    s3_client.put_object(
        Bucket=BUCKET_NAME,
        Key='admin/config.json',
        Body=json.dumps(config, indent=2).encode('utf-8'),
        ContentType='application/json'
    )


def json_response(data, status_code=200):
    """Return JSON API response"""
    return {
        'statusCode': status_code,
        'headers': {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*'
        },
        'body': json.dumps(data)
    }


def serve_admin_page(user_info, base_url):
    """Serve the admin configuration page"""
    user_email = user_info.get('email', 'admin')
    html = generate_admin_page(user_email, base_url)
    return {
        'statusCode': 200,
        'headers': {'Content-Type': 'text/html; charset=utf-8'},
        'body': html
    }


def generate_admin_page(user_email, base_url):
    """Generate admin page HTML with enterprise policy controls and sidebar navigation.

    (B608 nosec below: this builds an HTML template, not a SQL query — bandit's
    heuristic misfires on f-string blocks containing CSS/HTML select-like
    tokens.)
    """
    return f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Claude Desktop Admin</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #f5f7fa;
            min-height: 100vh;
        }}
        .layout {{
            display: flex;
            min-height: 100vh;
        }}
        .sidebar {{
            width: 260px;
            background: linear-gradient(180deg, #1a1a2e 0%, #16213e 100%);
            color: white;
            padding: 0;
            position: fixed;
            height: 100vh;
            overflow-y: auto;
        }}
        .sidebar-header {{
            padding: 24px 20px;
            border-bottom: 1px solid rgba(255,255,255,0.1);
        }}
        .sidebar-header h1 {{
            font-size: 18px;
            font-weight: 600;
            margin-bottom: 4px;
        }}
        .sidebar-header .subtitle {{
            font-size: 12px;
            color: rgba(255,255,255,0.6);
        }}
        .sidebar-nav {{
            padding: 16px 0;
        }}
        .nav-section {{
            padding: 8px 20px;
            font-size: 11px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            color: rgba(255,255,255,0.4);
            margin-top: 8px;
        }}
        .nav-item {{
            display: flex;
            align-items: center;
            padding: 12px 20px;
            color: rgba(255,255,255,0.8);
            text-decoration: none;
            cursor: pointer;
            transition: all 0.2s;
            border-left: 3px solid transparent;
        }}
        .nav-item:hover {{
            background: rgba(255,255,255,0.05);
            color: white;
        }}
        .nav-item.active {{
            background: rgba(102, 126, 234, 0.2);
            color: white;
            border-left-color: #667eea;
        }}
        .nav-item svg {{
            width: 18px;
            height: 18px;
            margin-right: 12px;
            opacity: 0.7;
        }}
        .nav-item.active svg {{
            opacity: 1;
        }}
        .sidebar-footer {{
            position: absolute;
            bottom: 0;
            left: 0;
            right: 0;
            padding: 16px 20px;
            border-top: 1px solid rgba(255,255,255,0.1);
            background: rgba(0,0,0,0.2);
        }}
        .user-info {{
            display: flex;
            align-items: center;
            margin-bottom: 12px;
        }}
        .user-avatar {{
            width: 32px;
            height: 32px;
            border-radius: 50%;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 14px;
            font-weight: 600;
            margin-right: 10px;
        }}
        .user-email {{
            font-size: 12px;
            color: rgba(255,255,255,0.8);
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
            max-width: 160px;
        }}
        .sidebar-links {{
            display: flex;
            gap: 12px;
        }}
        .sidebar-links a {{
            font-size: 12px;
            color: rgba(255,255,255,0.6);
            text-decoration: none;
        }}
        .sidebar-links a:hover {{
            color: white;
        }}
        .main-content {{
            flex: 1;
            margin-left: 260px;
            padding: 24px 32px;
            max-width: calc(100% - 260px);
        }}
        .page-header {{
            margin-bottom: 24px;
        }}
        .page-header h2 {{
            font-size: 24px;
            color: #1a1a2e;
            margin-bottom: 4px;
        }}
        .page-header p {{
            color: #666;
            font-size: 14px;
        }}
        .section {{
            background: white;
            border-radius: 12px;
            padding: 24px;
            margin-bottom: 24px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.08);
        }}
        .section h3 {{
            font-size: 16px;
            color: #333;
            margin-bottom: 16px;
            padding-bottom: 12px;
            border-bottom: 1px solid #eee;
        }}
        .section h4 {{
            font-size: 14px;
            color: #555;
            margin: 20px 0 12px;
        }}
        .section-description {{
            color: #666;
            font-size: 13px;
            margin-bottom: 16px;
        }}
        .page-content {{ display: none; }}
        .page-content.active {{ display: block; }}
        table {{
            width: 100%;
            border-collapse: collapse;
        }}
        th, td {{
            padding: 12px;
            text-align: left;
            border-bottom: 1px solid #eee;
        }}
        th {{
            background: #f8f9fa;
            font-weight: 600;
            color: #555;
            font-size: 13px;
        }}
        select, input[type="text"], input[type="url"], textarea {{
            padding: 10px 12px;
            border: 1px solid #ddd;
            border-radius: 8px;
            font-size: 14px;
            width: 100%;
            transition: border-color 0.2s;
        }}
        select:focus, input:focus, textarea:focus {{
            outline: none;
            border-color: #667eea;
            box-shadow: 0 0 0 3px rgba(102,126,234,0.1);
        }}
        textarea {{
            min-height: 80px;
            font-family: monospace;
            resize: vertical;
        }}
        .btn {{
            display: inline-flex;
            align-items: center;
            justify-content: center;
            padding: 10px 20px;
            border-radius: 8px;
            font-weight: 600;
            cursor: pointer;
            border: none;
            font-size: 14px;
            transition: all 0.2s;
            gap: 8px;
        }}
        .btn-primary {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
        }}
        .btn-primary:hover {{
            transform: translateY(-1px);
            box-shadow: 0 4px 12px rgba(102, 126, 234, 0.3);
        }}
        .btn-success {{
            background: linear-gradient(135deg, #28a745 0%, #20c997 100%);
            color: white;
        }}
        .btn-success:hover {{
            transform: translateY(-1px);
            box-shadow: 0 4px 12px rgba(40, 167, 69, 0.3);
        }}
        .btn-danger {{
            background: #dc3545;
            color: white;
        }}
        .btn-danger:hover {{
            background: #c82333;
        }}
        .btn-secondary {{
            background: #6c757d;
            color: white;
        }}
        .btn-sm {{
            padding: 6px 12px;
            font-size: 12px;
        }}
        .btn-outline {{
            background: white;
            border: 1px solid #ddd;
            color: #333;
        }}
        .btn-outline:hover {{
            background: #f8f9fa;
        }}
        .actions {{
            display: flex;
            gap: 12px;
            margin-top: 20px;
        }}
        .status {{
            padding: 16px;
            border-radius: 8px;
            margin-top: 20px;
            display: none;
        }}
        .status.success {{
            background: #d4edda;
            color: #155724;
            display: block;
        }}
        .status.error {{
            background: #f8d7da;
            color: #721c24;
            display: block;
        }}
        .status.info {{
            background: #d1ecf1;
            color: #0c5460;
            display: block;
        }}
        .loading {{
            opacity: 0.6;
            pointer-events: none;
        }}
        .badge {{
            font-size: 11px;
            padding: 3px 8px;
            border-radius: 12px;
            font-weight: 500;
        }}
        .badge-success {{
            background: #e8f5e9;
            color: #2e7d32;
        }}
        .badge-warning {{
            background: #fff3e0;
            color: #e65100;
        }}
        .badge-danger {{
            background: #ffebee;
            color: #c62828;
        }}
        .badge-info {{
            background: #e3f2fd;
            color: #1565c0;
        }}
        .model-tags, .tool-tags {{
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
        }}
        .model-tag, .tool-tag {{
            display: inline-flex;
            align-items: center;
            background: #e3f2fd;
            color: #1565c0;
            padding: 4px 10px;
            border-radius: 16px;
            font-size: 13px;
        }}
        .tool-tag.blocked {{
            background: #ffebee;
            color: #c62828;
        }}
        .tool-tag.ask {{
            background: #fff3e0;
            color: #e65100;
        }}
        .model-tag .remove, .tool-tag .remove {{
            margin-left: 6px;
            cursor: pointer;
            opacity: 0.6;
            font-weight: bold;
        }}
        .model-tag .remove:hover, .tool-tag .remove:hover {{
            opacity: 1;
        }}
        .add-row {{
            display: flex;
            gap: 8px;
            align-items: center;
            margin-top: 12px;
        }}
        .add-row select, .add-row input {{
            flex: 1;
        }}
        .toggle-row {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 16px 0;
            border-bottom: 1px solid #eee;
        }}
        .toggle-row:last-child {{
            border-bottom: none;
        }}
        .toggle-label {{
            font-weight: 500;
            color: #333;
        }}
        .toggle-description {{
            font-size: 12px;
            color: #888;
            margin-top: 4px;
        }}
        .toggle-switch {{
            position: relative;
            width: 48px;
            height: 24px;
            flex-shrink: 0;
        }}
        .toggle-switch input {{
            opacity: 0;
            width: 0;
            height: 0;
        }}
        .toggle-slider {{
            position: absolute;
            cursor: pointer;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background-color: #ccc;
            transition: 0.3s;
            border-radius: 24px;
        }}
        .toggle-slider:before {{
            position: absolute;
            content: "";
            height: 18px;
            width: 18px;
            left: 3px;
            bottom: 3px;
            background-color: white;
            transition: 0.3s;
            border-radius: 50%;
        }}
        input:checked + .toggle-slider {{
            background-color: #667eea;
        }}
        input:checked + .toggle-slider:before {{
            transform: translateX(24px);
        }}
        .card {{
            border: 1px solid #e0e0e0;
            border-radius: 10px;
            padding: 16px;
            margin-bottom: 12px;
            background: #fafafa;
        }}
        .card-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 8px;
        }}
        .card-header h5 {{
            font-size: 14px;
            font-weight: 600;
            margin: 0;
        }}
        .card-body {{
            font-size: 13px;
            color: #666;
        }}
        .card-body code {{
            background: #e9ecef;
            padding: 2px 6px;
            border-radius: 4px;
            font-size: 12px;
        }}
        .form-grid {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 16px;
        }}
        .form-grid .full-width {{
            grid-column: 1 / -1;
        }}
        .form-group {{
            margin-bottom: 16px;
        }}
        .form-group label {{
            display: block;
            font-size: 13px;
            font-weight: 500;
            color: #555;
            margin-bottom: 6px;
        }}
        .collapsible-btn {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            width: 100%;
            padding: 12px 16px;
            background: #f8f9fa;
            border: 1px solid #e0e0e0;
            border-radius: 8px;
            cursor: pointer;
            font-weight: 500;
            color: #333;
            margin-bottom: 12px;
            transition: all 0.2s;
        }}
        .collapsible-btn:hover {{
            background: #e9ecef;
        }}
        .collapsible-btn.active {{
            border-color: #667eea;
            background: #f0f4ff;
        }}
        .collapsible-content {{
            display: none;
            padding: 16px;
            background: #fafafa;
            border-radius: 8px;
            margin-bottom: 16px;
        }}
        .collapsible-content.show {{
            display: block;
        }}
        .grid-2 {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 24px;
        }}
        @media (max-width: 1200px) {{
            .grid-2 {{
                grid-template-columns: 1fr;
            }}
        }}
        .summary-grid {{
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 16px;
            margin-bottom: 20px;
        }}
        .summary-card {{
            background: #f8f9fa;
            border-radius: 8px;
            padding: 16px;
            text-align: center;
        }}
        .summary-card .number {{
            font-size: 28px;
            font-weight: 700;
            color: #667eea;
        }}
        .summary-card .label {{
            font-size: 12px;
            color: #666;
            margin-top: 4px;
        }}
        pre {{
            background: #1a1a2e;
            color: #e0e0e0;
            padding: 16px;
            border-radius: 8px;
            overflow: auto;
            max-height: 400px;
            font-size: 12px;
        }}
        .save-status {{
            font-size: 13px;
            padding: 8px 12px;
            border-radius: 6px;
            display: inline-flex;
            align-items: center;
            gap: 6px;
        }}
        .save-status.saving {{
            background: #fff3e0;
            color: #e65100;
        }}
        .save-status.saved {{
            background: #e8f5e9;
            color: #2e7d32;
        }}
        .save-status.error {{
            background: #ffebee;
            color: #c62828;
        }}
        .save-status.unsaved {{
            background: #fff8e1;
            color: #ff8f00;
        }}
        @keyframes spin {{
            from {{ transform: rotate(0deg); }}
            to {{ transform: rotate(360deg); }}
        }}
    </style>
</head>
<body>
    <div class="layout">
        <aside class="sidebar">
            <div class="sidebar-header">
                <h1>Claude Admin</h1>
                <div class="subtitle">Enterprise Configuration</div>
            </div>
            <nav class="sidebar-nav">
                <div class="nav-section">Configuration</div>
                <a class="nav-item active" onclick="switchPage('models')">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"/><path d="M12 1v2m0 18v2M4.22 4.22l1.42 1.42m12.72 12.72l1.42 1.42M1 12h2m18 0h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42"/></svg>
                    Models &amp; Groups
                </a>
                <a class="nav-item" onclick="switchPage('policies')">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>
                    Policies
                </a>
                <a class="nav-item" onclick="switchPage('mcp')">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="3" width="20" height="14" rx="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/></svg>
                    MCP Servers
                </a>
                <div class="nav-section">Actions</div>
                <a class="nav-item" onclick="switchPage('deploy')">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>
                    Deploy
                </a>
            </nav>
            <div class="sidebar-footer">
                <div class="user-info">
                    <div class="user-avatar">{esc(user_email[0].upper()) if user_email else 'A'}</div>
                    <div class="user-email" title="{esc(user_email)}">{esc(user_email)}</div>
                </div>
                <div class="sidebar-links">
                    <a href="/">Landing Page</a>
                    <a href="/logout">Logout</a>
                </div>
            </div>
        </aside>

        <main class="main-content">
            <!-- Models & Groups Page -->
            <div id="page-models" class="page-content active">
                <div class="page-header">
                    <h2>Models &amp; Groups</h2>
                    <p>Assign Bedrock inference profiles to IAM Identity Center groups</p>
                </div>

                <div class="section">
                    <h3>Group to Model Mappings</h3>
                    <p class="section-description">Each group will get a permission set with access to the assigned models.</p>
                    <table id="mappings-table">
                        <thead>
                            <tr>
                                <th>IDC Group</th>
                                <th>Assigned Models</th>
                                <th>Add Model</th>
                                <th>Permission Set</th>
                            </tr>
                        </thead>
                        <tbody id="mappings-body">
                            <tr><td colspan="4" style="text-align: center; color: #888; padding: 40px;">Loading...</td></tr>
                        </tbody>
                    </table>
                </div>

                <div class="section">
                    <h3>Available Models</h3>
                    <table id="models-table">
                        <thead>
                            <tr>
                                <th>Model Name</th>
                                <th>Model ID</th>
                                <th>Type</th>
                            </tr>
                        </thead>
                        <tbody id="models-body">
                            <tr><td colspan="3" style="text-align: center; color: #888; padding: 40px;">Loading...</td></tr>
                        </tbody>
                    </table>
                </div>

                <div class="section" style="background: linear-gradient(135deg, #f8f9fa 0%, #e9ecef 100%);">
                    <div style="display: flex; justify-content: space-between; align-items: center;">
                        <div id="models-save-status" class="save-status"></div>
                        <button class="btn btn-primary" onclick="saveDraft('models')">
                            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M19 21H5a2 2 0 01-2-2V5a2 2 0 012-2h11l5 5v11a2 2 0 01-2 2z"/><polyline points="17 21 17 13 7 13 7 21"/><polyline points="7 3 7 8 15 8"/></svg>
                            Save Draft
                        </button>
                    </div>
                </div>
            </div>

            <!-- Policies Page -->
            <div id="page-policies" class="page-content">
                <div class="page-header">
                    <h2>Policies</h2>
                    <p>Control which tools and features are available to users</p>
                </div>

                <div class="grid-2">
                    <div class="section">
                        <h3>Tool Restrictions</h3>
                        <p class="section-description">Blocked tools are completely removed from Claude.</p>

                        <h4>Disabled Tools</h4>
                        <div id="disabled-tools-list" class="tool-tags">
                            <span style="color:#888;font-size:13px;">None - all tools enabled</span>
                        </div>
                        <div class="add-row">
                            <select id="add-disabled-tool">
                                <option value="">Select tool to disable...</option>
                                <option value="WebSearch">WebSearch</option>
                                <option value="WebFetch">WebFetch</option>
                                <option value="Bash">Bash (Shell commands)</option>
                                <option value="Edit">Edit (File editing)</option>
                                <option value="Write">Write (File writing)</option>
                                <option value="NotebookEdit">NotebookEdit</option>
                            </select>
                            <button class="btn btn-primary btn-sm" onclick="addDisabledTool()">Block</button>
                        </div>

                        <h4>Tool Policies</h4>
                        <p class="section-description">Set approval requirements for specific tools.</p>
                        <div id="tool-policies-list"></div>
                        <div class="add-row">
                            <select id="add-tool-policy-name" style="flex: 2;">
                                <option value="">Select tool...</option>
                                <option value="Bash">Bash</option>
                                <option value="Edit">Edit</option>
                                <option value="Write">Write</option>
                                <option value="WebFetch">WebFetch</option>
                                <option value="WebSearch">WebSearch</option>
                            </select>
                            <select id="add-tool-policy-value" style="flex: 1;">
                                <option value="allow">Allow</option>
                                <option value="ask">Ask</option>
                                <option value="blocked">Block</option>
                            </select>
                            <button class="btn btn-primary btn-sm" onclick="addToolPolicy()">Add</button>
                        </div>
                    </div>

                    <div class="section">
                        <h3>Feature Controls</h3>
                        <p class="section-description">Enable or disable Claude Desktop features.</p>

                        <div class="toggle-row">
                            <div>
                                <div class="toggle-label">Allow Local MCP Servers</div>
                                <div class="toggle-description">Let users add their own MCP servers</div>
                            </div>
                            <label class="toggle-switch">
                                <input type="checkbox" id="policy-isLocalDevMcpEnabled" checked>
                                <span class="toggle-slider"></span>
                            </label>
                        </div>

                        <div class="toggle-row">
                            <div>
                                <div class="toggle-label">Allow Desktop Extensions</div>
                                <div class="toggle-description">Let users install .dxt and .mcpb extensions</div>
                            </div>
                            <label class="toggle-switch">
                                <input type="checkbox" id="policy-isDesktopExtensionEnabled" checked>
                                <span class="toggle-slider"></span>
                            </label>
                        </div>

                        <div class="toggle-row">
                            <div>
                                <div class="toggle-label">Require Signed Extensions</div>
                                <div class="toggle-description">Only allow signed extensions</div>
                            </div>
                            <label class="toggle-switch">
                                <input type="checkbox" id="policy-isDesktopExtensionSignatureRequired">
                                <span class="toggle-slider"></span>
                            </label>
                        </div>

                        <div class="toggle-row">
                            <div>
                                <div class="toggle-label">Enable Cowork Tab</div>
                                <div class="toggle-description">Allow access to Cowork/agentic features</div>
                            </div>
                            <label class="toggle-switch">
                                <input type="checkbox" id="policy-coworkTabEnabled" checked>
                                <span class="toggle-slider"></span>
                            </label>
                        </div>

                        <div class="toggle-row">
                            <div>
                                <div class="toggle-label">Disable Bundled Skills</div>
                                <div class="toggle-description">Turn off built-in skills and workflows</div>
                            </div>
                            <label class="toggle-switch">
                                <input type="checkbox" id="policy-disableBundledSkills">
                                <span class="toggle-slider"></span>
                            </label>
                        </div>

                        <div class="toggle-row">
                            <div>
                                <div class="toggle-label">Lock to Bedrock Provider</div>
                                <div class="toggle-description">Prevent switching to Anthropic direct</div>
                            </div>
                            <label class="toggle-switch">
                                <input type="checkbox" id="policy-disableDeploymentModeChooser" checked>
                                <span class="toggle-slider"></span>
                            </label>
                        </div>
                    </div>
                </div>

                <div class="section">
                    <h3>Workspace &amp; Network Restrictions</h3>
                    <div class="grid-2">
                        <div>
                            <h4>Allowed Workspace Folders</h4>
                            <p class="section-description">Restrict which directories users can attach. Leave empty for no restrictions.</p>
                            <div id="allowed-folders-list" style="margin-bottom: 12px;"></div>
                            <div class="add-row">
                                <input type="text" id="add-folder-path" placeholder="e.g., ~/Projects">
                                <button class="btn btn-primary btn-sm" onclick="addAllowedFolder()">Add</button>
                            </div>
                        </div>
                        <div>
                            <h4>Network Egress Allowlist</h4>
                            <p class="section-description">Restrict which hosts tools can connect to. Use * for unrestricted.</p>
                            <div id="egress-hosts-list" style="margin-bottom: 12px;"></div>
                            <div class="add-row">
                                <input type="text" id="add-egress-host" placeholder="e.g., *.corp.com">
                                <button class="btn btn-primary btn-sm" onclick="addEgressHost()">Add</button>
                            </div>
                        </div>
                    </div>
                </div>

                <div class="section" style="background: linear-gradient(135deg, #f8f9fa 0%, #e9ecef 100%);">
                    <div style="display: flex; justify-content: space-between; align-items: center;">
                        <div id="policies-save-status" class="save-status"></div>
                        <button class="btn btn-primary" onclick="saveDraft('policies')">
                            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M19 21H5a2 2 0 01-2-2V5a2 2 0 012-2h11l5 5v11a2 2 0 01-2 2z"/><polyline points="17 21 17 13 7 13 7 21"/><polyline points="7 3 7 8 15 8"/></svg>
                            Save Draft
                        </button>
                    </div>
                </div>
            </div>

            <!-- MCP Servers Page -->
            <div id="page-mcp" class="page-content">
                <div class="page-header">
                    <h2>MCP Servers</h2>
                    <p>Pre-configure MCP servers for your users</p>
                </div>

                <div class="section">
                    <h3>Managed MCP Servers (Remote)</h3>
                    <p class="section-description">Remote HTTPS MCP servers that users connect to via OAuth.</p>
                    <div id="managed-mcp-servers"></div>

                    <button class="collapsible-btn" onclick="toggleCollapsible(this)">
                        <span>+ Add Remote MCP Server</span>
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6 9 12 15 18 9"/></svg>
                    </button>
                    <div class="collapsible-content">
                        <div class="form-grid">
                            <div class="form-group">
                                <label>Server Name</label>
                                <input type="text" id="new-mcp-name" placeholder="e.g., corporate-tools">
                            </div>
                            <div class="form-group">
                                <label>Server URL</label>
                                <input type="url" id="new-mcp-url" placeholder="https://mcp.your-corp.com/api">
                            </div>
                            <div class="form-group full-width">
                                <label>Description (optional)</label>
                                <input type="text" id="new-mcp-description" placeholder="Corporate tools gateway">
                            </div>
                            <div class="full-width">
                                <button class="btn btn-primary" onclick="addManagedMcpServer()">Add Server</button>
                            </div>
                        </div>
                    </div>
                </div>

                <div class="section">
                    <h3>MCP Server Templates (Local)</h3>
                    <p class="section-description">Pre-configured local MCP servers. Users may need to provide credentials.</p>
                    <div id="mcp-templates"></div>

                    <button class="collapsible-btn" onclick="toggleCollapsible(this)">
                        <span>+ Add from Template</span>
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6 9 12 15 18 9"/></svg>
                    </button>
                    <div class="collapsible-content">
                        <div style="display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 12px;">
                            <button class="btn btn-outline" onclick="addMcpTemplate('github')">GitHub</button>
                            <button class="btn btn-outline" onclick="addMcpTemplate('slack')">Slack</button>
                            <button class="btn btn-outline" onclick="addMcpTemplate('filesystem')">Filesystem</button>
                            <button class="btn btn-outline" onclick="addMcpTemplate('brave-search')">Brave Search</button>
                            <button class="btn btn-outline" onclick="addMcpTemplate('postgres')">PostgreSQL</button>
                            <button class="btn btn-outline" onclick="addMcpTemplate('custom')">Custom</button>
                        </div>
                    </div>

                    <button class="collapsible-btn" onclick="toggleCollapsible(this)">
                        <span>+ Add Custom Local Server</span>
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6 9 12 15 18 9"/></svg>
                    </button>
                    <div class="collapsible-content">
                        <div class="form-grid">
                            <div class="form-group">
                                <label>Server Name</label>
                                <input type="text" id="new-local-mcp-name" placeholder="e.g., my-server">
                            </div>
                            <div class="form-group">
                                <label>Command</label>
                                <input type="text" id="new-local-mcp-command" placeholder="/usr/local/bin/npx">
                            </div>
                            <div class="form-group full-width">
                                <label>Arguments (one per line)</label>
                                <textarea id="new-local-mcp-args" placeholder="-y&#10;@modelcontextprotocol/server-github"></textarea>
                            </div>
                            <div class="form-group full-width">
                                <label>Environment Variables (KEY=value, one per line)</label>
                                <textarea id="new-local-mcp-env" placeholder="GITHUB_TOKEN=&lt;user-provided&gt;&#10;PATH=/usr/local/bin:/usr/bin"></textarea>
                            </div>
                            <div class="full-width">
                                <button class="btn btn-primary" onclick="addLocalMcpServer()">Add Server</button>
                            </div>
                        </div>
                    </div>
                </div>

                <div class="section" style="background: linear-gradient(135deg, #f8f9fa 0%, #e9ecef 100%);">
                    <div style="display: flex; justify-content: space-between; align-items: center;">
                        <div id="mcp-save-status" class="save-status"></div>
                        <button class="btn btn-primary" onclick="saveDraft('mcp')">
                            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M19 21H5a2 2 0 01-2-2V5a2 2 0 012-2h11l5 5v11a2 2 0 01-2 2z"/><polyline points="17 21 17 13 7 13 7 21"/><polyline points="7 3 7 8 15 8"/></svg>
                            Save Draft
                        </button>
                    </div>
                </div>
            </div>

            <!-- Deploy Page -->
            <div id="page-deploy" class="page-content">
                <div class="page-header">
                    <h2>Deploy Configuration</h2>
                    <p>Generate MDM configuration files for your groups</p>
                </div>

                <div class="section">
                    <h3>Configuration Summary</h3>
                    <div class="summary-grid" id="deploy-summary">
                        <div class="summary-card">
                            <div class="number" id="summary-groups">0</div>
                            <div class="label">Groups with Models</div>
                        </div>
                        <div class="summary-card">
                            <div class="number" id="summary-policies">0</div>
                            <div class="label">Policy Settings</div>
                        </div>
                        <div class="summary-card">
                            <div class="number" id="summary-mcp">0</div>
                            <div class="label">MCP Servers</div>
                        </div>
                    </div>
                    <p class="section-description">
                        Deploying will update IAM Identity Center permission sets and generate MDM configuration files
                        (mobileconfig for macOS, .reg for Windows, JSON for manual setup) for each group.
                    </p>
                    <div style="background: #e8f5e9; border: 1px solid #a5d6a7; border-radius: 8px; padding: 16px; margin-bottom: 16px;">
                        <div style="display: flex; align-items: flex-start; gap: 12px;">
                            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#2e7d32" stroke-width="2" style="flex-shrink: 0; margin-top: 2px;"><circle cx="12" cy="12" r="10"/><path d="M12 16v-4M12 8h.01"/></svg>
                            <div>
                                <div style="font-weight: 600; color: #1b5e20; margin-bottom: 4px;">Dynamic Config Updates via OIDC Bootstrap</div>
                                <div style="color: #2e7d32; font-size: 13px; line-height: 1.5;">
                                    MDM profiles include OIDC bootstrap configuration. Claude Desktop will authenticate via Cognito (federated with IAM Identity Center) and automatically fetch the latest configuration every 30 minutes.
                                    <strong>After the initial profile installation, users will receive policy and model updates automatically</strong> — no need to re-download profiles.
                                </div>
                                <div style="color: #558b2f; font-size: 12px; margin-top: 8px; padding-top: 8px; border-top: 1px solid #c5e1a5;">
                                    <strong>Note:</strong> The 30-minute refresh interval is controlled by Claude Desktop and cannot be changed server-side. For urgent updates (e.g., security policy changes), ask users to restart Claude Desktop to fetch changes immediately.
                                </div>
                            </div>
                        </div>
                    </div>
                    <div class="actions">
                        <button class="btn btn-success" onclick="deployConfig()">
                            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>
                            Save Configuration
                        </button>
                        <button class="btn btn-outline" onclick="previewConfig()">Preview JSON</button>
                    </div>
                    <div id="status" class="status"></div>
                </div>

                <div class="section">
                    <h3>Generated Configuration Preview</h3>
                    <pre id="config-preview" style="display: none;">Select "Preview JSON" to see the configuration</pre>
                </div>
            </div>
        </main>
    </div>

    <script>
        function escapeHtml(value) {{
            const div = document.createElement('div');
            div.textContent = value === null || value === undefined ? '' : String(value);
            return div.innerHTML;
        }}

        let groups = [];
        let models = [];
        let permissionSets = [];
        let groupConfig = {{}};

        let policies = {{
            disabledBuiltinTools: [],
            builtinToolPolicy: {{}},
            isLocalDevMcpEnabled: true,
            isDesktopExtensionEnabled: true,
            isDesktopExtensionSignatureRequired: false,
            coworkTabEnabled: true,
            disableBundledSkills: false,
            disableDeploymentModeChooser: true,
            allowedWorkspaceFolders: [],
            coworkEgressAllowedHosts: []
        }};

        let managedMcpServers = [];
        let mcpServerTemplates = [];

        function switchPage(pageId) {{
            document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
            document.querySelectorAll('.page-content').forEach(p => p.classList.remove('active'));
            document.querySelector(`.nav-item[onclick="switchPage('${{pageId}}')"]`).classList.add('active');
            document.getElementById('page-' + pageId).classList.add('active');
            if (pageId === 'deploy') updateDeploySummary();
        }}

        function toggleCollapsible(el) {{
            el.classList.toggle('active');
            el.nextElementSibling.classList.toggle('show');
        }}

        async function init() {{
            await Promise.all([loadGroups(), loadModels(), loadPermissionSets(), loadAdminConfig()]);
            buildGroupConfig();
            renderMappings();
            renderModels();
            renderPolicies();
            renderMcpServers();
        }}

        async function loadGroups() {{
            try {{
                const res = await fetch('/admin/api/groups');
                const data = await res.json();
                groups = (data.groups || []).filter(g => g.displayName && g.displayName.toLowerCase().includes('claude'));
            }} catch (e) {{ groups = []; }}
        }}

        async function loadModels() {{
            try {{
                const res = await fetch('/admin/api/models');
                const data = await res.json();
                models = data.models || [];
            }} catch (e) {{ models = []; }}
        }}

        async function loadPermissionSets() {{
            try {{
                const res = await fetch('/admin/api/permission-sets');
                const data = await res.json();
                permissionSets = data.permissionSets || [];
            }} catch (e) {{ permissionSets = []; }}
        }}

        async function loadAdminConfig() {{
            try {{
                const res = await fetch('/admin/api/config');
                const data = await res.json();
                if (data.policies) policies = {{ ...policies, ...data.policies }};
                if (data.managedMcpServers) managedMcpServers = data.managedMcpServers;
                if (data.mcpServerTemplates) mcpServerTemplates = data.mcpServerTemplates;
            }} catch (e) {{}}
        }}

        function buildGroupConfig() {{
            groupConfig = {{}};
            for (const group of groups) {{
                groupConfig[group.groupId] = {{ groupName: group.displayName, permissionSetName: null, models: [] }};
            }}
            for (const ps of permissionSets) {{
                if (!ps.assignedGroups) continue;
                for (const ag of ps.assignedGroups) {{
                    if (!groupConfig[ag.groupId]) continue;
                    groupConfig[ag.groupId].permissionSetName = ps.name;
                    if (ps.modelResources && ps.modelResources.length > 0) {{
                        const seenProfiles = new Set();
                        for (const resource of ps.modelResources) {{
                            const match = resource.match(/inference-profile\\/((?:us|global)\\.anthropic\\.[^*]+)/);
                            if (!match) continue;
                            const profileId = match[1];
                            if (seenProfiles.has(profileId)) continue;
                            seenProfiles.add(profileId);
                            let foundModel = models.find(m => m.modelId === profileId);
                            if (!foundModel) {{
                                const profileBase = profileId.replace(/-v\\d+:.*$/, '').replace(/:\\d+$/, '');
                                foundModel = models.find(m => m.modelId.replace(/-v\\d+:.*$/, '').replace(/:\\d+$/, '') === profileBase);
                            }}
                            const modelName = foundModel ? foundModel.modelName : profileId;
                            const modelId = foundModel ? foundModel.modelId : profileId;
                            if (!groupConfig[ag.groupId].models.find(m => m.modelId === modelId)) {{
                                groupConfig[ag.groupId].models.push({{ modelId, modelName }});
                            }}
                        }}
                    }}
                }}
            }}
        }}

        function renderMappings() {{
            const tbody = document.getElementById('mappings-body');
            if (groups.length === 0) {{
                tbody.innerHTML = '<tr><td colspan="4" style="text-align:center;color:#888;padding:40px;">No Claude groups found. Create groups with "Claude" in the name in IAM Identity Center.</td></tr>';
                return;
            }}
            let html = '';
            for (const group of groups) {{
                const gc = groupConfig[group.groupId] || {{ models: [], permissionSetName: null }};
                let modelTagsHtml = '<div class="model-tags">';
                if (gc.models.length === 0) modelTagsHtml += '<span style="color:#888;">None</span>';
                else gc.models.forEach((m, mi) => {{ modelTagsHtml += '<span class="model-tag">' + m.modelName + ' <span class="remove" data-group="' + group.groupId + '" data-idx="' + mi + '" onclick="removeModelByIdx(this)">&times;</span></span>'; }});
                modelTagsHtml += '</div>';
                let addHtml = '<div class="add-row"><select id="add-model-' + group.groupId + '" style="font-size:13px;"><option value="">Select model...</option>';
                models.filter(m => !gc.models.find(gm => gm.modelId === m.modelId)).forEach(m => {{ addHtml += '<option value="' + encodeURIComponent(m.modelId) + '|' + encodeURIComponent(m.modelName) + '">' + m.modelName + '</option>'; }});
                addHtml += '</select><button class="btn btn-primary btn-sm" data-group="' + group.groupId + '" onclick="addModelFromBtn(this)">+</button></div>';
                let psHtml = gc.permissionSetName ? escapeHtml(gc.permissionSetName) + ' <a href="#" onclick="viewPolicy(' + escapeHtml(JSON.stringify(gc.permissionSetName)) + ');return false;" style="font-size:11px;color:#667eea;">[view]</a>' : '-';
                html += '<tr><td><strong>' + escapeHtml(group.displayName) + '</strong></td><td>' + modelTagsHtml + '</td><td>' + addHtml + '</td><td>' + psHtml + '</td></tr>';
            }}
            tbody.innerHTML = html;
        }}

        function addModelFromBtn(btn) {{
            const groupId = btn.getAttribute('data-group');
            const select = document.getElementById('add-model-' + groupId);
            if (!select.value) return;
            const [modelId, modelName] = select.value.split('|').map(decodeURIComponent);
            if (!groupConfig[groupId].models.find(m => m.modelId === modelId)) groupConfig[groupId].models.push({{ modelId, modelName }});
            renderMappings();
        }}

        function removeModelByIdx(el) {{
            const groupId = el.getAttribute('data-group'), idx = parseInt(el.getAttribute('data-idx'), 10);
            if (groupConfig[groupId]) {{ groupConfig[groupId].models.splice(idx, 1); renderMappings(); }}
        }}

        function renderModels() {{
            const tbody = document.getElementById('models-body');
            if (models.length === 0) {{ tbody.innerHTML = '<tr><td colspan="3" style="text-align:center;color:#888;padding:40px;">No models available</td></tr>'; return; }}
            tbody.innerHTML = models.map(m => '<tr><td>' + m.modelName + '</td><td><code style="font-size:12px;">' + m.modelId + '</code></td><td><span class="badge badge-success">' + m.type + '</span></td></tr>').join('');
        }}

        function renderPolicies() {{
            const dtl = document.getElementById('disabled-tools-list');
            dtl.innerHTML = policies.disabledBuiltinTools.length === 0 ? '<span style="color:#888;">None - all tools enabled</span>' : policies.disabledBuiltinTools.map((t, i) => '<span class="tool-tag blocked">' + escapeHtml(t) + ' <span class="remove" onclick="removeDisabledTool(' + i + ')">&times;</span></span>').join('');

            const tpl = document.getElementById('tool-policies-list');
            const pe = Object.entries(policies.builtinToolPolicy);
            tpl.innerHTML = pe.length === 0 ? '<p style="color:#888;font-size:13px;">No custom tool policies.</p>' : pe.map(([t, p]) => '<div style="display:flex;justify-content:space-between;align-items:center;padding:10px 0;border-bottom:1px solid #eee;"><span>' + escapeHtml(t) + '</span><span class="tool-tag ' + escapeHtml(p) + '">' + escapeHtml(p) + ' <span class="remove" onclick="removeToolPolicy(' + escapeHtml(JSON.stringify(t)) + ')">&times;</span></span></div>').join('');

            ['isLocalDevMcpEnabled', 'isDesktopExtensionEnabled', 'isDesktopExtensionSignatureRequired', 'coworkTabEnabled', 'disableBundledSkills', 'disableDeploymentModeChooser'].forEach(key => {{
                const el = document.getElementById('policy-' + key);
                el.checked = policies[key];
                el.onchange = function() {{ policies[key] = this.checked; }};
            }});

            const fl = document.getElementById('allowed-folders-list');
            fl.innerHTML = policies.allowedWorkspaceFolders.length === 0 ? '<span style="color:#888;">No restrictions</span>' : policies.allowedWorkspaceFolders.map((f, i) => '<span class="tool-tag">' + (f.path || f) + ' <span class="remove" onclick="removeAllowedFolder(' + i + ')">&times;</span></span>').join(' ');

            const el = document.getElementById('egress-hosts-list');
            el.innerHTML = policies.coworkEgressAllowedHosts.length === 0 ? '<span style="color:#888;">No restrictions</span>' : policies.coworkEgressAllowedHosts.map((h, i) => '<span class="tool-tag">' + h + ' <span class="remove" onclick="removeEgressHost(' + i + ')">&times;</span></span>').join(' ');
        }}

        function addDisabledTool() {{ const s = document.getElementById('add-disabled-tool'); if (s.value && !policies.disabledBuiltinTools.includes(s.value)) {{ policies.disabledBuiltinTools.push(s.value); s.value = ''; renderPolicies(); }} }}
        function removeDisabledTool(i) {{ policies.disabledBuiltinTools.splice(i, 1); renderPolicies(); }}
        function addToolPolicy() {{ const t = document.getElementById('add-tool-policy-name').value, p = document.getElementById('add-tool-policy-value').value; if (t) {{ policies.builtinToolPolicy[t] = p; document.getElementById('add-tool-policy-name').value = ''; renderPolicies(); }} }}
        function removeToolPolicy(t) {{ delete policies.builtinToolPolicy[t]; renderPolicies(); }}
        function addAllowedFolder() {{ const v = document.getElementById('add-folder-path').value.trim(); if (v) {{ policies.allowedWorkspaceFolders.push({{ path: v }}); document.getElementById('add-folder-path').value = ''; renderPolicies(); }} }}
        function removeAllowedFolder(i) {{ policies.allowedWorkspaceFolders.splice(i, 1); renderPolicies(); }}
        function addEgressHost() {{ const v = document.getElementById('add-egress-host').value.trim(); if (v && !policies.coworkEgressAllowedHosts.includes(v)) {{ policies.coworkEgressAllowedHosts.push(v); document.getElementById('add-egress-host').value = ''; renderPolicies(); }} }}
        function removeEgressHost(i) {{ policies.coworkEgressAllowedHosts.splice(i, 1); renderPolicies(); }}

        function renderMcpServers() {{
            const md = document.getElementById('managed-mcp-servers');
            md.innerHTML = managedMcpServers.length === 0 ? '<p style="color:#888;">No remote MCP servers configured.</p>' : managedMcpServers.map((s, i) => '<div class="card"><div class="card-header"><h5>' + s.name + '</h5><div><span class="badge badge-success">Remote</span> <button class="btn btn-danger btn-sm" onclick="removeManagedMcp(' + i + ')">Remove</button></div></div><div class="card-body"><strong>URL:</strong> <code>' + s.url + '</code>' + (s.description ? '<br>' + s.description : '') + '</div></div>').join('');

            const td = document.getElementById('mcp-templates');
            td.innerHTML = mcpServerTemplates.length === 0 ? '<p style="color:#888;">No local MCP templates configured.</p>' : mcpServerTemplates.map((s, i) => '<div class="card"><div class="card-header"><h5>' + s.name + '</h5><div><span class="badge badge-warning">Local</span> <button class="btn btn-danger btn-sm" onclick="removeMcpTemplate(' + i + ')">Remove</button></div></div><div class="card-body"><strong>Command:</strong> <code>' + s.command + ' ' + (s.args || []).join(' ') + '</code></div></div>').join('');
        }}

        function addManagedMcpServer() {{
            const n = document.getElementById('new-mcp-name').value.trim(), u = document.getElementById('new-mcp-url').value.trim(), d = document.getElementById('new-mcp-description').value.trim();
            if (!n || !u) {{ alert('Name and URL required'); return; }}
            managedMcpServers.push({{ name: n, transport: 'http', url: u, description: d, toolPolicy: {{ '*': 'allow' }} }});
            document.getElementById('new-mcp-name').value = ''; document.getElementById('new-mcp-url').value = ''; document.getElementById('new-mcp-description').value = '';
            renderMcpServers();
        }}
        function removeManagedMcp(i) {{ managedMcpServers.splice(i, 1); renderMcpServers(); }}

        const MCP_TEMPLATES = {{
            'github': {{ name: 'github', command: '/usr/local/bin/npx', args: ['-y', '@modelcontextprotocol/server-github'], env: {{ 'PATH': '/usr/local/bin:/usr/bin', 'GITHUB_PERSONAL_ACCESS_TOKEN': '<user-provided>' }} }},
            'slack': {{ name: 'slack', command: '/usr/local/bin/npx', args: ['-y', '@anthropic/mcp-slack-server'], env: {{ 'PATH': '/usr/local/bin:/usr/bin', 'SLACK_BOT_TOKEN': '<user-provided>', 'SLACK_TEAM_ID': '<user-provided>' }} }},
            'filesystem': {{ name: 'filesystem', command: '/usr/local/bin/npx', args: ['-y', '@modelcontextprotocol/server-filesystem', '~/Projects'], env: {{ 'PATH': '/usr/local/bin:/usr/bin' }} }},
            'brave-search': {{ name: 'brave-search', command: '/usr/local/bin/npx', args: ['-y', '@anthropic/mcp-brave-search'], env: {{ 'PATH': '/usr/local/bin:/usr/bin', 'BRAVE_API_KEY': '<user-provided>' }} }},
            'postgres': {{ name: 'postgres', command: '/usr/local/bin/npx', args: ['-y', '@modelcontextprotocol/server-postgres', 'postgresql://localhost/mydb'], env: {{ 'PATH': '/usr/local/bin:/usr/bin' }} }},
            'custom': {{ name: 'custom-server', command: '/path/to/server', args: [], env: {{ 'PATH': '/usr/local/bin:/usr/bin' }} }}
        }};
        function addMcpTemplate(t) {{ if (MCP_TEMPLATES[t]) {{ mcpServerTemplates.push({{ ...MCP_TEMPLATES[t] }}); renderMcpServers(); }} }}

        function addLocalMcpServer() {{
            const n = document.getElementById('new-local-mcp-name').value.trim(), c = document.getElementById('new-local-mcp-command').value.trim();
            if (!n || !c) {{ alert('Name and command required'); return; }}
            const args = document.getElementById('new-local-mcp-args').value.trim().split('\\n').map(a => a.trim()).filter(Boolean);
            const env = {{}};
            document.getElementById('new-local-mcp-env').value.trim().split('\\n').forEach(l => {{ const [k, ...v] = l.split('='); if (k && v.length) env[k.trim()] = v.join('=').trim(); }});
            mcpServerTemplates.push({{ name: n, command: c, args, env }});
            document.getElementById('new-local-mcp-name').value = ''; document.getElementById('new-local-mcp-command').value = ''; document.getElementById('new-local-mcp-args').value = ''; document.getElementById('new-local-mcp-env').value = '';
            renderMcpServers();
        }}
        function removeMcpTemplate(i) {{ mcpServerTemplates.splice(i, 1); renderMcpServers(); }}

        function updateDeploySummary() {{
            const gc = Object.values(groupConfig).filter(g => g.models.length > 0).length;
            const pc = policies.disabledBuiltinTools.length + Object.keys(policies.builtinToolPolicy).length + policies.allowedWorkspaceFolders.length + policies.coworkEgressAllowedHosts.length;
            const mc = managedMcpServers.length + mcpServerTemplates.length;
            document.getElementById('summary-groups').textContent = gc;
            document.getElementById('summary-policies').textContent = pc;
            document.getElementById('summary-mcp').textContent = mc;
        }}

        function previewConfig() {{
            const preview = document.getElementById('config-preview');
            if (preview.style.display === 'block') {{
                preview.style.display = 'none';
            }} else {{
                const config = buildFullConfig();
                preview.textContent = JSON.stringify(config, null, 2);
                preview.style.display = 'block';
            }}
        }}

        function buildFullConfig() {{
            const mappings = [];
            for (const [groupId, gc] of Object.entries(groupConfig)) {{
                if (gc.models.length === 0) continue;
                mappings.push({{ groupId, groupName: gc.groupName, roleName: gc.permissionSetName || gc.groupName.replace(/-/g, ''), models: gc.models, createNew: !gc.permissionSetName }});
            }}
            return {{ mappings, policies, managedMcpServers, mcpServerTemplates }};
        }}

        async function deployConfig() {{
            const config = buildFullConfig();
            if (config.mappings.length === 0) {{ showStatus('Please add at least one model to a group', 'error'); return; }}
            showStatus('Deploying configuration... This may take a minute.', 'info');
            document.querySelector('.main-content').classList.add('loading');
            try {{
                const res = await fetch('/admin/api/deploy', {{ method: 'POST', headers: {{ 'Content-Type': 'application/json' }}, body: JSON.stringify(config) }});
                const data = await res.json();
                if (data.success) {{
                    let msg = 'Deployment complete!<br><br>';
                    (data.results || []).forEach(r => {{ msg += (r.status === 'success' ? '&#10003;' : '&#10007;') + ' ' + r.group + ': ' + (r.model || '') + '<br>'; if (r.error) msg += '&nbsp;&nbsp;Error: ' + r.error + '<br>'; }});
                    showStatus(msg, 'success');
                    setTimeout(() => location.reload(), 2000);
                }} else showStatus('Error: ' + (data.error || 'Unknown error'), 'error');
            }} catch (e) {{ showStatus('Error: ' + e.message, 'error'); }}
            finally {{ document.querySelector('.main-content').classList.remove('loading'); }}
        }}

        function showStatus(msg, type) {{ const s = document.getElementById('status'); s.innerHTML = msg; s.className = 'status ' + type; }}

        async function viewPolicy(psName) {{
            try {{
                const res = await fetch('/admin/api/permission-set/' + encodeURIComponent(psName));
                const data = await res.json();
                if (data.error) {{ alert('Error: ' + data.error); return; }}
                const policy = data.inlinePolicy ? JSON.stringify(data.inlinePolicy, null, 2) : 'No inline policy';
                const modal = document.createElement('div');
                modal.style.cssText = 'position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.5);display:flex;justify-content:center;align-items:center;z-index:1000;';
                modal.innerHTML = '<div style="background:white;padding:30px;border-radius:12px;max-width:800px;max-height:80vh;overflow:auto;"><h3 style="margin-bottom:15px;">Permission Set: ' + escapeHtml(psName) + '</h3><p><strong>Description:</strong> ' + escapeHtml(data.description || 'N/A') + '</p><p><strong>Session Duration:</strong> ' + escapeHtml(data.sessionDuration) + '</p><h4 style="margin-top:15px;">Inline Policy:</h4><pre style="background:#1a1a2e;color:#e0e0e0;padding:15px;border-radius:8px;overflow:auto;font-size:12px;">' + escapeHtml(policy) + '</pre><button class="btn btn-primary" style="margin-top:15px;" onclick="this.parentElement.parentElement.remove()">Close</button></div>';
                document.body.appendChild(modal);
                modal.onclick = function(e) {{ if (e.target === modal) modal.remove(); }};
            }} catch (e) {{ alert('Error: ' + e.message); }}
        }}

        async function saveDraft(page) {{
            const statusEl = document.getElementById(page + '-save-status');
            statusEl.className = 'save-status saving';
            statusEl.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="animation: spin 1s linear infinite;"><circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/></svg> Saving...';

            const config = buildFullConfig();
            try {{
                const res = await fetch('/admin/api/config', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify(config)
                }});
                const data = await res.json();
                if (data.success) {{
                    statusEl.className = 'save-status saved';
                    statusEl.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"/></svg> Draft saved';
                    setTimeout(() => {{ statusEl.innerHTML = ''; statusEl.className = 'save-status'; }}, 3000);
                }} else {{
                    statusEl.className = 'save-status error';
                    statusEl.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg> Error: ' + (data.error || 'Failed to save');
                }}
            }} catch (e) {{
                statusEl.className = 'save-status error';
                statusEl.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg> Error: ' + e.message;
            }}
        }}

        init();
    </script>
</body>
</html>'''  # nosec B608



def generate_landing_page(user_email, config_groups, is_admin=False):
    """Generate landing page HTML matching admin console style"""
    group_cards = []

    for config_key, group_info in config_groups.items():
        buttons = []
        formats = group_info.get('formats', {})
        for fmt in ['macos', 'windows', 'json']:
            if formats.get(fmt):
                icon = {
                    'macos': '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2a10 10 0 1 0 10 10A10 10 0 0 0 12 2z"/><path d="M12 6v6l4 2"/></svg>',
                    'windows': '<svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><path d="M0 3.5l9.5-1.3v9.1H0V3.5zm10.5-1.5L24 0v11.3H10.5V2zm0 10.7H24V24l-13.5-1.9V12.7zM0 12.7h9.5v8.5L0 20.1v-7.4z"/></svg>',
                    'json': '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>'
                }[fmt]
                label = {'macos': 'macOS', 'windows': 'Windows', 'json': 'JSON'}[fmt]
                buttons.append(f'<a href="/download/{urllib.parse.quote(config_key)}-{fmt}" class="download-btn">{icon} {label}</a>')

        if buttons:
            # Split model string into individual models for display
            models_str = group_info.get('model', 'Unknown Model')
            models_list = [m.strip() for m in models_str.split(',')]
            models_html = ''.join([f'<div class="model-item">{esc(m)}</div>' for m in models_list])

            group_cards.append(f'''
                <div class="config-card">
                    <div class="card-header">
                        <h3>{esc(group_info.get('name', config_key))}</h3>
                    </div>
                    <div class="card-models">
                        <div class="models-label">Available Models:</div>
                        {models_html}
                    </div>
                    <div class="card-body">
                        <p>Download configuration for your platform:</p>
                        <div class="download-buttons">{''.join(buttons)}</div>
                    </div>
                </div>''')

    no_configs_msg = '''<div class="empty-state">
        <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="#ccc" stroke-width="1.5"><circle cx="12" cy="12" r="10"/><path d="M12 8v4m0 4h.01"/></svg>
        <h3>No Configurations Available</h3>
        <p>Contact your administrator to get access.</p>
    </div>''' if not group_cards else ''

    admin_nav = f'''<a class="nav-item" href="/admin">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"/><path d="M12 1v2m0 18v2M4.22 4.22l1.42 1.42m12.72 12.72l1.42 1.42M1 12h2m18 0h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42"/></svg>
        Admin Console
    </a>''' if is_admin else ''

    return f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Claude Desktop Configuration</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #f5f7fa;
            min-height: 100vh;
        }}
        .layout {{
            display: flex;
            min-height: 100vh;
        }}
        .sidebar {{
            width: 260px;
            background: linear-gradient(180deg, #1a1a2e 0%, #16213e 100%);
            color: white;
            position: fixed;
            height: 100vh;
            overflow-y: auto;
        }}
        .sidebar-header {{
            padding: 24px 20px;
            border-bottom: 1px solid rgba(255,255,255,0.1);
        }}
        .sidebar-header h1 {{
            font-size: 18px;
            font-weight: 600;
            margin-bottom: 4px;
        }}
        .sidebar-header .subtitle {{
            font-size: 12px;
            color: rgba(255,255,255,0.6);
        }}
        .sidebar-nav {{
            padding: 16px 0;
        }}
        .nav-item {{
            display: flex;
            align-items: center;
            padding: 12px 20px;
            color: rgba(255,255,255,0.8);
            text-decoration: none;
            transition: all 0.2s;
            border-left: 3px solid transparent;
        }}
        .nav-item:hover {{
            background: rgba(255,255,255,0.05);
            color: white;
        }}
        .nav-item.active {{
            background: rgba(102, 126, 234, 0.2);
            color: white;
            border-left-color: #667eea;
        }}
        .nav-item svg {{
            width: 18px;
            height: 18px;
            margin-right: 12px;
            opacity: 0.7;
        }}
        .sidebar-footer {{
            position: absolute;
            bottom: 0;
            left: 0;
            right: 0;
            padding: 16px 20px;
            border-top: 1px solid rgba(255,255,255,0.1);
            background: rgba(0,0,0,0.2);
        }}
        .user-info {{
            display: flex;
            align-items: center;
            margin-bottom: 12px;
        }}
        .user-avatar {{
            width: 32px;
            height: 32px;
            border-radius: 50%;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 14px;
            font-weight: 600;
            margin-right: 10px;
        }}
        .user-email {{
            font-size: 12px;
            color: rgba(255,255,255,0.8);
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
            max-width: 160px;
        }}
        .sidebar-links a {{
            font-size: 12px;
            color: rgba(255,255,255,0.6);
            text-decoration: none;
            margin-right: 12px;
        }}
        .sidebar-links a:hover {{
            color: white;
        }}
        .main-content {{
            flex: 1;
            margin-left: 260px;
            padding: 32px;
        }}
        .page-header {{
            margin-bottom: 32px;
        }}
        .page-header h2 {{
            font-size: 28px;
            color: #1a1a2e;
            margin-bottom: 8px;
        }}
        .page-header p {{
            color: #666;
            font-size: 15px;
        }}
        .config-grid {{
            display: flex;
            flex-direction: column;
            gap: 20px;
            margin-bottom: 32px;
            max-width: 700px;
        }}
        .config-card {{
            background: white;
            border-radius: 12px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.08);
            overflow: hidden;
            transition: all 0.2s;
        }}
        .config-card:hover {{
            box-shadow: 0 4px 12px rgba(0,0,0,0.12);
            transform: translateY(-2px);
        }}
        .card-header {{
            padding: 20px 20px 16px;
        }}
        .card-header h3 {{
            font-size: 20px;
            color: #1a1a2e;
            margin: 0;
            font-weight: 600;
        }}
        .card-models {{
            padding: 0 20px 16px;
            border-bottom: 1px solid #eee;
        }}
        .models-label {{
            font-size: 12px;
            color: #888;
            margin-bottom: 8px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }}
        .model-item {{
            font-size: 13px;
            color: #1565c0;
            background: #e3f2fd;
            padding: 6px 12px;
            border-radius: 6px;
            margin-bottom: 6px;
            font-family: monospace;
        }}
        .model-item:last-child {{
            margin-bottom: 0;
        }}
        .card-body {{
            padding: 20px;
        }}
        .card-body p {{
            color: #666;
            font-size: 14px;
            margin-bottom: 16px;
        }}
        .download-buttons {{
            display: flex;
            gap: 10px;
            flex-wrap: wrap;
        }}
        .download-btn {{
            display: inline-flex;
            align-items: center;
            gap: 8px;
            padding: 10px 16px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            border-radius: 8px;
            text-decoration: none;
            font-size: 13px;
            font-weight: 600;
            transition: all 0.2s;
        }}
        .download-btn:hover {{
            transform: translateY(-1px);
            box-shadow: 0 4px 12px rgba(102, 126, 234, 0.3);
        }}
        .download-btn svg {{
            width: 16px;
            height: 16px;
        }}
        .instructions {{
            background: white;
            border-radius: 12px;
            padding: 24px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.08);
        }}
        .instructions h3 {{
            font-size: 16px;
            color: #1a1a2e;
            margin-bottom: 16px;
            padding-bottom: 12px;
            border-bottom: 1px solid #eee;
        }}
        .instructions ol {{
            margin: 0;
            padding-left: 20px;
            color: #555;
            line-height: 2;
        }}
        .instructions li {{
            padding-left: 8px;
        }}
        .instructions strong {{
            color: #1a1a2e;
        }}
        .empty-state {{
            text-align: center;
            padding: 60px 20px;
            background: white;
            border-radius: 12px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.08);
        }}
        .empty-state svg {{
            margin-bottom: 16px;
        }}
        .empty-state h3 {{
            color: #333;
            margin-bottom: 8px;
        }}
        .empty-state p {{
            color: #888;
        }}
        @media (max-width: 768px) {{
            .sidebar {{ display: none; }}
            .main-content {{ margin-left: 0; }}
        }}
    </style>
</head>
<body>
    <div class="layout">
        <aside class="sidebar">
            <div class="sidebar-header">
                <h1>Claude Desktop</h1>
                <div class="subtitle">Configuration Portal</div>
            </div>
            <nav class="sidebar-nav">
                <a class="nav-item active" href="/">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
                    Downloads
                </a>
                {admin_nav}
            </nav>
            <div class="sidebar-footer">
                <div class="user-info">
                    <div class="user-avatar">{esc(user_email[0].upper()) if user_email else 'U'}</div>
                    <div class="user-email" title="{esc(user_email)}">{esc(user_email)}</div>
                </div>
                <div class="sidebar-links">
                    <a href="/logout">Logout</a>
                </div>
            </div>
        </aside>

        <main class="main-content">
            <div class="page-header">
                <h2>Download Configuration</h2>
                <p>Select your role and platform to download the Claude Desktop configuration</p>
            </div>

            {'<div class="config-grid">' + ''.join(group_cards) + '</div>' if group_cards else no_configs_msg}

            <div class="instructions">
                <h3>Setup Instructions</h3>
                <ol>
                    <li>Download the configuration for your <strong>role</strong> and <strong>platform</strong></li>
                    <li><strong>macOS:</strong> Double-click the .mobileconfig file, then approve in System Settings &gt; Privacy &amp; Security &gt; Profiles</li>
                    <li><strong>Windows:</strong> Double-click the .reg file and confirm the registry import</li>
                    <li><strong>JSON:</strong> Copy to <code>~/.config/claude/</code> (macOS/Linux) or <code>%APPDATA%\\Claude\\</code> (Windows)</li>
                    <li><strong>Restart Claude Desktop</strong> after installing the configuration</li>
                    <li>Click "Continue with Bedrock" and sign in with your corporate SSO</li>
                </ol>
                <div style="background: #e3f2fd; border-radius: 8px; padding: 12px 16px; margin-top: 16px; display: flex; align-items: flex-start; gap: 10px;">
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#1565c0" stroke-width="2" style="flex-shrink: 0; margin-top: 2px;"><circle cx="12" cy="12" r="10"/><path d="M12 16v-4M12 8h.01"/></svg>
                    <div style="color: #1565c0; font-size: 13px; line-height: 1.5;">
                        <strong>Auto-Updates:</strong> Once installed, Claude Desktop will automatically authenticate and receive policy/model updates every 30 minutes. No need to re-download the configuration.
                    </div>
                </div>
            </div>
        </main>
    </div>
</body>
</html>'''
