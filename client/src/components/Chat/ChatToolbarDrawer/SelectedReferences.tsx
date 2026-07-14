# 已选引用组件

import { Tag, Button } from 'antd';
import { FileOutlined, BookOutlined } from '@ant-design/icons';
import type { FileInfo, KnowledgeInfo } from '../types';
import './index.module.less';

interface SelectedReferencesProps {
  files: FileInfo[];
  knowledge: KnowledgeInfo[];
  onRemoveFile: (id: string) => void;
  onRemoveKnowledge: (id: string) => void;
  onClear: () => void;
}

/**
 * 已选引用列表
 * 显示在工具栏底部
 */
export function SelectedReferences({
  files,
  knowledge,
  onRemoveFile,
  onRemoveKnowledge,
  onClear,
}: SelectedReferencesProps) {
  const totalCount = files.length + knowledge.length;

  return (
    <div className="chat-toolbar-selected-references">
      <div className="selected-header">
        <span>当前引用 ({totalCount})</span>
        <Button type="link" size="small" onClick={onClear}>
          清空所有
        </Button>
      </div>

      <div className="selected-list">
        {files.map((file) => (
          <Tag
            key={file.id}
            closable
            onClose={() => onRemoveFile(file.id)}
            className="reference-tag"
          >
            <FileOutlined style={{ marginRight: 4 }} />
            {file.name}
          </Tag>
        ))}

        {knowledge.map((item) => (
          <Tag
            key={item.id}
            closable
            onClose={() => onRemoveKnowledge(item.id)}
            className="reference-tag"
          >
            <BookOutlined style={{ marginRight: 4 }} />
            {item.name}
          </Tag>
        ))}
      </div>
    </div>
  );
}
