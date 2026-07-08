# ABOUTME: Declarative extra-files list shared by the package and distribute commands
# ABOUTME: Provides OS-token matching and validation for admin-defined extra files

"""Admin-defined extra files for packaging and distribution.

Admins can list extra files/folders (preinstall scripts, certificates, CA
bundles, etc.) to ship *on top of* the generated package. The list lives in the
admin-side deployment profile (never in the runtime ``config.json`` and never
synced to the Go credential-process) and is consumed by two commands:

- ``package`` copies the extras that apply to at least one platform being
  built (``--target-platform``) into the build folder.
- ``distribute`` filters extras per-OS across its three archive builders.

Each entry is a plain dict with three keys::

    {"name": "certs", "targets": "all", "from": "~/secure/azure-oidc-certs"}

- ``name``    — path inside the package (relative, no traversal).
- ``targets`` — which machines get it: a single token or a list of tokens.
- ``from``    — source path on the admin's machine (a file or a whole folder).

The ``targets`` tokens form a hierarchy ``all`` > family > arch so that a single
list can be resolved against three different platform vocabularies (see
``extra_applies_to``).
"""

from __future__ import annotations

from typing import Any

# Arch-specific tokens mapped to their OS family.
_FAMILY_OF: dict[str, str] = {
    "macos-arm64": "macos",
    "macos-intel": "macos",
    "linux-x64": "linux",
    "linux-arm64": "linux",
    "windows": "windows",
}

# All family tokens.
_FAMILIES: frozenset[str] = frozenset(_FAMILY_OF.values())

# Every token an admin may put in ``targets``.
VALID_TARGET_TOKENS: frozenset[str] = frozenset({"all"}) | _FAMILIES | frozenset(_FAMILY_OF)

# Landing-page family tokens -> internal family. The landing page groups by
# family only (no arch split), so ``mac`` maps to the ``macos`` family.
_LANDING_FAMILY: dict[str, str] = {"mac": "macos", "linux": "linux", "windows": "windows"}

# Generated artifacts and reserved directories that an extra file's ``name``
# must never collide with — clobbering these would silently break the package.
RESERVED_NAMES: frozenset[str] = frozenset(
    {
        "config.json",
        "install.sh",
        "install.bat",
        "ccwb-install.ps1",
        "readme.md",
        "collector-config.yaml",
        "otel-helper.sh",
        "otel-helper.ps1",
        "otel-helper.cmd",
        "cowork-3p.reg",
        "cowork-3p.mobileconfig",
        "cowork-3p-config.json",
    }
)

# Reserved top-level directory names (an extra must not shadow these).
RESERVED_DIRS: frozenset[str] = frozenset({"claude-settings"})

# Prefixes of generated binaries an extra's top-level name must not collide with.
_RESERVED_PREFIXES: tuple[str, ...] = (
    "credential-process-",
    "otel-helper-",
    "otelcol-",
)


def normalize_targets(targets: Any) -> list[str]:
    """Return ``targets`` as a lowercased list of tokens.

    Accepts a single string or a list of strings. Non-string members are
    coerced defensively but validation (``validate_extra_files``) is what
    rejects unknown tokens.
    """
    if isinstance(targets, str):
        raw = [targets]
    elif isinstance(targets, (list, tuple)):
        raw = list(targets)
    else:
        return []
    return [str(t).strip().lower() for t in raw]


def extra_applies_to(targets: Any, platform_token: str) -> bool:
    """True if an entry with ``targets`` should be included for ``platform_token``.

    ``platform_token`` is one of:

    - a per-OS token: ``windows``, ``linux-x64``, ``linux-arm64``,
      ``macos-arm64``, ``macos-intel`` (used by ``_create_per_os_archives``);
    - a landing family: ``mac``, ``linux``, ``windows`` (used by
      ``_upload_landing_page_packages``).

    The all-OS archive (``_create_archive``) does not call this — it includes
    every extra unconditionally.

    Matching rules (hierarchy ``all`` > family > arch):

    - ``all`` matches everything.
    - An exact token match always applies.
    - A family target (``macos``) matches any arch in that family and the
      family/landing token.
    - An arch target (``macos-arm64``) matches its own per-OS token and its
      landing family (``mac``) — the landing family has no arch split, so any
      arch-specific extra for that family must appear in it.
    """
    plat = platform_token.strip().lower()
    # Resolve the platform to its family, whether it's a per-OS token,
    # an arch token, or a landing-family token.
    plat_family = _LANDING_FAMILY.get(plat) or _FAMILY_OF.get(plat) or (plat if plat in _FAMILIES else None)

    for token in normalize_targets(targets):
        if token == "all":
            return True
        if token == plat:
            return True
        # Family target matches any platform in that family.
        if token in _FAMILIES and token == plat_family:
            return True
        # Arch target matches its landing family (family has no arch split).
        token_family = _FAMILY_OF.get(token)
        if token_family and plat in _LANDING_FAMILY and _LANDING_FAMILY[plat] == token_family:
            return True
    return False


