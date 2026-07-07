# ABOUTME: Tests for small pure-function helpers in index.py (cookies, session sign/verify)

import json

from tests.conftest import make_session_token


class TestParseCookies:
    def test_parses_multiple_cookies(self, idx):
        result = idx.parse_cookies('session=abc123; theme=dark')
        assert result == {'session': 'abc123', 'theme': 'dark'}

    def test_empty_header_returns_empty_dict(self, idx):
        assert idx.parse_cookies('') == {}
        assert idx.parse_cookies(None) == {}

    def test_ignores_malformed_entries_without_equals(self, idx):
        result = idx.parse_cookies('valid=1; garbage; other=2')
        assert result == {'valid': '1', 'other': '2'}

    def test_value_containing_equals_sign_kept_intact(self, idx):
        # e.g. signed session tokens can contain '='
        result = idx.parse_cookies('session=abc==; x=1')
        assert result['session'] == 'abc=='


class TestCreateAndValidateSession:
    def test_valid_unexpired_session_returns_data(self, idx, session_secret):
        token = make_session_token(idx, email='alice@example.com', exp_delta=3600)
        result = idx.validate_session(token)
        assert result['email'] == 'alice@example.com'

    def test_expired_session_returns_none(self, idx, session_secret):
        token = make_session_token(idx, email='alice@example.com', exp_delta=-3600)
        result = idx.validate_session(token)
        assert result is None

    def test_malformed_token_returns_none(self, idx, session_secret):
        assert idx.validate_session('not-a-valid-token') is None
        assert idx.validate_session('') is None

    def test_tampered_payload_is_rejected(self, idx, session_secret):
        """A session token whose payload was modified after signing (e.g. to
        change the email or extend expiry) must fail signature verification,
        proving the token is not forgeable without the signing secret."""
        token = make_session_token(idx, email='alice@example.com', exp_delta=3600)
        payload_b64, signature_b64 = token.split('.', 1)

        import base64
        forged_payload = json.dumps({'email': 'attacker@evil.com', 'exp': 9999999999})
        forged_payload_b64 = base64.urlsafe_b64encode(forged_payload.encode()).decode().rstrip('=')
        forged_token = f"{forged_payload_b64}.{signature_b64}"

        assert idx.validate_session(forged_token) is None

    def test_signature_from_different_secret_is_rejected(self, idx, session_secret, monkeypatch):
        """A token signed with a different key (simulating an attacker who
        doesn't have the real secret) must not validate."""
        token = make_session_token(idx, email='alice@example.com', exp_delta=3600)

        # Rotate the cached secret so validate_session verifies against a
        # different key than the one used to sign the token above.
        idx._session_signing_secret_cache = b'a-completely-different-key'

        assert idx.validate_session(token) is None


class TestJsonResponse:
    def test_default_status_is_200(self, idx):
        result = idx.json_response({'ok': True})
        assert result['statusCode'] == 200
        assert json.loads(result['body']) == {'ok': True}

    def test_custom_status_code(self, idx):
        result = idx.json_response({'error': 'nope'}, 403)
        assert result['statusCode'] == 403

    def test_includes_cors_header(self, idx):
        result = idx.json_response({})
        assert result['headers']['Access-Control-Allow-Origin'] == '*'
