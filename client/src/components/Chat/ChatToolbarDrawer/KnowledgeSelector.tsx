// 知识库选择器组件

import { Button, Empty, Checkbox } from 'antd';
import { ReloadOutlined, BookOutlined } from '@ant-design/icons';
import { useKnowledgeList } from '../hooks/useKnowledgeList';
import type { KnowledgeInfo } from '../types';

interface KnowledgeSelectorProps {
  selected: KnowledgeInfo[];
  onSelect: (items: KnowledgeInfo[]) => void;
}

/**
 * 知识库选择器
 * 
 * 功能：
 * - 列表展示知识库
 * - 显示知识库描述
 * - 支持多选（复选框）
 */
export function KnowledgeSelector({ selected, onSelect }: KnowledgeSelectorProps) {
  const { knowledgeList, loading, refresh } = useKnowledgeList();

  // 处理选择
  const handleSelect = (item: KnowledgeInfo, checked: boolean) => {
    if (checked) {
      onSelect([...selected, item]);
    } else {
      onSelect(selected.filter(k => k.id !== item.id));
    }
  };

  return (
    <div className="chat-toolbar-knowledge-selector">
      {/* 刷新按钮 */}
      <div style={{ padding: '8px 16px', textAlign: 'right' }}>
        <Button
          type="text"
          size="small"
          icon={<ReloadOutlined />}
          onClick={refresh}
          loading={loading}
        >
          刷新
        </Button>
      </div>

      {/* 知识库列表 */}
      {knowledgeList.length > 0 ? (
        <div className="knowledge-list">
          {knowledgeList.map((item) => (
            <div key={item.id} className="knowledge-item">
              <Checkbox
                checked={selected.some(s => s.id === item.id)}
                onChange={(e) => handleSelect(item, e.target.checked)}
              >
                <div className="knowledge-content">
                  <div className="knowledge-name">
                    <BookOutlined style={{ marginRight: 8 }} />
                    {item.name}
                  </div>
                  {item.description && (
                    <div className="knowledge-desc">{item.description}</div>
                  )}
                  <div className="knowledge-meta">
                    文档数: {item.documentCount || 0}
                  </div>
                </div>
              </Checkbox>
            </div>
          ))}
        </div>
      ) : (
        <Empty description="暂无知识库" />
      )}

      {/* 已选数量 */}
      {selected.length > 0 && (
        <div className="selected-count">
          <span>已选择 {selected.length} 个知识库</span>
          <Button type="link" size="small" onClick={() => onSelect([])}>
            清空
          </Button>
        </div>
      )}
    </div>
  );
}
