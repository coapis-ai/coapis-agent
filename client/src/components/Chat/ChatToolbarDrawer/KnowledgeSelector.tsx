// 知识库选择器组件

import { useMemo } from 'react';
import { List, Checkbox, Empty, Spin } from 'antd';
import { BookOutlined } from '@ant-design/icons';
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
 * - 显示知识库列表
 * - 支持多选
 * - 无知识库时显示空状态（不报错）
 */
export function KnowledgeSelector({ selected, onSelect }: KnowledgeSelectorProps) {
  const { knowledgeList, loading } = useKnowledgeList();

  // 选中的知识库ID
  const selectedIds = useMemo(() => {
    return selected.map(item => item.id);
  }, [selected]);

  // 处理选择
  const handleToggle = (item: KnowledgeInfo) => {
    if (selectedIds.includes(item.id)) {
      // 取消选择
      onSelect(selected.filter(s => s.id !== item.id));
    } else {
      // 添加选择
      onSelect([...selected, item]);
    }
  };

  return (
    <div style={{ maxHeight: 300, overflowY: 'auto' }}>
      <Spin spinning={loading}>
        {knowledgeList.length > 0 ? (
          <List
            dataSource={knowledgeList}
            renderItem={(item) => (
              <List.Item
                style={{ padding: '8px 0', border: 'none' }}
                actions={[
                  <Checkbox
                    key="checkbox"
                    checked={selectedIds.includes(item.id)}
                    onChange={() => handleToggle(item)}
                  />,
                ]}
              >
                <List.Item.Meta
                  avatar={<BookOutlined style={{ color: '#1890ff' }} />}
                  title={item.name}
                  description={item.description || `${item.documentCount || 0} 个文档`}
                />
              </List.Item>
            )}
          />
        ) : (
          <Empty 
            description="暂无知识库" 
            image={Empty.PRESENTED_IMAGE_SIMPLE}
          />
        )}
      </Spin>
    </div>
  );
}