def extra_applies_to_any(targets: Any, platform_tokens: Any) -> bool:
    """True if an entry with ``targets`` applies to at least one platform in
    ``platform_tokens``.

    ``platform_tokens`` uses the ``platforms_to_build`` vocabulary from the
    ``package`` command: per-OS arch tokens (``macos-arm64``, ``windows``, …)
    plus the generic family tokens ``macos`` / ``linux`` that the non-Go build
    path can produce. A family token is expanded to its arches so an
    arch-targeted extra (e.g. ``macos-arm64``) still ships in a generic
    ``macos`` build.
    """
    expanded: set[str] = set()
    for p in platform_tokens or []:
        tok = str(p).strip().lower()
        expanded.add(tok)
        expanded.update(arch for arch, family in _FAMILY_OF.items() if family == tok)
    return any(extra_applies_to(targets, tok) for tok in expanded)


def _name_errors(name: Any) -> list[str]:
    """Validate the ``name`` field for path safety and reserved collisions."""
    errors: list[str] = []
    if not isinstance(name, str) or not name.strip():
        return ["extra_files: 'name' must be a non-empty string"]

    # Reject absolute paths and Windows drive letters (e.g. "C:\\x").
    if name.startswith(("/", "\\")) or (len(name) >= 2 and name[1] == ":"):
        errors.append(f"extra_files: 'name' must be a relative path, got '{name}'")

    # Reject traversal in either separator style. Splitting on both catches
    # "a/../b" and "a\\..\\b" regardless of the host OS.
    segments = name.replace("\\", "/").split("/")
    if ".." in segments:
        errors.append(f"extra_files: 'name' must not contain '..' path segments, got '{name}'")

    # Reserved-name / reserved-dir collision on the FIRST path segment
    # (case-insensitive). The first segment is what lands at the package root.
    top = segments[0].lower() if segments else ""
    if top in RESERVED_NAMES or top in RESERVED_DIRS:
        errors.append(f"extra_files: 'name' collides with a generated artifact: '{name}'")
    elif top.startswith(_RESERVED_PREFIXES):
        errors.append(f"extra_files: 'name' collides with a generated binary: '{name}'")

    return errors


def validate_extra_files(entries: Any) -> list[str]:
    """Validate an ``extra_files`` list; return human-readable error strings.

    An empty list (or non-error input) returns ``[]``. Presence of the ``from``
    source path is intentionally NOT checked here — that is a build-time concern
    handled by ``package`` (fail-fast). This validates shape, ``name`` safety,
    ``targets`` tokens, and that ``from`` is a non-empty string.
    """
    if entries in (None, []):
        return []
    if not isinstance(entries, list):
        return ["extra_files: must be a list of entries"]

    errors: list[str] = []
    for i, entry in enumerate(entries):
        prefix = f"extra_files[{i}]"
        if not isinstance(entry, dict):
            errors.append(f"{prefix}: must be an object with 'name', 'targets', 'from'")
            continue

        expected = {"name", "targets", "from"}
        keys = set(entry)
        missing = expected - keys
        extra = keys - expected
        if missing:
            errors.append(f"{prefix}: missing key(s): {', '.join(sorted(missing))}")
        if extra:
            errors.append(f"{prefix}: unexpected key(s): {', '.join(sorted(extra))}")

        for err in _name_errors(entry.get("name")):
            errors.append(f"{prefix}: {err.split(': ', 1)[-1]}")

        tokens = normalize_targets(entry.get("targets"))
        if not tokens:
            errors.append(f"{prefix}: 'targets' must be a token or list of tokens")
        else:
            unknown = [t for t in tokens if t not in VALID_TARGET_TOKENS]
            if unknown:
                errors.append(f"{prefix}: unknown target(s) {unknown}; valid: {', '.join(sorted(VALID_TARGET_TOKENS))}")

        src = entry.get("from")
        if not isinstance(src, str) or not src.strip():
            errors.append(f"{prefix}: 'from' must be a non-empty source path")

    return errors
