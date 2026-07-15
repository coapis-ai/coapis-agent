// 聊天输入框底部引用条
// 单行显示已选择的文件和知识库，超长省略

import { Tag, Tooltip } from 'antd';
import { FileOutlined, BookOutlined } from '@ant-design/icons';
import type { FileInfo, KnowledgeInfo } from './types';
import styles from './ChatInputFooter.module.less';

interface ChatInputFooterProps {
  files: FileInfo[];
  knowledge: KnowledgeInfo[];
  onRemoveFile: (id: string) => void;
  onRemoveKnowledge: (id: string) => void;
}

/**
 * 聊天输入框底部引用条
 * 单行显示，超长省略
 */
export function ChatInputFooter({
  files,
  knowledge,
  onRemoveFile,
  onRemoveKnowledge,
}: ChatInputFooterProps) {
  const totalCount = files.length + knowledge.length;

  // 没有引用时不显示
  if (totalCount === 0) {
    return null;
  }

  // 构建显示内容
  const items: Array<{ type: 'file' | 'knowledge'; name: string; id: string }> = [
    ...files.map(f => ({ type: 'file' as const, name: f.name, id: f.id })),
    ...knowledge.map(k => ({ type: 'knowledge' as const, name: k.name, id: k.id })),
  ];

  // 限制显示数量，避免换行
  const maxDisplay = 3;
  const displayItems = items.slice(0, maxDisplay);
  const remainingCount = items.length - maxDisplay;

  return (
    <div className={styles.footer}>
      <div className={styles.left}>
        {displayItems.map((item) => (
          <Tag
            key={item.id}
            closable
            onClose={(e) => {
              e.preventDefault();
              if (item.type === 'file') {
                onRemoveFile(item.id);
              } else {
                onRemoveKnowledge(item.id);
              }
            }}
            className={styles.refTag}
          >
            {item.type === 'file' ? <FileOutlined /> : <BookOutlined />}
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
