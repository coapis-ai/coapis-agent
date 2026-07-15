// 聊天输入框底部组件
// 左侧：当前引用（文件/知识库）
// 右侧：模型能力提示

import { Tag, Tooltip } from 'antd';
import { FileOutlined, BookOutlined } from '@ant-design/icons';
import type { FileInfo, KnowledgeInfo } from './types';
import { ModelCapabilityHint } from './ModelCapabilityHint';
import styles from './ChatInputFooter.module.less';

interface ChatInputFooterProps {
  files: FileInfo[];
  knowledge: KnowledgeInfo[];
  onRemoveFile: (id: string) => void;
  onRemoveKnowledge: (id: string) => void;
  caps: {
    supportsMultimodal: boolean;
    supportsImage: boolean;
    supportsVideo: boolean;
  };
}

/**
 * 聊天输入框底部
 * 左侧：当前引用，右侧：模型能力
 */
export function ChatInputFooter({
  files,
  knowledge,
  onRemoveFile,
  onRemoveKnowledge,
  caps,
}: ChatInputFooterProps) {
  const totalCount = files.length + knowledge.length;

  // 没有引用时，只显示模型能力
  if (totalCount === 0) {
    return (
      <div className={styles.footer}>
        <div className={styles.left} />
        <div className={styles.right}>
          <ModelCapabilityHint caps={caps} />
        </div>
      </div>
    );
  }

  return (
    <div className={styles.footer}>
      {/* 左侧：当前引用 */}
      <div className={styles.left}>
        {files.map((file) => (
          <Tooltip key={file.id} title={file.name}>
            <Tag
              closable
              onClose={(e) => {
                e.preventDefault();
                onRemoveFile(file.id);
              }}
              className={styles.refTag}
            >
              <FileOutlined style={{ marginRight: 4 }} />
              <span className={styles.refName}>{file.name}</span>
            </Tag>
          </Tooltip>
        ))}

        {knowledge.map((item) => (
          <Tooltip key={item.id} title={item.name}>
            <Tag
              closable
              onClose={(e) => {
                e.preventDefault();
                onRemoveKnowledge(item.id);
              }}
              className={styles.refTag}
            >
              <BookOutlined style={{ marginRight: 4 }} />
              <span className={styles.refName}>{item.name}</span>
            </Tag>
          </Tooltip>
        ))}
      </div>

      {/* 右侧：模型能力 */}
      <div className={styles.right}>
        <ModelCapabilityHint caps={caps} />
      </div>
    </div>
  );
}
