// 聊天输入框底部引用条
// 单行显示已选择的资源芯片（文件/知识库/会话引用），超长省略
// 模型不在这里显示：模型选择归输入框左侧的芯片（ModelChips），避免两处重复
// MCP / 技能芯片已按 D6 删除（无后端接线，恒为空）

import { Tag, Tooltip } from 'antd';
import {
  FileOutlined,
  BookOutlined,
  HistoryOutlined,
} from '@ant-design/icons';
import type { FileInfo, KnowledgeInfo } from './types';
import styles from './ChatInputFooter.module.less';

export interface RefChip {
  id: string;
  name: string;
}

interface ChatInputFooterProps {
  files: FileInfo[];
  knowledge: KnowledgeInfo[];
  onRemoveFile: (id: string) => void;
  onRemoveKnowledge: (id: string) => void;
  sessions?: RefChip[];
  onRemoveSession?: (id: string) => void;
}

type ChipKind = 'file' | 'knowledge' | 'session';

const CHIP_ICON: Record<ChipKind, React.ReactNode> = {
  file: <FileOutlined />,
  knowledge: <BookOutlined />,
  session: <HistoryOutlined />,
};

/**
 * 聊天输入框底部引用条
 * 单行显示，超长省略
 * 无引用时显示占位文字
 */
export function ChatInputFooter({
  files,
  knowledge,
  onRemoveFile,
  onRemoveKnowledge,
  sessions = [],
  onRemoveSession,
}: ChatInputFooterProps) {
  const items: Array<{ kind: ChipKind; id: string; name: string }> = [
    ...files.map(f => ({ kind: 'file' as const, name: f.name, id: f.id })),
    ...knowledge.map(k => ({ kind: 'knowledge' as const, name: k.name, id: k.id })),
    ...sessions.map(s => ({ kind: 'session' as const, name: s.name, id: s.id })),
  ];

  const totalCount = items.length;

  // 没有引用时显示占位文字
  if (totalCount === 0) {
    return (
      <div className={styles.footer}>
        <div className={styles.placeholder}>
          引用资源
        </div>
      </div>
    );
  }

  const handleRemove = (kind: ChipKind, id: string) => {
    switch (kind) {
      case 'file': onRemoveFile(id); break;
      case 'knowledge': onRemoveKnowledge(id); break;
      case 'session': onRemoveSession?.(id); break;
    }
  };

  // 限制显示数量，避免换行
  const maxDisplay = 4;
  const displayItems = items.slice(0, maxDisplay);
  const remainingCount = items.length - maxDisplay;

  return (
    <div className={styles.footer}>
      <div className={styles.left}>
        {displayItems.map((item) => (
          <Tag
            key={`${item.kind}:${item.id}`}
            closable
            onClose={(e) => {
              e.preventDefault();
              handleRemove(item.kind, item.id);
            }}
            className={styles.refTag}
          >
            {CHIP_ICON[item.kind]}
            <span className={styles.refName}>{item.name}</span>
          </Tag>
        ))}
        
        {remainingCount > 0 && (
          <Tooltip title={`还有 ${remainingCount} 项未显示`}>
            <Tag className={styles.refTag}>+{remainingCount}</Tag>
          </Tooltip>
        )}
      </div>
    </div>
  );
}
