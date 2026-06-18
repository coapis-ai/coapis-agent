# -*- coding: utf-8 -*-
"""CoApis Enterprise Package

This package provides enterprise-grade features for CoApis:
- Monitoring: Advanced system monitoring with Prometheus integration
- SSO: SAML 2.0 and OIDC integration
- Skill Market: Enterprise skill marketplace with curation and review
- Clustering: Multi-node clustering and load balancing
- Audit: Comprehensive audit logging and compliance reporting

License:
    Commercial - see LICENSE file for terms

Usage:
    pip install coapis-enterprise
    # The package auto-registers with the CoApis server at startup
"""

from .plugin import EnterprisePluginImpl

__version__ = "1.0.0"
__all__ = ["EnterprisePluginImpl"]
