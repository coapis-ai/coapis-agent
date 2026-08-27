# CoApis 社区版：外部系统身份集成实施方案 v6.0

## 一、 实施目标
实现 Co/apis 社区版与外部系统（OA、企业微信、钉钉等）的身份集成，通过**“登录界面提供‘XX系统登录’入口”**和**“管理员批量导入映射关系”**的方式，完成本地账号与外部 OpenID/员工号的绑定与免密登录。

---

## 二、 实施阶段与步骤

### Phase 1: 基础设施与环境配置 (Infrastructure Setup)
1. **环境变量配置**：
   - 在 Co/apis 社区版启动环境中设置 `EXTERNAL_SSO_SECRET` 变量，用于签名验证。例如：
     ```bash
     export EXTERNAL_SSO_SECRET="your_secure_shared_secret_key"
     ```
2. **数据存储文件初始化**：
   - 确保项目目录中存在 `data/external_identity_mappings.json` 文件，初始结构为：
     ```json
     {
       "bindings": []
     }
     ```

### Phase 2: 后端 API 开发与集成 (Backend API Development)
1. **路由模块创建**：
   - 已创建 `/apps/ai/tool-dev/dev-coapis/coapis-agent/server/coapis/app/routers/external_auth.py`，包含以下端点：
     - `POST /api/auth/external/login`：外部系统 SSO 回调验证接口。
     - `POST /api/auth/users/identity/bind`：本地手动绑定外部标识接口。
     - `POST /api/auth/users/identity/unbind`：本地手动解绑外部标识接口。
2. **主应用路由注册**：
   - 在 FastAPI 主应用文件（如 `main.py` 或 `app.py`）中引入并注册 `external_auth_router`：
     ```python
     from coapis.app.routers.external_auth import router as external_auth_router
     app.include_router(external_auth_router)
     ```

### Phase 3: 前端 UI 与产品体验集成 (Frontend UI Integration)
1. **登录页面改造**：
   - 在 Co/apis 社区版登录页（Login Page）增加外部系统登录入口区域。
   - 提供按钮或图标链接，如：“🏢 OA系统登录”、“💼 企业微信登录”。
2. **管理端批量导入工具开发**：
   - 在后台管理界面增加“外部系统身份映射管理”模块。
   - 支持 CSV/Excel 模板下载与上传解析。
   - 后端提供接口或脚本逻辑，将导入数据合并到 `data/external_identity_mappings.json` 中，并使用原子写回机制确保并发安全。

### Phase 4: 测试与验证 (Testing & Validation)
1. **签名验证测试**：
   - 使用外部系统模拟请求 `/api/auth/external/login`，验证实时时间戳校验与 HMAC-SHA256 签名验证逻辑。
2. **JSON 文件并发写入测试**：
   - 模拟多用户同时绑定/解绑操作，验证 `data/external_identity_mappings.json` 的原子写回机制是否有效防止数据损坏或覆盖。
3. **前端入口联调**：
   - 验证登录页“XX系统登录”按钮跳转及 SSO 回调流程的完整性。

---

## 三、 关键注意事项

1. **共享密钥一致性**：确保 Co/apis 社区版启动时已正确加载 `EXTERNAL_SSO_SECRET` 环境变量，且与外部系统生成签名所使用的密钥完全一致。
2. **并发文件写入安全**：Co/apis 后端在实现绑定/解绑接口时，已采用“读取 -> 内存修改 -> 原子写回（临时文件替换）”的策略，确保 JSON 映射文件在多请求并发下的数据完整性。
3. **C2A与MCP上下文统一**：一旦用户通过外部 `openid/员工号` 成功完成映射并登录（获得本地 Token），后续所有的 C2A 卡片渲染、MCP 工具调用，Co/apis 后端均基于该用户的**本地账号 ID (`user_id)`** 进行权限校验，不再强制要求携带外部的 `openid`。
