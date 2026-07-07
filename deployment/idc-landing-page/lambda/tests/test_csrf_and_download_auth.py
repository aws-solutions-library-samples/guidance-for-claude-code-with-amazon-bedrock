# ABOUTME: Tests for CSRF Origin-header verification and the authenticated /download/ endpoint
# ABOUTME: Covers verify_request_origin() and handle_download()'s per-config_key authorization

import json

import boto3


def _s3(idx):
    return boto3.client('s3', region_name='us-east-1')


class TestVerifyRequestOrigin:
    def test_matching_origin_header_passes(self, idx):
        headers = {'Origin': 'https://example.cloudfront.net'}
        assert idx.verify_request_origin(headers, 'https://example.cloudfront.net') is True

    def test_matching_origin_with_trailing_slash_passes(self, idx):
        headers = {'Origin': 'https://example.cloudfront.net/'}
        assert idx.verify_request_origin(headers, 'https://example.cloudfront.net') is True

    def test_cross_origin_header_fails(self, idx):
        headers = {'Origin': 'https://attacker.example.com'}
        assert idx.verify_request_origin(headers, 'https://example.cloudfront.net') is False

    def test_missing_origin_and_referer_fails_closed(self, idx):
        assert idx.verify_request_origin({}, 'https://example.cloudfront.net') is False

    def test_falls_back_to_referer_when_origin_absent(self, idx):
        headers = {'Referer': 'https://example.cloudfront.net/admin'}
        assert idx.verify_request_origin(headers, 'https://example.cloudfront.net') is True

    def test_null_origin_fails(self, idx):
        headers = {'Origin': 'null'}
        assert idx.verify_request_origin(headers, 'https://example.cloudfront.net') is False

    def test_lowercase_header_key_also_works(self, idx):
        headers = {'origin': 'https://example.cloudfront.net'}
        assert idx.verify_request_origin(headers, 'https://example.cloudfront.net') is True


class TestAdminPostRequiresMatchingOrigin(object):
    """End-to-end: /admin/api/config POST must be rejected if Origin doesn't
    match, even with a fully valid admin session."""

    def _admin_event(self, path, method, origin=None, body=''):
        headers = {'Cookie': 'session=whatever', 'Host': 'legit.example.com'}
        if origin is not None:
            headers['Origin'] = origin
        return {
            'path': path,
            'httpMethod': method,
            'headers': headers,
            'body': body,
        }

    def test_post_with_wrong_origin_is_rejected(self, idx, monkeypatch):
        monkeypatch.setattr(idx, 'get_user_idc_groups', lambda email: ['Claude-Code-Admins'])
        monkeypatch.setattr(idx, 'validate_session', lambda token: {'email': 'admin@example.com'})
        monkeypatch.delenv('CLOUDFRONT_DOMAIN', raising=False)

        event = self._admin_event('/admin/api/config', 'POST', origin='https://attacker.example.com', body='{}')
        result = idx.lambda_handler(event, None)

        assert result['statusCode'] == 403
        assert 'Invalid request origin' in result['body']

    def test_post_with_no_origin_or_referer_is_rejected(self, idx, monkeypatch):
        """Browsers always send Origin on same-origin POSTs; a POST with
        neither Origin nor Referer must fail closed, not be allowed through."""
        monkeypatch.setattr(idx, 'get_user_idc_groups', lambda email: ['Claude-Code-Admins'])
        monkeypatch.setattr(idx, 'validate_session', lambda token: {'email': 'admin@example.com'})
        monkeypatch.delenv('CLOUDFRONT_DOMAIN', raising=False)

        event = self._admin_event('/admin/api/config', 'POST', origin=None, body='{}')
        result = idx.lambda_handler(event, None)

        assert result['statusCode'] == 403

    def test_post_with_correct_origin_is_allowed_through(self, idx, bucket, monkeypatch):
        monkeypatch.setattr(idx, 'get_user_idc_groups', lambda email: ['Claude-Code-Admins'])
        monkeypatch.setattr(idx, 'validate_session', lambda token: {'email': 'admin@example.com'})
        monkeypatch.delenv('CLOUDFRONT_DOMAIN', raising=False)

        # base_url is derived from the Host header when CLOUDFRONT_DOMAIN is unset.
        event = self._admin_event('/admin/api/config', 'POST', origin='https://legit.example.com', body='{"mappings": []}')
        result = idx.lambda_handler(event, None)

        # Not rejected for CSRF (403 with 'Invalid request origin'); the
        # actual save may succeed or fail for unrelated reasons, but must
        # not be blocked at the origin-check stage.
        if result['statusCode'] == 403:
            assert 'Invalid request origin' not in result['body']

    def test_get_requests_are_not_origin_checked(self, idx, monkeypatch):
        """GET requests (e.g. /admin/api/config GET) don't carry an Origin
        header from browsers and must not be blocked by this check."""
        monkeypatch.setattr(idx, 'get_user_idc_groups', lambda email: ['Claude-Code-Admins'])
        monkeypatch.setattr(idx, 'validate_session', lambda token: {'email': 'admin@example.com'})

        event = self._admin_event('/admin/api/config', 'GET')
        result = idx.lambda_handler(event, None)

        assert result['statusCode'] != 403


