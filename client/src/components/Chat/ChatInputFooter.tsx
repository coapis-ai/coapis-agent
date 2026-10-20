// 聊天输入框底部引用条
// 单行显示已选择的资源芯片（工作路径/文件/知识库），超长省略
// 模型不在这里显示：模型选择归输入框左侧的芯片（ModelChips），避免两处重复
// MCP / 技能芯片已按 D6 删除（无后端接线，恒为空）
// 会话引用已删除（A5：refSessions 是空壳——无入口写入、无出口发送，无后端消费者）

import { Tag, Tooltip, Button } from 'antd';
import {
  FileOutlined,
  BookOutlined,
  FolderOpenOutlined,
  PictureOutlined,
  VideoCameraOutlined,
  AudioOutlined,
} from '@ant-design/icons';
import { useTranslation } from 'react-i18next';
import type { FileInfo, KnowledgeInfo } from './types';
import styles from './ChatInputFooter.module.less';

interface ChatInputFooterProps {
  files: FileInfo[];
  knowledge: KnowledgeInfo[];
  onRemoveFile: (id: string) => void;
  onRemoveKnowledge: (id: string) => void;
  /** 清空全部引用（设计第四区：引用提示 + 清空） */
  onClearAll?: () => void;
}

type ChipKind = 'folder' | 'file' | 'image' | 'video' | 'audio' | 'knowledge';

const CHIP_ICON: Record<ChipKind, React.ReactNode> = {
  folder: <FolderOpenOutlined />,
  file: <FileOutlined />,
  // 媒体芯片用媒体图标：用户勾选一张图时，看到的应该是「图」而不是「文件」，
  // 与发送后气泡里的缩略图语义对上。
  image: <PictureOutlined />,
  video: <VideoCameraOutlined />,
  audio: <AudioOutlined />,
  knowledge: <BookOutlined />,
};

/**
 * 聊天输入框底部引用条
 * - 目录引用用 📁 图标 + 「工作路径」标记，与文件引用可分辨（P0-3）
 * - 左侧显示「已选 N 项」计数，右侧「清空」（设计第四区）
 * - 单行显示，超过 4 项折叠为 +N
 */
export function ChatInputFooter({
  files,
  knowledge,
  onRemoveFile,
  onRemoveKnowledge,
  onClearAll,
}: ChatInputFooterProps) {
  const { t } = useTranslation();

  // 目录在前：工作路径是上下文骨架，先看到它更符合心智
  const items: Array<{ kind: ChipKind; id: string; name: string }> = [
    ...files
      .filter((f) => f.type === 'folder')
      .map((f) => ({ kind: 'folder' as const, name: f.name, id: f.id })),
    ...files
      .filter((f) => f.type !== 'folder')
      .map((f) => ({
        // 媒体类型直接透传（image/video/audio），非媒体落 'file'
        kind: (f.type === 'image' || f.type === 'video' || f.type === 'audio'
          ? f.type
          : 'file') as ChipKind,
        name: f.name,
        id: f.id,
      })),
    ...knowledge.map((k) => ({ kind: 'knowledge' as const, name: k.name, id: k.id })),
  ];

  const totalCount = items.length;

  // 没有引用时显示占位文字
  if (totalCount === 0) {
    return (
      <div className={styles.footer}>
        <div className={styles.placeholder}>
          {t('resourceMenu.references', '引用资源')}
        </div>
      </div>
    );
  }

  const handleRemove = (kind: ChipKind, id: string) => {
    switch (kind) {
      case 'folder':
      case 'file':
      case 'image':
      case 'video':
      case 'audio':
        onRemoveFile(id);
        break;
      case 'knowledge':
        onRemoveKnowledge(id);
        break;
    }
  };

  // 限制显示数量，避免换行
  const maxDisplay = 4;
  const displayItems = items.slice(0, maxDisplay);
  const remainingCount = items.length - maxDisplay;

  return (
    <div className={styles.footer}>
      <div className={styles.left}>
        <span className={styles.count}>
          {t('resourceMenu.refCount', '已选 {{n}} 项', { n: totalCount })}
        </span>

        {displayItems.map((item) => (
          <Tooltip
            key={`${item.kind}:${item.id}`}
            title={
              item.kind === 'folder'
                ? t('resourceMenu.workingPathHint', '工作路径：智能体可访问该目录下的文件')
                : item.name
            }
          >
            <Tag
              closable
              onClose={(e) => {
                e.preventDefault();
                handleRemove(item.kind, item.id);
              }}
              className={`${styles.refTag} ${
                item.kind === 'folder' ? styles.folderTag : ''
              }`}
            >
              {CHIP_ICON[item.kind]}
              <span className={styles.refName}>{item.name}</span>
              {item.kind === 'folder' && (
                <span className={styles.folderBadge}>
                  {t('resourceMenu.workingPath', '工作路径')}
                </span>
              )}
            </Tag>
          </Tooltip>
        ))}

        {remainingCount > 0 && (
          <Tooltip
            title={t('resourceMenu.moreRefs', '还有 {{n}} 项未显示', {
              n: remainingCount,
            })}
          >
            <Tag className={styles.refTag}>+{remainingCount}</Tag>
          </Tooltip>
        )}
      </div>

      {onClearAll && (
        <Button
          type="link"
          size="small"
          className={styles.clearBtn}
          onClick={onClearAll}
        >
          {t('resourceMenu.clearAll', '清空')}
        </Button>
      )}
    </div>
  );
}
