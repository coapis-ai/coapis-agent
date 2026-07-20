// Tag selector components for scene management
import React, { useState, useEffect } from 'react';
import { Select, Spin, TreeSelect } from 'antd';
import { getApiToken } from '../../api/config';

// Tag types (duplicated from TagManagement to avoid circular dependency)
interface TagConfig {
  id: string;
  name: string;
  icon: string;
  type: 'dimension' | 'category' | 'industry' | 'frequency';
  parent_id?: string;
  description?: string;
  enabled: boolean;
}

interface TagListResponse {
  tags: TagConfig[];
  total: number;
}

/**
 * Primary tag selector - only shows category tags
 * Used to determine which menu section the scene belongs to
 */
export const PrimaryTagSelector: React.FC<{
  value?: string;
  onChange?: (value: string) => void;
  placeholder?: string;
}> = ({
  value,
  onChange,
  placeholder = '选择主标签',
}) => {
  const [loading, setLoading] = useState(false);
  const [tags, setTags] = useState<TagConfig[]>([]);

  useEffect(() => {
    loadTags();
  }, []);

  const loadTags = async () => {
    try {
      setLoading(true);
      const token = getApiToken();
      const response = await fetch('/api/admin/tags?tag_type=category&enabled=true', {
        headers: {
          'Authorization': `Bearer ${token}`,
        },
      });
      
      if (!response.ok) {
        throw new Error('Failed to load tags');
      }
      
      const data: TagListResponse = await response.json();
      setTags(data.tags);
    } catch (error) {
      console.error('Failed to load tags:', error);
    } finally {
      setLoading(false);
    }
  };

  // Build tree data for TreeSelect
  const buildTreeData = () => {
    // Group tags by parent_id
    const dimensionTags = tags.filter(t => t.type === 'dimension');
    const categoryTags = tags.filter(t => t.type === 'category');
    
    return dimensionTags.map(dim => ({
      value: dim.id as string,
      title: `${dim.icon} ${dim.name}`,
      selectable: false,
      children: categoryTags
        .filter(cat => cat.parent_id === dim.id)
        .map(cat => ({
          value: cat.id as string,
          title: `${cat.icon} ${cat.name}`,
        })),
    }));
  };

  if (loading) {
    return <Spin size="small" />;
  }

  return (
    <TreeSelect
      value={value}
      onChange={onChange}
      treeData={buildTreeData()}
      placeholder={placeholder}
      showSearch
      treeDefaultExpandAll
      style={{ width: '100%' }}
    />
  );
};

/**
 * Other tags selector - shows industry and frequency tags
 * Used for scene attributes
 */
export const OtherTagsSelector: React.FC<{
  value?: string[];
  onChange?: (value: string[]) => void;
  placeholder?: string;
}> = ({
  value,
  onChange,
  placeholder = '选择其他标签',
}) => {
  const [loading, setLoading] = useState(false);
  const [tags, setTags] = useState<TagConfig[]>([]);

  useEffect(() => {
    loadTags();
  }, []);

  const loadTags = async () => {
    try {
      setLoading(true);
      const token = getApiToken();
      
      // Load industry and frequency tags
      const [industryRes, frequencyRes] = await Promise.all([
        fetch('/api/admin/tags?tag_type=industry&enabled=true', {
          headers: { 'Authorization': `Bearer ${token}` },
        }),
        fetch('/api/admin/tags?tag_type=frequency&enabled=true', {
          headers: { 'Authorization': `Bearer ${token}` },
        }),
      ]);
      
      const industryData: TagListResponse = await industryRes.json();
      const frequencyData: TagListResponse = await frequencyRes.json();
      
      setTags([...industryData.tags, ...frequencyData.tags]);
    } catch (error) {
      console.error('Failed to load tags:', error);
    } finally {
      setLoading(false);
    }
  };

  if (loading) {
    return <Spin size="small" />;
  }

  return (
    <Select
      mode="multiple"
      value={value}
      onChange={onChange}
      placeholder={placeholder}
      options={tags.map(t => ({
        label: `${t.icon} ${t.name}`,
        value: t.id,
      }))}
      style={{ width: '100%' }}
    />
  );
};
