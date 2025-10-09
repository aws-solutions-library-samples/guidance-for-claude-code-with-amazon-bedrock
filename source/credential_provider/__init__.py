# ABOUTME: Cognito OIDC Authentication package for enterprise identity federation
# ABOUTME: Provides secure credential exchange between OIDC providers and AWS services

"""AWS credential provider for OIDC + Cognito Identity Pool."""

from .__main__ import MultiProviderAuth, __version__, main

__all__ = ["main", "MultiProviderAuth", "__version__"]
