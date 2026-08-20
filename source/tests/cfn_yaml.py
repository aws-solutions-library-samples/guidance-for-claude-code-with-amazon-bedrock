# ABOUTME: Shared CloudFormation-aware YAML loading for the test suite.
# ABOUTME: Replaces the per-file loader classes that each test used to hand-roll.

"""CloudFormation-aware YAML loading for tests.

CloudFormation templates use short-form intrinsic tags (``!Ref``, ``!Sub``,
``!GetAtt``) that plain :func:`yaml.safe_load` cannot parse. Two shapes are
useful when asserting against a template, so this module exposes one loader for
each:

``load_resolved``
    Collapses every tag to its payload — ``!Ref Foo`` becomes ``"Foo"`` and
    ``!GetAtt Alb.DNSName`` becomes ``"Alb.DNSName"``. Convenient for
    substring and regex assertions over rendered-ish values.

``load_intrinsics``
    Keeps the canonical long form — ``!Ref Foo`` becomes ``{"Ref": "Foo"}``
    and ``!GetAtt Alb.DNSName`` becomes ``{"Fn::GetAtt": ["Alb", "DNSName"]}``.
    Use this when a test must tell an intrinsic apart from a literal string.

Pick deliberately: a test written against one shape will silently change
meaning under the other.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import cfn_flip
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
INFRA_DIR = REPO_ROOT / "deployment" / "infrastructure"


def iter_templates(pattern: str = "*.yaml") -> list[Path]:
    """Return every CloudFormation template in ``deployment/infrastructure``.

    Sorted so that ``pytest.mark.parametrize`` ids stay stable across runs.
    """
    return sorted(INFRA_DIR.glob(pattern))


class _ResolvedLoader(yaml.SafeLoader):
    """SafeLoader that also understands CloudFormation short tags."""


def _resolve_tag(loader: yaml.SafeLoader, tag_suffix: str, node: yaml.Node) -> Any:
    """Return a CFN tag's payload, discarding which tag it was."""
    if isinstance(node, yaml.ScalarNode):
        return loader.construct_scalar(node)
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node)
    if isinstance(node, yaml.MappingNode):
        return loader.construct_mapping(node)
    return None


_ResolvedLoader.add_multi_constructor("!", _resolve_tag)


def load_resolved(path: str | Path) -> Any:
    """Load a template with each CFN tag collapsed to its payload value."""
    # Driving the loader directly is what PyYAML's generic load helper does
    # internally, so this is not a shortcut: _ResolvedLoader derives from
    # SafeLoader and adds only CFN tag constructors, meaning arbitrary Python
    # object construction is unreachable either way. Routing through the generic
    # helper with an explicit Loader= would add nothing but trips static
    # analysers that match the call by name without resolving which loader it
    # was handed.
    loader = _ResolvedLoader(Path(path).read_text(encoding="utf-8"))
    try:
        return loader.get_single_data()
    finally:
        loader.dispose()


def load_intrinsics(path: str | Path) -> Any:
    """Load a template keeping CFN intrinsics in canonical long form."""
    # cfn_flip is the parser the CLI itself uses (see cli/utils/cloudformation.py).
    return cfn_flip.load_yaml(Path(path).read_text(encoding="utf-8"))
