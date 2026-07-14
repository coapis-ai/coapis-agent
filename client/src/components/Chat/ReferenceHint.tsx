// 引用提示组件

import { Tag, Button, Space } from 'antd';
import { FileOutlined, BookOutlined } from '@ant-design/icons';
import type { FileInfo, KnowledgeInfo } from './types';
import './ReferenceHint.module.less';

interface ReferenceHintProps {
  files: FileInfo[];
  knowledge: KnowledgeInfo[];
  onRemoveFile: (id: string) => void;
  onRemoveKnowledge: (id: string) => void;
  onClear: () => void;
}

/**
 * 引用提示组件
 * 显示在输入框上方，提示已选择的文件和知识库
 */
export function ReferenceHint({
  files,
  knowledge,
  onRemoveFile,
  onRemoveKnowledge,
  onClear,
}: ReferenceHintProps) {
  const totalCount = files.length + knowledge.length;

  if (totalCount === 0) return null;

  return (
    <div className="reference-hint">
      <div className="reference-hint-content">
        <Space size={[4, 8]} wrap>
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
        </Space>

        <Button
          type="link"
          size="small"
          onClick={onClear}
          className="clear-button"
        >
          清空
        </Button>
      </div>
    </div>
  );
}
