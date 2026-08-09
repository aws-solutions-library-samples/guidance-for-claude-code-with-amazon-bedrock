"""Regression test: OktaDomain AllowedPattern must accept Okta custom URL domains.

The original pattern '^[a-zA-Z0-9][a-zA-Z0-9-]*\\.okta(-emea)?\\.com$' only allowed
*.okta.com / *.okta-emea.com, which blocked:
  - Okta custom URL domains hosted on the customer's own domain (login.company.com)
  - Okta preview orgs (*.oktapreview.com)
  - Okta for Government orgs (*.okta-gov.com) — relevant for GovCloud
The domain is substituted into `https://${OktaDomain}` for the IAM OIDC provider,
so it must be a valid FQDN with no scheme/path/port, but need not be on okta.com.
"""

import re
from pathlib import Path

import pytest
import yaml

INFRA_DIR = Path(__file__).resolve().parents[2] / "deployment" / "infrastructure"


class CfnLoader(yaml.SafeLoader):
    pass


def _cfn_tag_constructor(loader, tag_suffix, node):
    if isinstance(node, yaml.ScalarNode):
        return loader.construct_scalar(node)
    elif isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node)
    elif isinstance(node, yaml.MappingNode):
        return loader.construct_mapping(node)


CfnLoader.add_multi_constructor("!", _cfn_tag_constructor)


def _okta_domain_pattern() -> str:
    template_path = INFRA_DIR / "bedrock-auth-okta.yaml"
    with open(template_path, encoding="utf-8") as f:
        template = yaml.load(f, Loader=CfnLoader)
    return template["Parameters"]["OktaDomain"]["AllowedPattern"]


class TestOktaDomainPattern:
    """OktaDomain must accept org domains AND custom URL domains, reject malformed input."""

    @pytest.mark.parametrize(
        "domain",
        [
            "company.okta.com",
            "company.okta-emea.com",
            "company.oktapreview.com",
            "company.okta-gov.com",  # Okta for Government
            "login.company.com",  # custom URL domain
            "id.acme.io",
            "sso.enterprise.co.uk",
            "auth.example.com",
        ],
    )
    def test_pattern_accepts_valid_domains(self, domain):
        pattern = _okta_domain_pattern()
        assert re.match(pattern, domain), f"Pattern {pattern!r} should accept {domain!r}"

    @pytest.mark.parametrize(
        "domain",
        [
            "https://company.okta.com",  # scheme
            "company.okta.com/oauth2/default",  # path
            "company.okta.com:443",  # port
            "company.okta.com.",  # trailing dot
            "company..com",  # empty label
            "-bad.okta.com",  # label starts with hyphen
            "localhost",  # no dot / no TLD
            "company.c",  # single-char TLD
            "company.okta.com ",  # trailing whitespace
            "",  # empty
        ],
    )
    def test_pattern_rejects_invalid_domains(self, domain):
        pattern = _okta_domain_pattern()
        assert not re.match(pattern, domain), f"Pattern {pattern!r} should reject {domain!r}"

    def test_pattern_no_longer_hardcodes_okta_com(self):
        """Guard against re-introducing an okta.com-only constraint."""
        pattern = _okta_domain_pattern()
        assert "okta" not in pattern.lower(), "OktaDomain pattern must not hard-code 'okta' (blocks custom domains)"
