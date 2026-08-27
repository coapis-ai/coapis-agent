# CoApis 社区版：外部系统身份集成与 OpenID/员工号绑定技术/产品手册 v6.0

## 一、 概述与设计理念

本手册旨在为 **CoApis 社区版** 提供完整的外部系统集成与身份认证指导。基于企业实际落地场景的反馈，我们摒弃了复杂隐式上下文传递或繁琐的 OAuth2 授权码流转，采用最务实且用户体验友好的方案：**“本地账号绑定外部 OpenID/员工号 + 映射验证”**。

### 核心设计理念
1. **用户侧体验优化**：在 Co/apis 登录界面直接提供"XX系统登录”入口（如 OA系统、企业微信等），实现一键免密跳转与自动登录。
2. **管理侧操作简化**：支持管理员通过批量导入（CSV/Excel模板）或脚本方式，直接将“本地账号”与“外部系统的 OpenID/员工号”的映射关系写入社区版的本地 JSON 配置文件。
3. **安全验证机制**：采用“共享密钥 + 时间戳 + HMAC-SHA256签名”的轻量级校验方案，确保身份传递的安全性并防止重放攻击。

---

## 二、 产品体验设计（用户侧与管理侧）

### 1. 用户侧：登录界面外部系统入口
在 Co/apis 社区版的标准账号密码登录页面上，增加外部系统登录区域：
*   **主登录区**：本地账号 / 密码 + 验证码（或一键登录）。
*   **辅助登录区（第三方/外部系统入口）**：
    *   提供按钮或图标链接，如：“🏢 OA系统登录”、“💼 企业微信登录”、“📱 钉钉扫码登录”。
    *   或者提供一个下拉菜单/弹窗：“选择您的身份来源”，让用户明确选择是通过哪个外部系统进入。

**交互与技术流转流程：**
当用户点击“OA系统登录”或类似按钮时：
1. **前端触发跳转/请求**：Co/apis 前端引导用户通过外部系统的授权链接，或直接携带 `provider`、`external_id` (openid/员工号)、`timestamp` 和 `signature` 跳转到 Co/apis 的 `/api/auth/external/login` 接口。
2. **后端验证与登录**：Co/apis 后端验签通过并查询本地映射文件（`data/external_identity_mappings.json`），若匹配成功则直接生成本地 Token，用户瞬间完成免密登录。

### 2. 管理侧：管理员批量导入映射关系
对于企业或团队来说，最方便的初始配置方式就是**“一次性批量导入”**。管理员在后台将“本地账号”与“外部系统的 OpenID/员工号”的对应关系直接写入映射文件。

*   **支持格式**：提供 Excel (.xlsx) 或 CSV 模板下载。
*   **模板字段**：`本地账号ID (user_id)` | `外部系统标识 (provider)` | `外部OpenID/员工号 (external_id)` | `状态 (status: 1绑定, 0解绑)`

当管理员上传并确认映射数据后，后端或脚本会执行以下操作：
1. **解析 CSV/Excel**：验证数据的完整性和格式。
2. **合并到现有映射**：读取 `data/external_identity_mappings.json` 中的 `bindings` 数组。
3. **去重与更新**：将新导入的映射记录追加或覆盖到 JSON 文件中（确保 `provider + external_id` 的唯一性）。
4. **原子写回**：使用“临时文件替换”机制，安全地保存为新的 `external_identity_mappings.json`。

---

## 三、 核心安全与签名技术机制

所有涉及外部系统向 Co/apis 传递身份上下文或触发 SSO 回调的请求，都必须经过严格的验签与防重放校验。

### 1. 共享密钥 (Shared Secret)
Co/apis 后端通过环境变量 `EXTERNAL_SSO_SECRET` 配置共享密钥。外部系统在生成签名时，需使用相同的密钥字符串。

### 2. 签名字符串生成规则
请求参数必须包含 `provider`、`external_id` 和 `timestamp`。签名字符串的拼接格式如下：
```text
sign_string = "provider={provider}&external_id={external_id}&timestamp={timestamp}"
```

