# 固定按钮组件

import { Button, Tooltip } from 'antd';
import { PushpinOutlined, PushpinFilled } from '@ant-design/icons';
import './index.module.less';

interface PinButtonProps {
  pinned: boolean;
  onToggle: () => void;
}

/**
 * 固定按钮
 * 用于固定工具栏，使其不自动收起
 */
export function PinButton({ pinned, onToggle }: PinButtonProps) {
  return (
    <Tooltip title={pinned ? '取消固定' : '固定工具栏'}>
      <Button
        type="text"
        className={`chat-toolbar-pin-button ${pinned ? 'pinned' : ''}`}
        icon={pinned ? <PushpinFilled /> : <PushpinOutlined />}
        onClick={(e) => {
          e.stopPropagation();
          onToggle();
        }}
        size="small"
      />
    </Tooltip>
  );
}
