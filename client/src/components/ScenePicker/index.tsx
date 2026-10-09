import React, { useMemo, useState } from 'react';
import { Row, Col, Input, Select, Empty } from 'antd';
import { SearchOutlined } from '@ant-design/icons';
import SceneCard from '../SceneCard';
import type { SceneConfig } from '../../pages/Workbench/types';
import styles from './index.module.less';

const { Search } = Input;
const { Option } = Select;

export interface ScenePickerProps {
  /** 全量场景（组件内部按 status/分类/搜索/标签过滤） */
  scenes: SceneConfig[];
  /** 点击卡片：进入该场景 */
  onSelect: (scene: SceneConfig) => void;
  /** 当前场景 id（高亮 + 「当前」标记，并置顶） */
  currentSceneId?: string;
  /** 按分类标签过滤（工作台 URL 参数），'all' 表示不过滤 */
  categoryFilterId?: string;
  /** 是否显示标签下拉筛选 */
  showTagFilter?: boolean;
  /** 是否显示搜索框 */
  showSearch?: boolean;
  /** 打开时自动聚焦搜索框（弹窗场景） */
  autoFocusSearch?: boolean;
  /** 栅格列宽（默认与工作台一致） */
  cols?: { xs: number; sm: number; md: number; lg: number };
  /** 内容区最大高度（弹窗内滚动），不传则不限制 */
  maxHeight?: number;
  /** 空态文案 */
  emptyText?: string;
}

/**
 * 场景选择器（共享组件）。
 * = 搜索框 + 标签筛选 + 卡片栅格，与工作台同一套组件与样式。
 * 工作台页面与聊天页「切换场景」弹窗共用，避免重复实现。
 */
const ScenePicker: React.FC<ScenePickerProps> = ({
  scenes,
  onSelect,
  currentSceneId,
  categoryFilterId,
  showTagFilter = true,
  showSearch = true,
  autoFocusSearch = false,
  cols,
  maxHeight,
  emptyText,
}) => {
  const [searchText, setSearchText] = useState('');
  const [selectedTag, setSelectedTag] = useState<string>();

  const allTags = useMemo(
    () => Array.from(new Set(scenes.flatMap((s) => s.tags))),
    [scenes],
  );

  const filteredScenes = useMemo(() => {
    const list = scenes.filter((scene) => {
      if (scene.status !== 'active') return false;

      // 按分类过滤（primary_tag_id 与 tag_ids 双匹配）
      if (categoryFilterId && categoryFilterId !== 'all') {
        const matchPrimaryTag = scene.primary_tag_id === categoryFilterId;
        const matchTagIds = scene.tag_ids && scene.tag_ids.includes(categoryFilterId);
        if (!matchPrimaryTag && !matchTagIds) return false;
      }

      if (searchText) {
        const searchLower = searchText.toLowerCase();
        const matchName = scene.name.toLowerCase().includes(searchLower);
        const matchDesc = (scene.description || '').toLowerCase().includes(searchLower);
        if (!matchName && !matchDesc) return false;
      }

      if (selectedTag && !scene.tags.includes(selectedTag)) return false;

      return true;
    });

    // 当前场景置顶，其余按使用热度降序
    list.sort((a, b) => {
      if (a.id === currentSceneId) return -1;
      if (b.id === currentSceneId) return 1;
      return (b.usage_count || 0) - (a.usage_count || 0);
    });

    return list;
  }, [scenes, categoryFilterId, searchText, selectedTag, currentSceneId]);

  const gridCols = cols ?? { xs: 24, sm: 12, md: 8, lg: 6 };

  return (
    <div
      className={styles.picker}
      style={maxHeight ? { maxHeight, overflowY: 'auto' } : undefined}
    >
      {(showSearch || showTagFilter) && (
        <div className={styles.filterBar}>
          {showSearch && (
            <Search
              placeholder="搜索场景"
              allowClear
              autoFocus={autoFocusSearch}
              prefix={<SearchOutlined />}
              onChange={(e) => setSearchText(e.target.value)}
              style={{ width: showTagFilter ? 260 : 300 }}
            />
          )}
          {showTagFilter && (
            <Select
              placeholder="选择标签"
              allowClear
              style={{ width: 150 }}
              onChange={setSelectedTag}
              value={selectedTag}
            >
              {allTags.map((tag) => (
                <Option key={tag} value={tag}>
                  {tag}
                </Option>
              ))}
            </Select>
          )}
        </div>
      )}

      {filteredScenes.length === 0 ? (
        <Empty
          description={emptyText ?? '暂无场景'}
          image={Empty.PRESENTED_IMAGE_SIMPLE}
        />
      ) : (
        <Row gutter={[16, 16]}>
          {filteredScenes.map((scene) => (
            <Col
              key={scene.id}
              xs={gridCols.xs}
              sm={gridCols.sm}
              md={gridCols.md}
              lg={gridCols.lg}
            >
              <SceneCard
                scene={scene}
                onEnter={onSelect}
                current={scene.id === currentSceneId}
              />
            </Col>
          ))}
        </Row>
      )}
    </div>
  );
};

export default ScenePicker;
