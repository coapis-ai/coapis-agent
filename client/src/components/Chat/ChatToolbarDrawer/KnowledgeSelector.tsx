# 知识库选择器组件（更新：使用真实API）

import { List, Checkbox, Empty, Spin, Button } from 'antd';
import { BookOutlined, ReloadOutlined } from '@ant-design/icons';
import { useKnowledgeList } from '../hooks/useKnowledgeList';
import type { KnowledgeInfo } from '../types';
import './index.module.less';

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
  const { loading, knowledgeList, error, refresh } = useKnowledgeList();

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

      {/* 错误提示 */}
      {error && (
        <div className="error-message" style={{ padding: 16, color: '#ff4d4f' }}>
          {error}
        </div>
      )}

      {/* 知识库列表 */}
      {loading && knowledgeList.length === 0 ? (
        <div className="loading-container">
          <Spin />
        </div>
      ) : knowledgeList.length > 0 ? (
        <>
          <List
            dataSource={knowledgeList}
            renderItem={(item) => (
              <List.Item className="knowledge-item">
                <Checkbox
                  checked={selected.some(k => k.id === item.id)}
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
                    {item.documentCount && (
                      <div className="knowledge-meta">
                        {item.documentCount} 篇文档
                      </div>
                    )}
                  </div>
                </Checkbox>
              </List.Item>
            )}
          />

          {/* 已选数量 */}
          {selected.length > 0 && (
            <div className="selected-count">
              已选择 {selected.length} 个知识库
              <Button type="link" size="small" onClick={() => onSelect([])}>
                清空
              </Button>
            </div>
          )}
        </>
      ) : (
        <Empty 
          description="暂无知识库" 
          image={Empty.PRESENTED_IMAGE_SIMPLE}
        />
      )}
    </div>
  );
}
