# ABOUTME: Regression test that every CodeBuild buildspec command parses as a YAML string
# ABOUTME: Guards against unquoted PowerShell ': ' + '{ }' lines that CodeBuild reads as mappings

"""Regression test for the Windows CodeBuild buildspec YAML bug.

The buildspecs are embedded as literal block scalars (``BuildSpec: |``) inside
``codebuild-windows.yaml``. A ``post_build`` command added by #472 was an
unquoted YAML scalar containing both a colon-space (``"FATAL: ..."``) and
PowerShell flow-mapping braces (``{ ... }``). CodeBuild's buildspec parser read
it as a YAML mapping instead of a string and failed every Windows build in
DOWNLOAD_SOURCE with::

    YAML_FILE_ERROR: Expected Commands[2] to be of string type: found subkeys
    instead at line 40, value of the key tag on line 39 might be empty

The precise oracle is dict-vs-str: a broken command parses to a ``dict``; a
correctly quoted one parses to a ``str``. cfn-lint does not catch this because
it validates the CloudFormation template, not the embedded buildspec's scalar
semantics.
"""

from pathlib import Path

import pytest
import yaml


INFRA_DIR = Path(__file__).resolve().parents[2] / "deployment" / "infrastructure"
TEMPLATE = INFRA_DIR / "codebuild-windows.yaml"


# CloudFormation intrinsic tags (!Sub, !Ref, !GetAtt, ...) break a plain
# SafeLoader. This loader treats every "!"-tag as its underlying node value,
# which is enough to reach the BuildSpec block scalars.
class CfnLoader(yaml.SafeLoader):
    pass


def _cfn_tag_constructor(loader, tag_suffix, node):
    if isinstance(node, yaml.ScalarNode):
        return loader.construct_scalar(node)
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node)
    if isinstance(node, yaml.MappingNode):
        return loader.construct_mapping(node)
    return None


CfnLoader.add_multi_constructor("!", _cfn_tag_constructor)


def _collect_buildspecs() -> dict[str, str]:
    """Return {project logical id: BuildSpec string} for every build project."""
    with open(TEMPLATE, encoding="utf-8") as f:
        template = yaml.load(f, Loader=CfnLoader)

    specs = {}
    for logical_id, resource in template["Resources"].items():
        if resource.get("Type") != "AWS::CodeBuild::Project":
            continue
        buildspec = resource["Properties"]["Source"].get("BuildSpec")
        if isinstance(buildspec, str):
            specs[logical_id] = buildspec
    return specs


def _all_commands(buildspec: str):
    """Yield (phase, index, command) for every command in every phase."""
    # The BuildSpec is a plain literal block scalar -> no CFN tags inside it.
    spec = yaml.safe_load(buildspec)
    for phase_name, phase in spec.get("phases", {}).items():
        for idx, command in enumerate(phase.get("commands", [])):
            yield phase_name, idx, command


def test_template_has_build_projects():
    """Guard the test itself: we must actually be inspecting buildspecs."""
    specs = _collect_buildspecs()
    assert specs, "no CodeBuild BuildSpec blocks found in codebuild-windows.yaml"
    # Windows + linux-x64 + linux-arm64
    assert len(specs) >= 3, f"expected >=3 build projects, found {sorted(specs)}"


@pytest.mark.parametrize("logical_id", sorted(_collect_buildspecs()))
def test_every_buildspec_command_is_a_string(logical_id):
    """Every command in every phase must parse as a YAML string, not a mapping.

    This is the exact discriminator that distinguishes the broken buildspec
    (unquoted ``{ Write-Error "FATAL: ..." }`` parses to a dict) from the fixed
    one (single-quoted scalar parses to a str).
    """
    buildspec = _collect_buildspecs()[logical_id]
    for phase_name, idx, command in _all_commands(buildspec):
        assert isinstance(command, str), (
            f"{logical_id} {phase_name}.commands[{idx}] parsed as "
            f"{type(command).__name__}, not str: {command!r}. An unquoted "
            f"PowerShell command with ': ' and '{{ }}' is read as a YAML "
            f"mapping and breaks CodeBuild buildspec parsing."
        )


def test_windows_post_build_preserves_powershell_semantics():
    """The fix must keep PowerShell byte-for-byte, not just make it parse.

    Guards against a future 'fix' that quotes the lines but mangles the inner
    PowerShell quoting (e.g. dropping the single quotes around the package hint
    or the double quotes around the FATAL message).
    """
    win = _collect_buildspecs()["WindowsBuildProject"]
    commands = [c for _, _, c in _all_commands(win)]
    assert all(isinstance(c, str) for c in commands), (
        "WindowsBuildProject has a non-string command (see "
        "test_every_buildspec_command_is_a_string)"
    )
    joined = "\n".join(commands)

    # Single-quoted PowerShell literal must survive intact (not "" or dropped).
    assert "'ccwb package --go'" in joined, (
        "PowerShell single-quoted literal 'ccwb package --go' was lost or "
        "mangled by YAML quoting"
    )
    # Double-quoted PowerShell strings must survive intact.
    assert '"FATAL: credential-process-windows.exe was not built.' in joined
    assert '"FATAL: otel-helper-windows.exe was not built.' in joined
    assert '$([math]::Round($_.Length/1MB, 1))' in joined
