# 可选依赖动态安装方案

> **版本**: 基于 `master` 分支
> **状态**: 📋 设计方案 — 待实施

---

## 一、现有机制分析

### 1.1 优雅降级（已实现）

`server/coapis/app/channels/registry.py` 中的 `_load_builtin_channels()`:

```python
for key, (module_name, class_name) in _BUILTIN_SPECS.items():
    try:
        mod = importlib.import_module(module_name, package=__package__)
        cls = getattr(mod, class_name)
        # ... 验证
    except Exception:
        if key in _REQUIRED_CHANNEL_KEYS:  # 只有 "console" 是必需的
            raise
        logger.debug("built-in channel unavailable: %s", key, exc_info=True)
        continue  # 静默跳过
```

**优点**: 启动不崩溃
**缺点**: 用户不知道缺少什么，渠道静默不可用

### 1.2 插件依赖安装（已实现）

`server/coapis/cli/plugin_commands.py` 中的插件安装流程:

```python
requirements_file = target_dir / "requirements.txt"
if requirements_file.exists():
    subprocess.run([
        sys.executable, "-m", "pip", "install", "-r", str(requirements_file)
    ], check=True, capture_output=True, text=True)
```

**优点**: 自动安装、用户无感知
**缺点**: 仅适用于插件，不适用于内置渠道

### 1.3 MCP 包恢复（已实现）

`server/deploy/entrypoint.sh` 中的 MCP 包恢复:

```python
# 从 mcp_installed.json 读取已安装的包
# 检查是否仍然存在，不存在则重新安装
for pkg in installed_pip:
    module = pkg.replace('-', '_').split('[')[0]
    r = subprocess.run(['python3', '-c', f'import {module}'], ...)
    if r.returncode != 0:
        subprocess.run(['pip', 'install', '--no-cache-dir', '-q', pkg], ...)
```

**优点**: 持久化记录、重启恢复
**缺点**: 仅适用于 MCP 包

---

## 二、设计方案：启用时自动安装

### 2.1 核心思路

在渠道配置/启用时，检测依赖是否已安装，未安装则提示用户并自动安装。

```
用户启用 wecom 渠道
    ↓
检测 wecom-aibot-python-sdk 是否已安装
    ↓
未安装 → 提示用户 → 用户确认 → pip install
    ↓
安装成功 → 渠道正常启用
安装失败 → 提示手动安装 → 渠道降级为不可用
```

### 2.2 实现位置

在 `server/coapis/app/channels/registry.py` 中增强 `_load_builtin_channels()`：

```python
# 新增：可选依赖映射
_OPTIONAL_CHANNEL_DEPS: dict[str, dict] = {
    "wecom": {
        "package": "wecom-aibot-python-sdk>=1.0.0",
        "import_name": "aibot",
        "display_name": "企业微信",
        "optional_group": "wecom",
    },
    # 未来可扩展其他渠道
}
```

### 2.3 实现逻辑

```python
def _load_builtin_channels() -> dict[str, type[BaseChannel]]:
    out: dict[str, type[BaseChannel]] = {}
    for key, (module_name, class_name) in _BUILTIN_SPECS.items():
        try:
            mod = importlib.import_module(module_name, package=__package__)
            cls = getattr(mod, class_name)
            # ... 验证
        except Exception as e:
            if key in _REQUIRED_CHANNEL_KEYS:
                raise

            # 新增：检查是否为可选依赖
            if key in _OPTIONAL_CHANNEL_DEPS:
                dep_info = _OPTIONAL_CHANNEL_DEPS[key]
                logger.info(
                    "Channel '%s' (%s) dependency not installed: %s\n"
                    "Install with: pip install %s\n"
                    "Or skip this channel.",
                    key,
                    dep_info["display_name"],
                    dep_info["package"],
                    dep_info["package"],
                )
            else:
                logger.debug("built-in channel unavailable: %s", key, exc_info=True)
            continue

        out[key] = cls
    return out
```

### 2.4 自动安装函数

```python
def try_install_channel_deps(channel_key: str) -> bool:
    """尝试安装渠道的可选依赖。

    Args:
        channel_key: 渠道名称 (e.g., "wecom")

    Returns:
        True 如果安装成功，False 否则
    """
    if channel_key not in _OPTIONAL_CHANNEL_DEPS:
        return False

    dep_info = _OPTIONAL_CHANNEL_DEPS[channel_key]
    package = dep_info["package"]

    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--no-cache-dir", package],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode == 0:
            logger.info("Installed %s for %s channel", package, channel_key)
            return True
        else:
            logger.error(
                "Failed to install %s: %s", package, result.stderr.strip()
            )
            return False
    except subprocess.TimeoutExpired:
        logger.error("Timeout installing %s", package)
        return False
    except Exception as e:
        logger.error("Error installing %s: %s", package, e)
        return False
```

### 2.5 配置时触发安装

在渠道配置命令中集成：

