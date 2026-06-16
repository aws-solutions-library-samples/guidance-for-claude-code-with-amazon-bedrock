# ABOUTME: Validation for persona definitions declared in config.yaml / Profile.personas.
# ABOUTME: Pure, returns a list of human-readable errors; empty list means valid.

"""Persona definition validation.

``validate_personas`` checks a list of persona dicts (the canonical shape in
``spec.md#4.1``) plus the top-level ``fallback_persona`` and returns a list of
human-readable error strings. An empty list means the personas are valid.

The wizard (``init.py``) and the deploy path call this before persisting or
materializing personas so that misconfigurations surface early with a clear message
rather than as an opaque CloudFormation or STS failure later.
"""

import re
from typing import Any

VALID_ENFORCEMENT_MODES = ("alert", "block")

# A persona name must be DNS/IAM-safe (spec §4.1): it is interpolated into IAM
# role/policy names and sanitized into CloudFormation logical ids. Restrict it to
# an alphanumeric-and-hyphen identifier (letter/digit start) so the rendered stack
# can never carry an invalid logical id or an illegal IAM resource name. This is
# the same convention as Config._is_valid_profile_name.
VALID_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]*$")


def validate_personas(personas: list[dict[str, Any]], fallback: str | None) -> list[str]:
    """Validate a list of persona definitions.

    Args:
        personas: Persona dicts in declared order. Each should carry at least ``name``
            and ``group``; optional keys include ``allowed_models``, ``denied_models``,
            ``enforcement_mode``, etc. (see ``spec.md#4.1``).
        fallback: The configured ``fallback_persona`` name, or ``None``.

    Returns:
        A list of human-readable error messages. Empty means valid. Checks:
          * duplicate persona names
          * distinct names that sanitize to the SAME CloudFormation logical id
            (e.g. ``eng-team`` and ``eng_team`` -> ``EngTeam``) — these would
            silently collide and overwrite resources in the rendered stack
          * missing or empty ``name`` or ``group``
          * ``name`` not DNS/IAM-safe (must match ``^[A-Za-z0-9][A-Za-z0-9-]*$``)
          * ``enforcement_mode`` not in {"alert", "block"} (when present)
          * ``allowed_models`` / ``denied_models`` entries that are not strings
          * ``fallback`` naming a persona that does not exist
    """
    # Imported here (not at module top) to keep this module import-light and to make
    # the dependency direction explicit: validation reuses the renderer's sanitizer so
    # the collision check uses the SAME logical-id mapping the stack will actually emit
    # (single source of truth). persona_template imports only stdlib + yaml, so there
    # is no import cycle.
    from claude_code_with_bedrock.persona_template import _logical_id

    errors: list[str] = []
    seen_names: set[str] = set()
    # Map each sanitized logical-id stem -> the first valid name that produced it, so a
    # later distinct name colliding on the same stem can be reported with both names.
    logical_id_owner: dict[str, str] = {}

    for index, persona in enumerate(personas):
        if not isinstance(persona, dict):
            errors.append(f"Persona at index {index} must be a mapping, got {type(persona).__name__}.")
            continue

        # A stable label for messages even when name is missing.
        raw_name = persona.get("name")
        label = raw_name if isinstance(raw_name, str) and raw_name else f"index {index}"

        # name: present, non-empty, and DNS/IAM-safe
        if not isinstance(raw_name, str) or not raw_name.strip():
            errors.append(f"Persona at {label} is missing a non-empty 'name'.")
        else:
            if raw_name in seen_names:
                errors.append(f"Duplicate persona name '{raw_name}'.")
            seen_names.add(raw_name)
            if not VALID_NAME_RE.match(raw_name):
                errors.append(
                    f"Persona name '{raw_name}' is not DNS/IAM-safe; use only letters, digits, "
                    "and hyphens, starting with a letter or digit (e.g. 'data-science')."
                )
            else:
                # Two DNS/IAM-safe but distinct names can still sanitize to the same
                # CloudFormation logical-id stem (e.g. a hyphen vs underscore variant, or
                # ASCII/non-ASCII), which would silently overwrite one persona's resources
                # in the rendered stack. Catch it here, upfront, alongside the other config
                # errors — the renderer also raises on collision, but as a late ValueError.
                stem = _logical_id(raw_name)
                if stem in logical_id_owner and logical_id_owner[stem] != raw_name:
                    errors.append(
                        f"Persona names '{logical_id_owner[stem]}' and '{raw_name}' both map to the "
                        f"same CloudFormation logical id '{stem}' and would collide; rename one so "
                        "their sanitized identifiers differ."
                    )
                else:
                    logical_id_owner.setdefault(stem, raw_name)

        # group: present and non-empty
        group = persona.get("group")
        if not isinstance(group, str) or not group.strip():
            errors.append(f"Persona '{label}' is missing a non-empty 'group'.")

        # enforcement_mode: when present, must be a known mode
        mode = persona.get("enforcement_mode")
        if mode is not None and mode not in VALID_ENFORCEMENT_MODES:
            errors.append(
                f"Persona '{label}' has invalid enforcement_mode '{mode}'; "
                f"expected one of {', '.join(VALID_ENFORCEMENT_MODES)}."
            )

        # model globs: every entry must be a string
        for field_name in ("allowed_models", "denied_models"):
            globs = persona.get(field_name)
            if globs is None:
                continue
            if not isinstance(globs, list):
                errors.append(f"Persona '{label}' field '{field_name}' must be a list of strings.")
                continue
            for entry in globs:
                if not isinstance(entry, str):
                    errors.append(
                        f"Persona '{label}' field '{field_name}' contains a non-string entry: {entry!r}."
                    )

    # fallback must name a persona that exists
    if fallback is not None and fallback not in seen_names:
        errors.append(f"fallback_persona '{fallback}' does not name any declared persona.")

    return errors
