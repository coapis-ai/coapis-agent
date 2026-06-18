# CoApis Enterprise

Enterprise-grade features for CoApis, including:

- **Monitoring**: Advanced system monitoring with Prometheus integration
- **SSO**: SAML 2.0 and OIDC integration with multi-tenant support
- **Skill Market**: Enterprise skill marketplace with curation and review
- **Clustering**: Multi-node clustering and load balancing
- **Audit**: Comprehensive audit logging and compliance reporting

## Installation

```bash
pip install coapis-enterprise
```

## License

This package is distributed under a commercial license. See [LICENSE](LICENSE) for details.

To purchase a license, contact: sales@coapis.dev

## Features by Tier

| Feature | Starter | Professional | Enterprise |
|---------|---------|--------------|------------|
| Monitoring | ✅ | ✅ | ✅ |
| SSO (OIDC) | ✅ | ✅ | ✅ |
| SSO (SAML) | ❌ | ✅ | ✅ |
| Audit Logging | ❌ | ✅ | ✅ |
| Skill Market | ❌ | ✅ | ✅ |
| Clustering | ❌ | ❌ | ✅ |

## Quick Start

1. Install the package:
   ```bash
   pip install coapis-enterprise
   ```

2. Activate your license:
   ```bash
   coapis-enterprise activate --key YOUR-LICENSE-KEY
   ```

3. Restart CoApis server:
   ```bash
   docker restart coapis-server
   ```

4. Enterprise features will be automatically enabled.

## Documentation

For more information, see the [Enterprise Documentation](https://docs.coapis.dev/enterprise).
