# ABOUTME: Shared persona-resolution algorithm (spec §4.3) for the ccwb CLI and tooling.
# ABOUTME: Pure, dependency-free; mirrored in Go (internal/persona) and the quota Lambdas.

"""Persona resolution.

A *persona* is a named group tier declared in ``config.yaml`` (and serialized into
``config.json``). At credential-issuance and telemetry time the user's OIDC ``groups``
claim is matched against the declared personas to pick exactly one.

This is the **parity contract** described in ``spec.md#4.3``: the Go credential-process,
the Go otel-helper, and both quota Lambdas implement the identical algorithm. Any change
here must be mirrored in those implementations and covered by the shared fixtures in
``tests/fixtures/persona_resolution_cases.json``.

Algorithm::

    resolve_persona(user_groups, personas_ordered, fallback):
        for p in personas_ordered:          # DECLARED ORDER == precedence
            if p["group"] in user_groups:
                return p
        if fallback:                         # name of a declared persona, or None
            return personas_ordered.by_name(fallback)   # None if the name is unknown
        return None                          # None => hard-deny (helper) / no group tier (lambda)
"""

from collections.abc import Iterable
from typing import Any


def resolve_persona(
    user_groups: Iterable[str],
    personas_ordered: list[dict[str, Any]],
    fallback: str | None,
) -> dict[str, Any] | None:
    """Resolve the single persona that applies to a user.

    Declared order is precedence: the first persona whose ``group`` appears in the
    user's groups wins. When no persona matches, the named ``fallback`` persona is
    returned if it exists; otherwise ``None``.

    Args:
        user_groups: The values of the user's OIDC groups claim. May be any iterable
            (list or set); membership is tested by exact string equality.
        personas_ordered: Personas in declared order (precedence). Each is a dict that
            must carry ``name`` and ``group`` keys; extra keys are ignored.
        fallback: Name of a declared persona to fall back to when no group matches, or
            ``None`` to hard-deny on no match.

    Returns:
        The matching persona dict (the same object from ``personas_ordered``), or
        ``None`` when there is no match and no usable fallback.
    """
    # Normalize to a set once for O(1) membership across the declared list.
    groups = set(user_groups)

    for persona in personas_ordered:
        if persona.get("group") in groups:
            return persona

    if fallback:
        for persona in personas_ordered:
            if persona.get("name") == fallback:
                return persona

    return None
