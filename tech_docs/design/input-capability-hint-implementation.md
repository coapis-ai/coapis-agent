# 输入框下方显示模型能力提示 - 实现方案

## ✅ 发现：Sender 组件支持 footer 属性

```typescript
// node_modules/@agentscope-ai/chat/lib/Sender/index.d.ts
export interface SenderProps {
  /**
   * @description 底部 UI
   * @descriptionEn Footer UI
   */
  footer?: React.ReactNode;
}
```

**这意味着我们可以直接使用 `sender.footer` 配置来显示能力提示！**

---

## 📍 实现位置

```tsx
// Chat/index.tsx
const options: IAgentScopeRuntimeWebUIOptions = {
  sender: {
    // ... 其他配置
    footer: (
      <ModelCapabilityHint caps={multimodalCaps} />
    ),
  },
  // ... 其他配置
};
```

---

## 💡 完整实现代码

### 1. 创建 ModelCapabilityHint 组件

```tsx
// client/src/components/Chat/ModelCapabilityHint.tsx
import React from 'react';
import { Space } from 'antd';
import { 
  CheckCircleOutlined, 
  WarningOutlined,
  InfoCircleOutlined,
  EyeOutlined,
  VideoCameraOutlined 
} from '@ant-design/icons';
import { useTranslation } from 'react-i18next';
import styles from './ModelCapabilityHint.module.less';

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
        <Space size={4}>
          <CheckCircleOutlined style={{ color: '#52c41a' }} />
          <span>{t('chat.capability.imageAndVideo')}</span>
        </Space>
      </div>
    );
  }
  
  // 仅支持图片
  if (caps.supportsImage) {
    return (
      <div className={styles.hint}>
        <Space size={4}>
          <CheckCircleOutlined style={{ color: '#52c41a' }} />
          <EyeOutlined style={{ color: '#52c41a' }} />
          <span>{t('chat.capability.imageOnly')}</span>
        </Space>
      </div>
    );
  }
  
  // 仅支持视频
  if (caps.supportsVideo) {
    return (
      <div className={styles.hint}>
        <Space size={4}>
          <CheckCircleOutlined style={{ color: '#52c41a' }} />
          <VideoCameraOutlined style={{ color: '#52c41a' }} />
          <span>{t('chat.capability.videoOnly')}</span>
        </Space>
      </div>
    );
  }
  
  // 纯文本模型（已探测但不支持）
  if (caps.supportsMultimodal === false) {
    return (
      <div className={`${styles.hint} ${styles.warning}`}>
        <Space size={4}>
          <WarningOutlined style={{ color: '#faad14' }} />
          <span>{t('chat.capability.textOnly')}</span>
        </Space>
      </div>
    );
  }
  
  // 未检测
  return (
    <div className={styles.hint}>
      <Space size={4}>
        <InfoCircleOutlined style={{ color: '#1890ff' }} />
        <span>{t('chat.capability.notProbed')}</span>
      </Space>
    </div>
  );
}
```

### 2. 样式文件

```less
// client/src/components/Chat/ModelCapabilityHint.module.less
.hint {
  padding: 6px 0;
  font-size: 12px;
  color: rgba(0, 0, 0, 0.45);
  text-align: center;
  user-select: none;
  
  &.warning {
    color: #faad14;
  }
}

// 暗色模式适配
@media (prefers-color-scheme: dark) {
  .hint {
    color: rgba(255, 255, 255, 0.45);
    
    &.warning {
      color: #faad14;
    }
  }
}
```

### 3. 国际化文案

```json
// client/src/locales/zh.json
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
// client/src/locales/en.json
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

### 4. 集成到 Chat 页面

```tsx
// client/src/pages/Chat/index.tsx
import { ModelCapabilityHint } from '../../components/Chat/ModelCapabilityHint';

// 在 options 配置中添加 footer
const options: IAgentScopeRuntimeWebUIOptions = {
  sender: {
    // ... 原有配置
    placeholder: t('chat.inputPlaceholder'),
    attachments: {
      // ... 附件配置
    },
    // 添加能力提示
    footer: <ModelCapabilityHint caps={multimodalCaps} />,
  },
  // ... 其他配置
};
```

---

## 🎨 效果预览

### 支持图片+视频

```
┌────────────────────────────────────────┐
│ [📎] [🎤] [________________] [发送]   │
├────────────────────────────────────────┤
│ ✓ 支持图片和视频识别                   │
└────────────────────────────────────────┘
```

### 仅支持图片

```
┌────────────────────────────────────────┐
│ [📎] [🎤] [________________] [发送]   │
├────────────────────────────────────────┤
│ ✓ 👁 支持图片识别                      │
└────────────────────────────────────────┘
```

### 纯文本模型

```
┌────────────────────────────────────────┐
│ [📎] [🎤] [________________] [发送]   │
├────────────────────────────────────────┤
│ ⚠ 当前模型不支持图片/视频识别         │
└────────────────────────────────────────┘
```

### 未检测

```
┌────────────────────────────────────────┐
│ [📎] [🎤] [________________] [发送]   │
├────────────────────────────────────────┤
│ ℹ 模型能力未检测                       │
└────────────────────────────────────────┘
```

---

## 🔄 数据流

```
用户切换模型
  ↓
window.dispatchEvent(new CustomEvent('model-switched'))
  ↓
useMultimodalCapabilities hook 监听
  ↓
fetchMultimodalCaps()
  ↓
setMultimodalCaps({
  supportsMultimodal: model.supports_multimodal,
  supportsImage: model.supports_image,
  supportsVideo: model.supports_video
})
  ↓
ModelCapabilityHint 组件重新渲染
  ↓
显示新的能力提示
```

**关键**：`multimodalCaps` 是响应式状态，模型切换时自动更新，提示也会自动更新。

---

## 📋 实施步骤

### 第一步：创建组件

1. 创建 `client/src/components/Chat/ModelCapabilityHint.tsx`
2. 创建 `client/src/components/Chat/ModelCapabilityHint.module.less`
3. 添加导出到 `client/src/components/Chat/index.ts`

### 第二步：添加国际化

1. 更新 `client/src/locales/zh.json`
2. 更新 `client/src/locales/en.json`

### 第三步：集成到聊天页面

1. 在 `client/src/pages/Chat/index.tsx` 中导入组件
2. 在 `options.sender` 配置中添加 `footer`

### 第四步：测试

1. 切换不同能力的模型，验证提示更新
2. 测试暗色模式
3. 测试移动端显示

---

## ✅ 优点

1. **简洁明了** - 一行文字，信息清晰
2. **实时更新** - 模型切换时自动更新
3. **实现简单** - 利用现有 footer 属性
4. **不占空间** - 在输入框正下方，不影响聊天区域
5. **原生支持** - 使用组件库原生功能

---

## 📌 注意事项

1. **样式适配** - 注意暗色模式下的颜色对比度
2. **移动端** - 字体大小和间距可能需要调整
3. **性能** - 使用已有的 `multimodalCaps` 状态，无需额外请求
4. **空状态** - 当 `multimodalCaps` 为初始状态时，显示"未检测"

---

## 🚀 开始实施？

需要我开始创建这些文件吗？
