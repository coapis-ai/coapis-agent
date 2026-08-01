# CoApis 企业版部署文档

## 部署步骤

### 1. 构建Docker镜像

企业版代码需要打包到Docker镜像中。

#### 方法1：复制到容器内（测试用）

```bash
# 复制企业版代码到容器
docker cp /apps/ai/tool-dev/dev-coapis/coapis-agent/coapis/enterprise \
  coapis-ent-server-dev:/tmp/coapis_enterprise/

# 创建.pth文件使Python能找到
docker exec coapis-ent-server-dev bash -c \
  "echo '/tmp' > /usr/local/lib/python3.11/site-packages/coapis-enterprise.pth"

# 重启容器
docker restart coapis-ent-server-dev
```

#### 方法2：构建新镜像（推荐）

创建 Dockerfile：

```dockerfile
FROM coapis-server:latest

# 安装asyncpg依赖
RUN pip install asyncpg

# 复制企业版代码
COPY coapis/enterprise /tmp/coapis_enterprise/

# 创建.pth文件
RUN echo "/tmp" > /usr/local/lib/python3.11/site-packages/coapis-enterprise.pth

# 复制数据库初始化脚本
COPY docker/init/postgres/03_missing_p0_p2_tables.sql /docker-entrypoint-initdb.d/
```

构建命令：
```bash
docker build -t coapis-enterprise-server:latest .
```

### 2. 数据库配置

企业版需要数据库连接池。在应用启动时初始化：

```python
# 在 _app.py 的 lifespan 中添加
from coapis_enterprise.database import DatabasePool

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await DatabasePool.initialize(
        host="172.16.6.241",
        port=4112,
        user="coapis",
        password="dev_password",
        database="coapis_enterprise_dev"
    )
    
    yield
    
    # Shutdown
    await DatabasePool.close()
```

### 3. 认证中间件

企业版API需要认证，确保请求头包含：

```
Authorization: Bearer {token}
```

认证流程：
1. 登录获取token：POST /api/auth/login
2. 使用token访问企业版API

### 4. 多租户配置

每个用户需要关联到租户：
- 用户表有 tenant_id 字段
- 请求头中的token包含 tenant_id 信息

### 5. 权限控制

企业版API支持两种权限模式：
- 普通用户：只能访问自己的数据
- 管理员：可以访问租户内所有数据

### 6. 测试验证

```bash
# 运行测试脚本
python /apps/ai/projects/test_chat_api.py
```

## 目录结构

```
coapis/enterprise/
├── __init__.py          # 导出get_routers, register_plugin
├── plugin.py            # 插件实现
├── database.py          # 数据库连接池
└── api/
    ├── __init__.py
    └── chat.py          # 聊天API（会话+消息）
```

## API端点

### 会话管理

- `GET /api/chat/sessions` - 列出会话
- `POST /api/chat/sessions` - 创建会话
- `GET /api/chat/sessions/{session_id}` - 获取会话详情
- `PATCH /api/chat/sessions/{session_id}` - 更新会话
- `DELETE /api/chat/sessions/{session_id}` - 删除会话

### 消息管理

- `GET /api/chat/sessions/{session_id}/messages` - 获取消息列表
- `POST /api/chat/sessions/{session_id}/messages` - 创建消息

### 搜索

- `GET /api/chat/search` - 全文搜索消息

## 注意事项

1. **包名**: 必须使用 `coapis_enterprise`（下划线），因为社区版硬编码了这个导入路径
2. **路径**: 通过 .pth 文件将 `/tmp` 添加到 Python 路径
3. **兼容性**: API完全兼容社区版的 ChatSpec 和 Message 模型
4. **隔离性**: 多租户隔离通过 tenant_id 实现
5. **审计**: 所有操作记录到 audit_logs 表
