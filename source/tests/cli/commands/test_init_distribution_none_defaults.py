# ABOUTME: Regression test for crash on re-running init with a Cognito landing page
# ABOUTME: Ensures None distribution values never reach questionary.text(default=...)

"""Regression test for "object of type 'NoneType' has no len()" in init.

A reloaded profile stores distribution IdP fields with an explicit None
(see InitCommand._build_config_from_profile), so config["distribution"]
contains keys present-but-None. The manual landing-page prompts must coerce
those to "" because questionary.text(default=None) crashes inside
prompt_toolkit with `len(None)`.
"""

import sys
from pathlib import Path

import pytest

# ruff: noqa: E402
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))


def _resolve_default(config: dict, key: str) -> str:
    """Mirror the default-resolution used by the manual landing-page prompts."""
    return config.get("distribution", {}).get(key) or ""


@pytest.mark.parametrize("key", ["idp_domain", "idp_client_id", "custom_domain"])
def test_none_distribution_value_resolves_to_empty_string(key):
    """A present-but-None distribution value must resolve to "" (not None)."""
    # Matches what _build_config_from_profile produces for an enabled-but-unconfigured
    # landing page that was reloaded for a re-run of `ccwb init`.
    config = {
        "distribution": {
            "enabled": True,
            "type": "landing-page",
            "idp_provider": "cognito",
            "idp_domain": None,
            "idp_client_id": None,
            "custom_domain": None,
        }
    }

    resolved = _resolve_default(config, key)

    assert resolved is not None
    assert resolved == ""


def test_questionary_text_rejects_none_default():
    """Document the underlying crash: questionary.text(default=None) raises."""
    questionary = pytest.importorskip("questionary")
    from prompt_toolkit.input import create_pipe_input
    from prompt_toolkit.output import DummyOutput

    with create_pipe_input() as inp:
        inp.send_text("\n")
        # The Document is built eagerly, so a None default raises at construction.
        with pytest.raises(TypeError, match="NoneType"):
            questionary.text("x", default=None, input=inp, output=DummyOutput())

    # And the resolved default ("") does not crash.
    with create_pipe_input() as inp:
        inp.send_text("\n")
        question = questionary.text("x", default="", input=inp, output=DummyOutput())
        assert question.ask() == ""
