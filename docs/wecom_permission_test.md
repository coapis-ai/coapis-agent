# WeCom 权限修复测试方案

## 修复内容
WeCom 渠道现在会通过 `workspace owner → user_store` 获取用户角色，不再 fallback 到 visitor。

## 测试前置条件
- 容器已重启，代码已生效
- WeCom 渠道已配置并连接
- 你的企业微信账号在系统中注册为 admin 角色

## 测试步骤

### 1. 基础对话测试（验证 WeCom 渠道正常工作）
在企业微信中发送：
```
你好，请介绍一下你自己
```
**预期**：正常回复，无报错

### 2. 需要高级权限的工具测试（验证 admin 权限生效）
在企业微信中发送：
```
执行命令 cat /etc/hostname
```
**预期**：admin 用户应能执行，返回服务器主机名

### 3. 文件系统操作测试
在企业微信中发送：
```
列出当前目录的文件
```
**预期**：admin 用户应能执行，返回文件列表

### 4. 对比验证（Console 渠道权限一致性）
在 Console 网页中执行相同命令，确认两个渠道返回的权限等级一致。

### 5. 查看日志确认角色解析
在服务器上查看容器日志，确认角色被正确解析：
```bash
docker logs coapis-server 2>&1 | grep "resolved role from workspace owner"
```
**预期**：应看到类似日志：
```
Runner: resolved role from workspace owner '以太吃虾': admin
```

## 回归验证
- visitor 用户仍只能使用基础工具（web_search 等）
- admin 用户可以使用所有工具（包括 shell、文件系统等）
- Console 渠道不受影响（已有 request.state.role，不走 fallback）
