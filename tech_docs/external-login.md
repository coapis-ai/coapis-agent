# 外部系统自动登录

> 通过简单的签名验证，实现外部系统用户自动登录到 CoApis，无需预先注册账号。

## 功能说明

- **自动创建用户**：首次登录时自动创建账号和个人空间
- **签名验证**：使用 HMAC-SHA256 确保请求来源可信
- **多种接入方式**：支持 API 调用和浏览器跳转

---

## 环境配置

```bash
# .env 或 docker-compose.yml
COAPIS_SSO_SECRET=your-secret-key-min-32-characters
```

⚠️ **生产环境必须设置**，开发环境有默认值。

---

## 签名算法

```python
import hmac
import hashlib

SSO_SECRET = "your-secret-key"
USERNAME = "zhangsan"

# 签名 = HMAC-SHA256(SECRET, username)
signature = hmac.new(
    SSO_SECRET.encode(),
    USERNAME.encode(),
    hashlib.sha256
).hexdigest()
```

---

## 接入方式

### 方式一：API 调用（推荐）

外部系统后端调用 CoApis API，获取 token 后传递给前端。

**请求**

```http
POST /api/external/login
Content-Type: application/json

{
  "token": "签名",
  "username": "用户名",
  "display_name": "显示名称（可选）"
}
```

**响应**

```json
{
  "token": "CoApis token",
  "username": "zhangsan",
  "display_name": "张三",
  "is_new_user": true
}
```

**完整示例**

```python
import hmac
import hashlib
import requests

# 配置
SSO_SECRET = "your-secret-key"
COAPIS_URL = "http://coapis-server:4208"
USERNAME = "zhangsan"

# 1. 生成签名
token = hmac.new(
    SSO_SECRET.encode(),
    USERNAME.encode(),
    hashlib.sha256
).hexdigest()

# 2. 调用 API
response = requests.post(
    f"{COAPIS_URL}/api/external/login",
    json={
        "token": token,
        "username": USERNAME,
        "display_name": "张三",
    }
)

# 3. 获取 CoApis token
if response.status_code == 200:
    data = response.json()
    coapis_token = data["token"]
    # 将 token 传递给前端，或设置到 cookie
else:
    print(f"登录失败: {response.json()}")
```

---

### 方式二：浏览器跳转

外部系统生成 URL，用户浏览器直接跳转。

**URL 格式**

```
{COAPIS_URL}/api/external/login?token={签名}&username={用户名}&display_name={显示名}&redirect={跳转路径}
```

**参数说明**

| 参数 | 必填 | 说明 |
|------|------|------|
| token | 是 | HMAC-SHA256 签名 |
| username | 是 | 用户名 |
| display_name | 否 | 显示名称 |
| redirect | 否 | 登录后跳转路径，默认 `/` |

**示例**

```python
import hmac
import hashlib

SSO_SECRET = "your-secret-key"
USERNAME = "lisi"

# 生成签名
token = hmac.new(
    SSO_SECRET.encode(),
    USERNAME.encode(),
    hashlib.sha256
).hexdigest()

# 生成跳转 URL
url = f"https://coapis.example.com/api/external/login?token={token}&username={USERNAME}&display_name=李四&redirect=/"

# 返回给前端，让浏览器跳转
print(url)
```

**用户访问后**

1. 自动验证签名
2. 自动创建用户（如果不存在）
3. 自动设置登录状态（存储到 localStorage）
4. 跳转到指定页面

---

## 流程图

```
┌─────────────────┐
│  外部系统登录    │
│  (ERP/OA/...)   │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  生成签名        │
│  HMAC(SECRET,   │
│       username) │
└────────┬────────┘
         │
         ▼
┌─────────────────┐     ┌─────────────────┐
│  调用 API        │ 或  │  浏览器跳转      │
│  POST /external │     │  GET /external  │
│  /login         │     │  /login?token=  │
└────────┬────────┘     └────────┬────────┘
         │                       │
         └───────────┬───────────┘
                     │
                     ▼
         ┌─────────────────────┐
         │  CoApis 验证签名     │
         └──────────┬──────────┘
                    │
          ┌─────────┴─────────┐
          │                   │
          ▼                   ▼
    ┌───────────┐       ┌───────────┐
    │ 新用户     │       │ 已有用户   │
    │ 自动创建   │       │ 返回token  │
    └─────┬─────┘       └─────┬─────┘
          │                   │
          └─────────┬─────────┘
                    │
                    ▼
         ┌─────────────────────┐
         │  返回 CoApis token   │
         │  + 用户信息          │
         └─────────────────────┘
```

---

## 安全建议

1. **密钥管理**
   - 生产环境使用强密钥（≥32 字符）
   - 定期更换密钥
   - 不同环境使用不同密钥

2. **HTTPS**
   - 生产环境必须使用 HTTPS
   - 防止签名被中间人窃取

3. **Token 有效期**
   - 默认 7 天
   - 可通过代码调整 `expiry_seconds` 参数

4. **用户名规范**
   - 建议使用外部系统的用户 ID
   - 避免使用特殊字符

---

## 错误码

| 状态码 | 说明 |
|--------|------|
| 200 | 成功 |
| 401 | 签名无效 |
| 500 | 创建用户失败 |

---

## 常见问题

### Q: 用户已存在时会怎样？

A: 直接返回 token，不会重复创建用户。`is_new_user` 字段会返回 `false`。

### Q: 如何同步用户信息？

A: 目前只支持首次创建时同步 `display_name`。如需同步更多信息，可以扩展 API 参数。

### Q: 能否限制用户权限？

A: 可以在创建用户时指定 `role` 参数（需要扩展 API）。

### Q: 如何登出？

A: 调用 `/api/auth/logout` 或在前端清除 `localStorage` 中的 token。
