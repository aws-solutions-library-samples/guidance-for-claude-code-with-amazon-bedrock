# ABOUTME: Regression tests for verify_cognito_access_token() using the OIDC userInfo endpoint
# ABOUTME: Guards against reverting to Cognito's GetUser API, which requires a scope our app
# ABOUTME: clients don't request (aws.cognito.signin.user.admin) and caused a login loop.

import json
from urllib.error import HTTPError
from io import BytesIO


class _FakeResponse:
    def __init__(self, body: dict):
        self._body = json.dumps(body).encode('utf-8')

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class TestVerifyCognitoAccessToken:
    def test_empty_token_returns_none_without_network_call(self, idx, monkeypatch):
        def fail_if_called(*args, **kwargs):
            raise AssertionError('should not make a network call for an empty token')
        monkeypatch.setattr(idx.urllib.request, 'urlopen', fail_if_called)

        assert idx.verify_cognito_access_token('') is None
        assert idx.verify_cognito_access_token(None) is None

    def test_valid_token_calls_userinfo_endpoint_and_returns_email(self, idx, monkeypatch):
        captured = {}

        def fake_urlopen(req, timeout=10):
            captured['url'] = req.full_url
            captured['auth_header'] = req.get_header('Authorization')
            return _FakeResponse({'email': 'alice@example.com', 'username': 'alice', 'sub': 'abc-123'})

        monkeypatch.setattr(idx.urllib.request, 'urlopen', fake_urlopen)

        result = idx.verify_cognito_access_token('a-real-looking-access-token')

        assert result == {'email': 'alice@example.com', 'username': 'alice'}
        assert captured['url'] == f"https://{idx.COGNITO_DOMAIN}/oauth2/userInfo"
        assert captured['auth_header'] == 'Bearer a-real-looking-access-token'

    def test_falls_back_to_sub_when_username_absent(self, idx, monkeypatch):
        def fake_urlopen(req, timeout=10):
            return _FakeResponse({'email': 'bob@example.com', 'sub': 'sub-456'})
        monkeypatch.setattr(idx.urllib.request, 'urlopen', fake_urlopen)

        result = idx.verify_cognito_access_token('token')
        assert result['username'] == 'sub-456'

    def test_cognito_rejection_returns_none(self, idx, monkeypatch):
        """Cognito returns a non-2xx (e.g. 401) for expired/revoked/malformed
        tokens - urlopen raises HTTPError in that case, which must result
        in None, not an unhandled exception."""
        def fake_urlopen(req, timeout=10):
            raise HTTPError(req.full_url, 401, 'Unauthorized', {}, BytesIO(b'{"error":"invalid_token"}'))
        monkeypatch.setattr(idx.urllib.request, 'urlopen', fake_urlopen)

        assert idx.verify_cognito_access_token('expired-or-bad-token') is None

    def test_does_not_require_admin_scope(self, idx, monkeypatch):
        """Regression guard: this must use GET /oauth2/userInfo (needs only
        'openid' scope), NOT the GetUser API (needs the reserved
        'aws.cognito.signin.user.admin' scope our app clients don't
        request). Asserting the exact URL path locks in that choice."""
        captured_urls = []

        def fake_urlopen(req, timeout=10):
            captured_urls.append(req.full_url)
            return _FakeResponse({'email': 'x@example.com'})
        monkeypatch.setattr(idx.urllib.request, 'urlopen', fake_urlopen)

        idx.verify_cognito_access_token('token')

        assert len(captured_urls) == 1
        assert '/oauth2/userInfo' in captured_urls[0]
