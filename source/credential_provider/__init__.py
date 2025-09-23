# ABOUTME: Cognito OIDC Authentication package for enterprise identity federation
# ABOUTME: Provides secure credential exchange between OIDC providers and AWS services

"""AWS credential provider for OIDC + Cognito Identity Pool."""

from .__main__ import main, MultiProviderAuth, __version__

__all__ = ["main", "MultiProviderAuth", "__version__"]