```python
# server/coapis/cli/channels_cmd.py (伪代码)

@click.command()
@click.argument("channel_name")
@click.option("--install-deps", is_flag=True, help="自动安装依赖")
def enable_channel(channel_name: str, install_deps: bool):
    """启用渠道。"""
    from coapis.app.channels.registry import (
        get_channel_registry,
        try_install_channel_deps,
    )

    registry = get_channel_registry()
    if channel_name not in registry:
        # 检查是否为可选依赖缺失
        from coapis.app.channels.registry import _OPTIONAL_CHANNEL_DEPS
        if channel_name in _OPTIONAL_CHANNEL_DEPS:
            dep_info = _OPTIONAL_CHANNEL_DEPS[channel_name]
            click.echo(
                f"⚠️  {dep_info['display_name']}渠道依赖未安装\n"
                f"   需要: {dep_info['package']}"
            )
            if install_deps or click.confirm("是否自动安装？"):
                if try_install_channel_deps(channel_name):
                    click.echo("✅ 依赖安装成功，重新加载渠道...")
                    from coapis.app.channels.registry import clear_builtin_channel_cache
                    clear_builtin_channel_cache()
                    registry = get_channel_registry()
                else:
                    click.echo("❌ 安装失败，请手动安装")
                    return
            else:
                click.echo("ℹ️  跳过安装，渠道暂时不可用")
                return

    # 正常启用渠道...
```

---

## 三、Docker 环境适配

### 3.1 容器内自动安装

`server/deploy/entrypoint.sh` 中增加可选依赖安装：

```bash
# ── 6. 安装启用的可选渠道依赖 ─────────────────────────────
echo ""
echo "Checking optional channel dependencies..."

# 从 config.json 读取启用的渠道
ENABLED_CHANNELS=$(python3 -c "
import json, os
working_dir = os.environ.get('COAPIS_WORKING_DIR', '/apps/ai/coapis')
config_path = f'{working_dir}/system/config.json'
try:
    with open(config_path) as f:
        config = json.load(f)
    channels = config.get('channels', {})
    enabled = [k for k, v in channels.items() if v.get('enabled', False)]
    print(' '.join(enabled))
except:
    print('')
")

# 可选依赖映射
declare -A OPTIONAL_DEPS=(
    ["wecom"]="wecom-aibot-python-sdk>=1.0.0"
)

for channel in $ENABLED_CHANNELS; do
    if [ -n "${OPTIONAL_DEPS[$channel]}" ]; then
        package="${OPTIONAL_DEPS[$channel]}"
        # 检查是否已安装
        if ! python3 -c "import ${package//-/_}" 2>/dev/null; then
            echo "  Installing $package for $channel channel..."
            pip install --no-cache-dir -q "$package" && \
                echo "  ✅ $channel channel ready" || \
                echo "  ⚠️  Failed to install $package, $channel channel unavailable"
        else
            echo "  ✓ $channel channel dependency already installed"
        fi
    fi
done
```

---

## 四、安全考虑

### 4.1 风险

| 风险 | 缓解措施 |
|------|---------|
| 自动安装恶意包 | 仅安装预定义白名单中的包 |
| 安装失败阻塞启动 | 超时控制 + 降级为手动安装提示 |
| 网络不可用 | 检测网络状态，不可用时跳过 |
| 权限不足 | 检测 pip 权限，失败时提示 |

### 4.2 白名单机制

```python
# 仅允许安装预定义的可选依赖
_ALLOWED_OPTIONAL_DEPS: frozenset[str] = frozenset({
    "wecom-aibot-python-sdk",
    # 未来添加新包时必须在此白名单中声明
})

def try_install_channel_deps(channel_key: str) -> bool:
    dep_info = _OPTIONAL_CHANNEL_DEPS.get(channel_key)
    if not dep_info:
        return False

    package_name = dep_info["package"].split(">=")[0].split("<=")[0].split("==")[0]
    if package_name not in _ALLOWED_OPTIONAL_DEPS:
        logger.warning("Refusing to install unlisted package: %s", package_name)
        return False

    # ... 安装逻辑
```

---

## 五、实施计划

### Phase 1: 基础框架（1-2天）

- [ ] 定义 `_OPTIONAL_CHANNEL_DEPS` 映射
- [ ] 实现 `try_install_channel_deps()` 函数
- [ ] 增强 `_load_builtin_channels()` 日志输出

### Phase 2: CLI 集成（1-2天）

- [ ] 在 `enable_channel` 命令中集成自动安装
- [ ] 添加 `--install-deps` 选项
- [ ] 添加 `--skip-install` 选项

### Phase 3: Docker 集成（1天）

- [ ] 在 `entrypoint.sh` 中添加可选依赖检测
- [ ] 从 config.json 读取启用渠道
- [ ] 自动安装缺失依赖

### Phase 4: 安全加固（1天）

- [ ] 实现白名单机制
- [ ] 添加超时控制
- [ ] 添加网络检测

---

## 六、用户体验

### 6.1 首次启用企业微信

```bash
$ coapis channels enable wecom

⚠️  企业微信渠道依赖未安装
   需要: wecom-aibot-python-sdk>=1.0.0

是否自动安装？ [y/N]: y

📦 Installing wecom-aibot-python-sdk>=1.0.0...
✅ 依赖安装成功
✅ 企业微信渠道已启用
```

### 6.2 Docker 首次启动

```
==========================================
CoApis Server Starting
==========================================
WORKING_DIR: /data/coapis
==========================================
✓ Version: 0.8.26-dev
📦 First startup detected, running initialization...
✅ Initialization complete!

Checking optional channel dependencies...
  Installing wecom-aibot-python-sdk>=1.0.0 for wecom channel...
  ✅ wecom channel ready
  ✓ dingtalk channel dependency already installed

CoApis ready!
```

---

*基于 CoApis-agent 源码分析整理*
