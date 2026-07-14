# 知识库选择器组件

import { useState, useEffect } from 'react';
import { List, Checkbox, Empty, Spin, Button } from 'antd';
import { BookOutlined } from '@ant-design/icons';
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
  const [loading, setLoading] = useState(false);
  const [knowledgeList, setKnowledgeList] = useState<KnowledgeInfo[]>([]);

  // TODO: 加载知识库列表（后续对接API）
  useEffect(() => {
    // 模拟数据
    setLoading(true);
    setTimeout(() => {
      setKnowledgeList([
        {
          id: 'kb-1',
          name: '产品文档',
          description: '产品需求、功能说明、用户手册',
          documentCount: 15,
        },
        {
          id: 'kb-2',
          name: '技术文档',
          description: 'API文档、开发指南、最佳实践',
          documentCount: 23,
        },
        {
          id: 'kb-3',
          name: '运维文档',
          description: '部署、配置、监控、故障排查',
          documentCount: 8,
        },
      ]);
      setLoading(false);
    }, 500);
  }, []);

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
      {loading ? (
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
        <Empty description="暂无知识库" />
      )}
    </div>
  );
}
