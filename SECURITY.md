# Security Policy / 安全说明

## Supported Versions / 受支持版本

| Version | Supported          |
|---------|-------------------|
| 0.9.x   | ✅ Active         |
| 0.8.x   | ✅ Active         |
| < 0.8   | ❌ Not supported  |

## Reporting a Vulnerability / 报告安全漏洞

We take security vulnerabilities seriously. If you discover a security issue, please report it responsibly.

我们非常重视安全问题。如果您发现安全漏洞，请负责任地报告。

### How to Report / 如何报告

**Please DO NOT open a public GitHub Issue for security vulnerabilities.**

**请勿通过公开 GitHub Issue 报告安全漏洞。**

Instead, please use one of the following methods:

请使用以下方式之一报告：

1. **Email**: Send details to the project maintainers privately
2. **Private Security Advisory**: Use GitHub's Security tab to report privately

### What to Include / 报告内容

Please include the following information in your report:

- **Description**: Clear description of the vulnerability
- **Impact**: What could an attacker do with this vulnerability?
- **Reproduction Steps**: Detailed steps to reproduce the issue
- **Environment**:
  - CoApis version
  - Docker version
  - OS version
  - Any relevant configuration

### Response Timeline / 响应时间

| Stage | Timeline |
|-------|----------|
| Acknowledgment | Within 48 hours |
| Initial Assessment | Within 1 week |
| Fix Development | Within 2-4 weeks (depending on severity) |
| Public Disclosure | After fix is released |

## Security Features / 安全特性

CoApis includes several built-in security features:

### Authentication & Authorization

- **JWT-based Authentication**: Secure token-based auth with configurable expiration
- **RBAC (Role-Based Access Control)**: Fine-grained permissions by role
- **Multi-tenant Isolation**: Complete data separation between users

### Data Protection

- **Path Traversal Prevention**: Built-in checks against `..` and absolute paths
- **File Permission Controls**: Sensitive files (auth.json, users.json) restricted to 600
- **Secret Management**: Provider credentials stored in isolated `.secret/` directory

### API Security

- **Rate Limiting**: Per-user request rate limits based on user level
- **Input Validation**: Pydantic v2 validation on all API endpoints
- **CORS Protection**: Configurable cross-origin resource sharing

### Audit & Compliance

- **Audit Logging**: All operations logged in JSONL format
- **Token Usage Tracking**: Per-user token consumption monitoring
- **Shell Command Whitelist**: Role-based command execution controls

## Security Best Practices / 安全最佳实践

### Deployment

1. **Use strong JWT secrets**: Generate a random 256-bit key for `JWT_SECRET`
2. **Restrict port exposure**: Only expose necessary ports (4103, 4200)
3. **Enable HTTPS**: Use a reverse proxy (Nginx) with TLS certificates
4. **Regular backups**: Backup `system/` and `workspaces/` directories regularly

### Configuration

1. **Enable authentication**: Set `COAPIS_AUTH_ENABLED=True`
2. **Set token quotas**: Configure per-user token limits to prevent abuse
3. **Use rate limiting**: Enable request rate limits based on user levels
4. **Restrict shell access**: Configure `shell_permissions` in `permissions.json`

### Monitoring

1. **Check audit logs**: Review `logs/audit.log` regularly
2. **Monitor token usage**: Track consumption via `/api/users/me`
3. **Watch for anomalies**: Alert on unusual request patterns

## Known Limitations / 已知限制

- Local deployment only — no built-in multi-node clustering
- SQLite backend — suitable for small to medium deployments
- No built-in encryption at rest (use disk-level encryption if needed)

## References / 参考

- [OWASP Top 10](https://owasp.org/www-project-top-ten/)
- [FastAPI Security](https://fastapi.tiangolo.com/tutorial/security/)
- [Docker Security Best Practices](https://docs.docker.com/build/building/best-practices/)

---

**Last updated**: 2026-05-27
