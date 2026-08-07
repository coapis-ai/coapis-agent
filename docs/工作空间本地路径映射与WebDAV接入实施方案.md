# 工作空间本地路径映射与 WebDAV 接入实施方案

## 一、 背景与痛点分析

在 AI 智能体平台的使用场景中，**"我的空间"（Workspace）**本质上是云端的文件管理系统。大多数用户习惯使用本地电脑进行开发和工作，依赖本地的文件夹路径管理代码、文档或数据。当前系统虽然提供了"我的空间"，但用户只能通过 Web 页面的"上传/下载"按钮来管理本地文件夹中的内容，这导致：

1. **操作摩擦大**：频繁上传下载效率低下，无法实时同步本地修改。
2. **开发体验割裂**：开发者需要离开熟悉的 IDE（如 VS Code、Cursor）才能编辑云端文件。
3. **普通用户门槛高**：非技术用户对"上传/下载"流程感到繁琐，缺乏本地文件管理器的直观体验。

## 二、 解决方案概述

为了解决上述痛点，我们提供**WebDAV 网络驱动器映射**方案，将"我的空间"映射为用户本地电脑的网络驱动器（如 Z: 盘），实现原生文件管理器的无缝操作。

> **说明**：原计划的 SSH/SFTP 接入方案因涉及权限越界风险（可能引发主机系统文件的非授权访问）已取消。当前仅支持通过 WebDAV 协议进行安全、受控的本地路径映射。

## 三、 WebDAV 网络驱动器映射实施指南

### 3.1 FastAPI WebDAV 路由配置

在 FastAPI 中新增 `/api/webdav/{username}/...` 路由端点，处理 PUT/DELETE/MKCOL/COPY/MOVE 请求：

1. 创建 `server/coapis/app/routers/webdav.py` 文件
2. 使用自定义 WebDAV handler 或集成 WebDAV 库处理请求
3. 验证用户 token 并映射到对应的 `workspaces/{username}/files/` 目录

### 3.2 Nginx WebDAV 配置

在 Nginx 配置中启用 WebDAV 模块，为每个用户的工作空间提供 WebDAV 访问路径。以下是 Nginx 配置文件示例（适用于 `docker/_common/nginx/conf/default.conf.template`）：

```nginx
# WebDAV 配置块
location ^~ /webdav/ {
    # 启用 dav 方法
    dav_methods PUT DELETE MKCOL COPY MOVE;
    dav_ext_methods PROPFIND OPTIONS;
    
    # 创建文件权限
    create_file_mode 0644;
    create_dir_mode 0755;
    
    # 限制只允许 authenticated users
    auth_basic "WebDAV Authentication";
    auth_basic_user_file /etc/nginx/.htpasswd_webdav;
}
```

### 3.3 前端 UI 增强（"我的空间"页面）✅ 已完成

在"我的空间"页面中增加 **"WebDAV 网络驱动器映射"** 按钮，点击后弹出模态框展示 WebDAV URL 及 Windows/Mac 的映射步骤。已添加以下功能：
- WebDAV URL 显示（格式：`{window.location.origin}/webdav/{username}`）
- Windows 映射步骤说明
- macOS 映射步骤说明

## 四、 安全与隔离保障

- **权限控制**：通过 WebDAV 的账号密码/Token 认证，确保用户只能访问自己的 `workspaces/{username}/files/` 目录。
- **防越权**：普通用户无法访问其他用户的 workspace 或系统核心文件。WebDAV 路径严格限制在用户专属的文件空间内。
- **能力对等**：用户在本地编辑的文件（如 Skill JSON、Python 脚本）保存后，云端智能体可立即感知并调用，与 admin 在自己空间内的操作完全一致。

## 五、 实施步骤总结

1. ✅ **前端 UI 改造已完成**：在"我的空间"页面增加 WebDAV 映射按钮及模态框，并添加对应的 i18n 翻译（zh.json / en.json）。
2. ✅ **后端与 Nginx WebDAV 配置已实施**：添加了 FastAPI WebDAV 路由和 Nginx webdav location 块支持。
3. ✅ **文档与引导已生成**：在 `docs/工作空间本地路径映射与WebDAV接入实施方案.md` 中提供完整方案说明。
