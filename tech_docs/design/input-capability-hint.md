# 输入框下方显示模型能力提示

## 🎯 需求

在聊天输入框下方显示一行文字，说明当前模型支持什么能力，模型切换时自动更新。

---

## 📍 实现位置

```
聊天界面布局：
┌────────────────────────────────┐
│ 聊天消息区域                   │
│                                │
├────────────────────────────────┤
│ 输入框                         │
│                                │
├────────────────────────────────┤
│ ✓ 支持图片和视频识别           │  ← 新增能力提示
└────────────────────────────────┘
```

---

## 💡 实现方案

### 方案一：使用 AgentScopeRuntimeWebUI 的 footer 配置

检查 `@agentscope-ai/chat` 是否支持 footer 配置。

### 方案二：在 AgentScopeRuntimeWebUI 外部添加提示

在 Chat 页面中，`AgentScopeRuntimeWebUI` 组件下方添加能力提示。

```tsx
<div className={styles.chatContainer}>
  <AgentScopeRuntimeWebUI {...config} ref={chatRef} />
  
  {/* 能力提示 */}
  <div className={styles.capabilityHint}>
    <ModelCapabilityHint caps={multimodalCaps} />
  </div>
</div>
```

---

## 🎨 UI 设计

### 显示内容

```
支持图片+视频：
✓ 支持图片和视频识别

仅支持图片：
✓ 支持图片识别

纯文本模型：
⚠ 当前模型不支持图片/视频识别

未检测：
ℹ 模型能力未检测，建议点击探测
```

### 样式

```less
.capabilityHint {
  padding: 8px 16px;
  text-align: center;
  font-size: 12px;
  color: rgba(0, 0, 0, 0.45);
  background: #fafafa;
  border-top: 1px solid #f0f0f0;
  
  .icon {
    margin-right: 4px;
  }
  
  &.warning {
    color: #faad14;
    background: #fffbe6;
  }
}
```

---

## 📝 具体实现

### 组件代码

```tsx
// components/ModelCapabilityHint.tsx
import { Space, Tag } from "antd";
import { 
  CheckCircleOutlined, 
  WarningOutlined,
  InfoCircleOutlined 
} from "@ant-design/icons";
import { useTranslation } from "react-i18next";

interface CapabilityHintProps {
  caps: {
    supportsMultimodal: boolean;
    supportsImage: boolean;
    supportsVideo: boolean;
  };
}

export function ModelCapabilityHint({ caps }: CapabilityHintProps) {
  const { t } = useTranslation();
  
  // 支持图片+视频
  if (caps.supportsImage && caps.supportsVideo) {
    return (
      <div className={styles.hint}>
        <CheckCircleOutlined className={styles.icon} />
        <span>{t("chat.capability.imageAndVideo")}</span>
      </div>
    );
  }
  
  // 仅支持图片
  if (caps.supportsImage) {
    return (
      <div className={styles.hint}>
        <CheckCircleOutlined className={styles.icon} />
        <span>{t("chat.capability.imageOnly")}</span>
      </div>
    );
  }
  
  // 纯文本模型
  if (caps.supportsMultimodal === false) {
    return (
      <div className={`${styles.hint} ${styles.warning}`}>
        <WarningOutlined className={styles.icon} />
        <span>{t("chat.capability.textOnly")}</span>
      </div>
    );
  }
  
  // 未检测
  return (
    <div className={styles.hint}>
      <InfoCircleOutlined className={styles.icon} />
      <span>{t("chat.capability.notProbed")}</span>
    </div>
  );
}
```

### 国际化文案

```json
// zh.json
{
  "chat": {
    "capability": {
      "imageAndVideo": "支持图片和视频识别",
      "imageOnly": "支持图片识别",
      "videoOnly": "支持视频识别",
      "textOnly": "当前模型不支持图片/视频识别",
      "notProbed": "模型能力未检测"
    }
  }
}
```

```json
// en.json
{
  "chat": {
    "capability": {
      "imageAndVideo": "Supports image and video recognition",
      "imageOnly": "Supports image recognition",
      "videoOnly": "Supports video recognition",
      "textOnly": "Current model does not support image/video recognition",
      "notProbed": "Model capability not probed"
    }
  }
}
```

---

## 🔄 数据流

```
用户切换模型
  ↓
window.dispatchEvent(new CustomEvent("model-switched"))
  ↓
useMultimodalCapabilities hook 监听
  ↓
fetchMultimodalCaps()
  ↓
setMultimodalCaps({ ... })
  ↓
ModelCapabilityHint 组件重新渲染
  ↓
显示新的能力提示
```

---

## 📋 实施步骤

### 第一步：创建组件

1. 创建 `components/ModelCapabilityHint.tsx`
2. 添加样式文件 `ModelCapabilityHint.module.less`
3. 添加国际化文案

### 第二步：集成到聊天页面

1. 在 `Chat/index.tsx` 中导入组件
2. 在 `AgentScopeRuntimeWebUI` 下方添加提示
3. 传入 `multimodalCaps` 状态

### 第三步：测试

1. 切换模型，验证提示更新
2. 测试不同能力组合的显示
3. 测试移动端显示

---

## 🎯 效果预览

### PC 端

```
┌────────────────────────────────────────┐
│ 聊天消息区域                           │
│                                        │
├────────────────────────────────────────┤
│ 输入框                                 │
│ [📎] [🎤] [________________] [发送]   │
├────────────────────────────────────────┤
│ ✓ 支持图片和视频识别                   │
└────────────────────────────────────────┘
```

### 移动端

```
┌──────────────────────┐
│ 聊天消息区域         │
├──────────────────────┤
│ 输入框               │
│ [📎][___][🎤][发送] │
├──────────────────────┤
│ ✓ 支持图片识别       │
└──────────────────────┘
```

---

## ✅ 优点

1. **简洁明了** - 一行文字，信息清晰
2. **实时更新** - 模型切换时自动更新
3. **实现简单** - 只需添加一个小组件
4. **不占空间** - 不影响聊天区域

---

## 📌 注意事项

1. **移动端适配** - 字体稍小，padding 适当减少
2. **暗色模式** - 调整颜色对比度
3. **性能** - 使用已有的 `multimodalCaps` 状态，无需额外请求

---

## 🚀 下一步

是否需要我开始实施这个方案？
