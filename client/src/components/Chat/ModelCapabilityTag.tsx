// 模型能力标签组件
// 显示在输入框右侧

import { ModelCapabilityHint } from './ModelCapabilityHint';

interface ModelCapabilityTagProps {
  caps: {
    supportsMultimodal: boolean;
    supportsImage: boolean;
    supportsVideo: boolean;
  };
}

/**
 * 模型能力标签
 * 用于 sender.prefix，显示在输入框右侧
 */
export function ModelCapabilityTag({ caps }: ModelCapabilityTagProps) {
  return (
    <div style={{
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'flex-end',
      padding: '0 8px',
    }}>
      <ModelCapabilityHint caps={caps} />
    </div>
  );
}