### 3. 签名算法 (HMAC-SHA256)
使用 HMAC-SHA256 算法对 `sign_string` 和 `EXTERNAL_SSO_SECRET` 进行加密，生成十六进制的 `signature`：
```python
import hmac
import hashlib
import os

sign_string = "provider=oa&external_id=emp_oa_98765&timestamp=1692740400"
shared_secret = os.getenv("EXTERNAL_SSO_SECRET", "default_secret_key_community")

signature = hmac.new(
    shared_secret.encode('utf-8'),
    sign_string.encode('utf-8'),
    hashlib.sha256
).hexdigest()
```

### 4. 防重放机制 (Anti-Replay)
Co/apis 后端会校验请求中的 `timestamp`（Unix 时间戳，秒级）与当前服务器时间的差值。**有效期为 5 分钟（300 秒）**。超出该时间范围的请求将被拒绝。

---

## 四、 API 接口文档

### 1. 外部系统免密登录/身份验证回调 (SSO Entry)
**功能：** 接收来自外部系统的身份凭证，验证签名和时效后，查询本地 JSON 映射文件并返回 Co/apis 本地 Token。

*   **接口路径：** `POST /api/auth/external/login`
*   **Content-Type:** `application/json`

#### 请求参数 (JSON Body)
| 字段名 | 类型 | 必填 | 说明 |
| :--- | :--- | :--- | :--- |
| `provider` | String | 是 | 外部系统标识（如：`oa`, `wecom`, `custom_system`） |
| `external_id` | String | 是 | 外部系统的 openid / unionid / 员工号 |
| `timestamp` | Integer | 是 | Unix 时间戳（秒级），用于防重放校验 |
| `signature` | String | 是 | HMAC-SHA256 签名串 |

#### 成功响应 (HTTP 200)
```json
{
  "success": true,
  "token": "mock_jwt_token_for_usr_local_12345",
  "user_id": "usr_local_12345",
  "message": "External identity login successful"
}
```

#### 错误响应
| HTTP 状态码 | 错误详情 (detail) | 说明 |
| :--- | :--- | :--- |
| `400` | `Invalid JSON payload` / `Missing required parameters...` | 请求参数格式错误或缺失必填项 |
| `401` | `Request expired or timestamp invalid` | 时间戳超出 5 分钟有效期，防重放校验失败 |
| `403` | `Invalid signature` | 签名验证失败，请求可能来自不可信源或被篡改 |
| `403` | `BINDING_REQUIRED` | 外部标识未与 Co/apis 本地账号建立绑定关系，需引导用户手动绑定或管理员导入 |

### 2. 本地手动绑定/解绑接口 (User Management)
*   **绑定接口**：`POST /api/auth/users/identity/bind`
*   **解绑接口**：`POST /api/auth/users/identity/unbind`
（具体参数与响应格式参见技术对接部分，需携带有效 Co/apis 登录态 Token）

---

## 五、 数据存储结构说明

社区版将所有身份映射关系持久化保存在本地 JSON 配置文件中，默认路径为：`data/external_identity_mappings.json`。

**文件数据结构示例：**
```json
{
  "bindings": [
    {
      "user_id": "usr_local_12345",
      "provider": "oa",
      "external_id": "emp_oa_98765",
      "status": 1,
      "created_at": "2026-08-22T10:00:00Z"
    },
    {
      "user_id": "usr_local_67890",
      "provider": "wecom",
      "external_id": "wecom_userid_xyz",
      "status": 1,
      "created_at": "2026-08-21T15:30:00Z"
    }
  ]
}
```

---

## 六、 C2A与MCP集成上下文说明

一旦用户通过外部系统的 `openid/员工号` 成功完成映射并登录（获得本地 Token），后续所有的操作均基于**本地账号 ID (`user_id)`**：
1. **统一上下文**：后续的 C2A 卡片渲染、MCP 工具调用，Co/apis 后端仅依赖该用户的本地 `user_id` 和已验证的 JWT Token/Session 进行校验。
2. **C2A Payload 简化**：`context_data` 中只需包含本地用户角色与权限列表（如 `["approve_read", "data_export"]`），无需携带外部系统的 `openid`，保持 C2A 协议的纯粹性与轻量化。