class TestHandleDownloadAuthorization:
    def _seed_developer_config(self, idx, bucket):
        _s3(idx).put_object(Bucket=bucket, Key='config/developer/default.json', Body=b'{}')
        _s3(idx).put_object(Bucket=bucket, Key='config/developer/Claude.mobileconfig', Body=b'<plist/>')

    def test_admin_can_download_any_group(self, idx, bucket, monkeypatch):
        self._seed_developer_config(idx, bucket)
        monkeypatch.setattr(idx, 'get_user_idc_groups', lambda email: ['Claude-Code-Admins'])
        result = idx.handle_download('developer-macos', {'email': 'admin@example.com'})
        assert result['statusCode'] == 302

    def test_matching_group_member_can_download_own_group(self, idx, bucket, monkeypatch):
        self._seed_developer_config(idx, bucket)
        monkeypatch.setattr(idx, 'get_user_idc_groups', lambda email: ['Claude-Code-Developers'])
        result = idx.handle_download('developer-macos', {'email': 'dev@example.com'})
        assert result['statusCode'] == 302

    def test_unrelated_user_cannot_download_other_groups_config(self, idx, bucket, monkeypatch):
        """The core vulnerability: an authenticated user with no relation to
        'developer' must not be able to download developer's MDM profile
        (AWS account ID, IDC SSO details, bootstrap OIDC config) by guessing
        the config_key."""
        self._seed_developer_config(idx, bucket)
        monkeypatch.setattr(idx, 'get_user_idc_groups', lambda email: ['Claude-Code-Contractors'])
        result = idx.handle_download('developer-macos', {'email': 'contractor@example.com'})
        assert result['statusCode'] == 403

    def test_no_groups_resolved_cannot_download_anything(self, idx, bucket, monkeypatch):
        self._seed_developer_config(idx, bucket)
        monkeypatch.setattr(idx, 'get_user_idc_groups', lambda email: [])
        result = idx.handle_download('developer-macos', {'email': 'nobody@example.com'})
        assert result['statusCode'] == 403

    def test_unknown_format_returns_404_not_403(self, idx, bucket, monkeypatch):
        monkeypatch.setattr(idx, 'get_user_idc_groups', lambda email: ['Claude-Code-Admins'])
        result = idx.handle_download('developer-invalidformat', {'email': 'admin@example.com'})
        assert result['statusCode'] == 404

    def test_download_name_strips_quote_characters(self, idx, bucket, monkeypatch):
        """A config_key containing a double-quote must not be able to break
        out of the Content-Disposition filename="..." attribute. The quote
        is stripped from download_name before it's used, so it should never
        appear un-percent-encoded in the resulting presigned URL."""
        monkeypatch.setattr(idx, 'get_user_idc_groups', lambda email: ['Claude-Code-Admins'])
        malicious_key = 'developer";x="injected'
        _s3(idx).put_object(Bucket=bucket, Key=f'config/{malicious_key}/default.json', Body=b'{}')

        result = idx.handle_download(f'{malicious_key}-json', {'email': 'admin@example.com'})

        assert result['statusCode'] == 302
        location = result['headers']['Location']
        # A raw '"' would indicate the sanitization didn't strip it (S3
        # presigned URLs percent-encode query values, so a literal quote
        # surviving into the URL means it wasn't removed beforehand).
        assert '"' not in location
