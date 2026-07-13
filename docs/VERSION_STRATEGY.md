# 版本管理策略

## 📌 核心原则

**不使用 `latest` 标签，所有版本必须明确指定**

---

## 🏷️ 版本标签格式

### 正式版本（推荐生产使用）

```
v主版本.次版本.补丁版本
```

**示例**：
- `v0.9.11` - 正式发布版本
- `v1.0.0` - 重大版本更新
- `v0.9.12` - Bug 修复版本

**特点**：
- ✅ 与 GitHub tag 完全同步
- ✅ 经过测试的稳定版本
- ✅ 永久可用，不会改变
- ✅ 生产环境推荐使用

---

### 开发版本（仅供测试）

```
dev-YYYYMMDD-{commit_sha}
```

**示例**：
- `dev-20260713-abc1234` - 2026年7月13日构建
- `dev-20260714-def5678` - 2026年7月14日构建

**特点**：
- ✅ 每次推送到 `main` 自动构建
- ✅ 包含最新功能和修复
- ⚠️ 可能不稳定，仅供测试
- ⚠️ 不保证长期可用

---

## 🚀 自动构建规则

### 推送到 main 分支

**触发条件**：`git push origin main`

**构建结果**：
```
ghcr.io/coapis-ai/coapis-agent/server:dev-20260713-abc1234
```

**说明**：
- 自动生成基于日期和 commit SHA 的标签
- 便于追踪具体是哪个 commit 的构建
- 适合测试最新功能

---

### 打 tag（正式发布）

**触发条件**：`git tag v0.9.11 && git push --tags`

**构建结果**：
```
ghcr.io/coapis-ai/coapis-agent/server:v0.9.11
ghcr.io/coapis-ai/coapis-agent/server:v0.9
```

**说明**：
- 使用语义化版本号
- 同时生成 `v0.9.11` 和 `v0.9` 两个标签
- 与 GitHub Release 同步

---

## 📦 使用方式

### 查看可用版本

访问 GitHub Packages：
```
https://github.com/coapis-ai/coapis-agent/pkgs/container/server
```

---

### 部署指定版本

**方式1：使用环境变量**

```bash
export COAPIS_IMAGE=ghcr.io/coapis-ai/coapis-agent/server:v0.9.11
docker compose up -d
```

**方式2：使用 .env 文件**

```bash
# .env
COAPIS_IMAGE=ghcr.io/coapis-ai/coapis-agent/server:v0.9.11
```

**方式3：使用安装脚本**

```bash
# 默认版本（v0.9.11）
curl -fsSL https://get.coapis.com | bash

# 指定版本
COAPIS_VERSION=v1.0.0 curl -fsSL https://get.coapis.com | bash
```

---

## ⚠️ 注意事项

### 1. 必须指定版本

**错误示例**：
```bash
# 不设置 COAPIS_IMAGE
docker compose up -d

# 错误信息
ERROR: required variable COAPIS_IMAGE is missing a value
```

**正确做法**：
```bash
export COAPIS_IMAGE=ghcr.io/coapis-ai/coapis-agent/server:v0.9.11
docker compose up -d
```

---

### 2. 没有 latest 标签

**旧方式（已废弃）**：
```bash
# ❌ 不再支持
COAPIS_IMAGE=ghcr.io/coapis-ai/coapis-agent/server:latest
```

**新方式**：
```bash
# ✅ 使用具体版本号
COAPIS_IMAGE=ghcr.io/coapis-ai/coapis-agent/server:v0.9.11
```

---

### 3. 版本升级

**升级前**：
```bash
# 当前运行 v0.9.11
export COAPIS_IMAGE=ghcr.io/coapis-ai/coapis-agent/server:v0.9.11
```

**升级到新版本**：
```bash
# 1. 设置新版本
export COAPIS_IMAGE=ghcr.io/coapis-ai/coapis-agent/server:v0.9.12

# 2. 拉取并重启
docker compose pull
docker compose up -d
```

---

## 🔄 版本发布流程

### 开发阶段

```bash
# 1. 开发新功能
git add .
git commit -m "feat: add new feature"
git push origin main

# 2. 自动构建开发版本
# ghcr.io/coapis-ai/coapis-agent/server:dev-20260713-abc1234
```

---

### 发布阶段

```bash
# 1. 更新版本号
# CHANGELOG.md, package.json, etc.

# 2. 打 tag
git tag v0.9.12
git push origin v0.9.12

# 3. 自动构建正式版本
# ghcr.io/coapis-ai/coapis-agent/server:v0.9.12
# ghcr.io/coapis-ai/coapis-agent/server:v0.9

# 4. GitHub 自动创建 Release
```

---

## 📊 版本对应关系

| 代码分支 | GitHub Tag | Docker 镜像标签 | 用途 |
|---------|-----------|----------------|------|
| main | 无 | `dev-YYYYMMDD-{sha}` | 开发测试 |
| main | `v0.9.11` | `v0.9.11`, `v0.9` | 正式发布 |
| main | `v1.0.0` | `v1.0.0`, `v1.0`, `v1` | 重大版本 |

---

## 🎯 最佳实践

### 生产环境

```bash
# ✅ 使用稳定的正式版本
export COAPIS_IMAGE=ghcr.io/coapis-ai/coapis-agent/server:v0.9.11
```

### 测试环境

```bash
# ✅ 使用最新的开发版本
# 查看最新开发版本：https://github.com/coapis-ai/coapis-agent/pkgs/container/server
export COAPIS_IMAGE=ghcr.io/coapis-ai/coapis-agent/server:dev-20260713-abc1234
```

### 版本锁定

```bash
# ✅ 在 .env 文件中锁定版本
echo "COAPIS_IMAGE=ghcr.io/coapis-ai/coapis-agent/server:v0.9.11" >> .env
```

---

## 🔗 相关文档

- [README.md](./README.md) - 快速开始
- [QUICKSTART.md](./QUICKSTART.md) - 快速部署指南
- [DEPLOYMENT.md](./DEPLOYMENT.md) - 完整部署文档
- [GitHub Packages](https://github.com/coapis-ai/coapis-agent/pkgs/container/server) - 查看所有镜像版本
