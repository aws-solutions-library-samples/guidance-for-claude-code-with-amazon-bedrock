# ABOUTME: Regression tests for admin-group exact-match and fail-closed group filtering
# ABOUTME: Covers the substring-match privilege escalation and fail-open landing-page bugs

import json

import boto3


def _s3(idx):
    return boto3.client('s3', region_name='us-east-1')


class TestAdminGroupExactMatch:
    """ADMIN_GROUP defaults to 'Claude-Code-Admins'. The check must be an
    exact (case-insensitive) match, not a substring match - otherwise any
    IDC group whose name merely contains 'claude-code-admins' (e.g.
    'Non-Claude-Code-Admins-Vendors') would grant admin access."""

    def test_exact_match_grants_admin(self, idx, monkeypatch):
        monkeypatch.setattr(idx, 'get_user_idc_groups', lambda email: ['Claude-Code-Admins'])
        monkeypatch.setattr(idx, 'validate_session', lambda token: {'email': 'admin@example.com'})

        event = {
            'path': '/admin',
            'httpMethod': 'GET',
            'headers': {'Cookie': 'session=whatever'},
        }
        result = idx.lambda_handler(event, None)
        # serve_admin_page will be invoked; we only assert it's not the 403 page
        assert result['statusCode'] != 403

    def test_case_insensitive_exact_match_grants_admin(self, idx, monkeypatch):
        monkeypatch.setattr(idx, 'get_user_idc_groups', lambda email: ['claude-code-admins'])
        monkeypatch.setattr(idx, 'validate_session', lambda token: {'email': 'admin@example.com'})

        event = {
            'path': '/admin',
            'httpMethod': 'GET',
            'headers': {'Cookie': 'session=whatever'},
        }
        result = idx.lambda_handler(event, None)
        assert result['statusCode'] != 403

    def test_substring_containing_group_name_does_not_grant_admin(self, idx, monkeypatch):
        """The exact vulnerability: a group name that merely contains the
        admin group name as a substring must NOT grant access."""
        monkeypatch.setattr(idx, 'get_user_idc_groups', lambda email: ['Non-Claude-Code-Admins-Vendors'])
        monkeypatch.setattr(idx, 'validate_session', lambda token: {'email': 'vendor@example.com'})

        event = {
            'path': '/admin',
            'httpMethod': 'GET',
            'headers': {'Cookie': 'session=whatever'},
        }
        result = idx.lambda_handler(event, None)
        assert result['statusCode'] == 403

    def test_unrelated_group_does_not_grant_admin(self, idx, monkeypatch):
        monkeypatch.setattr(idx, 'get_user_idc_groups', lambda email: ['Claude-Code-Developers'])
        monkeypatch.setattr(idx, 'validate_session', lambda token: {'email': 'dev@example.com'})

        event = {
            'path': '/admin',
            'httpMethod': 'GET',
            'headers': {'Cookie': 'session=whatever'},
        }
        result = idx.lambda_handler(event, None)
        assert result['statusCode'] == 403


class TestServeLandingPageFailsClosed:
    """A user whose IDC group lookup returns empty (e.g. their email doesn't
    resolve to any real IDC user, or the lookup fails) must see NO config
    groups, not every group's download links."""

    def _seed_one_group(self, idx, bucket):
        _s3(idx).put_object(
            Bucket=bucket,
            Key='config/developer/default.json',
            Body=json.dumps({'inferenceModels': [{'labelOverride': 'Sonnet'}]}).encode('utf-8'),
        )
        _s3(idx).put_object(Bucket=bucket, Key='config/developer/Claude.mobileconfig', Body=b'<plist/>')

    def test_no_groups_resolved_shows_no_config_cards(self, idx, bucket, monkeypatch):
        self._seed_one_group(idx, bucket)
        monkeypatch.setattr(idx, 'get_user_idc_groups', lambda email: [])

        result = idx.serve_landing_page({'email': 'nobody@example.com'}, 'https://example.com')

        # 'config-card' (the CSS selector) is always present in the template;
        # the actual per-card markup is 'class="config-card"' - assert that
        # specific marker is absent, i.e. no cards were rendered.
        assert 'class="config-card"' not in result['body']

    def test_admin_still_sees_all_groups(self, idx, bucket, monkeypatch):
        self._seed_one_group(idx, bucket)
        monkeypatch.setattr(idx, 'get_user_idc_groups', lambda email: ['Claude-Code-Admins'])

        result = idx.serve_landing_page({'email': 'admin@example.com'}, 'https://example.com')

        assert 'class="config-card"' in result['body']

    def test_matching_group_sees_own_group(self, idx, bucket, monkeypatch):
        self._seed_one_group(idx, bucket)
        monkeypatch.setattr(idx, 'get_user_idc_groups', lambda email: ['Claude-Code-Developers'])

        result = idx.serve_landing_page({'email': 'dev@example.com'}, 'https://example.com')

        assert 'class="config-card"' in result['body']
