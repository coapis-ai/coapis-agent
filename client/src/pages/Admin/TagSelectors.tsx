// Tag selector components for scene management
import React, { useState, useEffect, useMemo } from 'react';
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
 * Primary tag selector - shows category tags organized by dimension
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
  const [allTags, setAllTags] = useState<TagConfig[]>([]);

  useEffect(() => {
    loadAllTags();
  }, []);

  const loadAllTags = async () => {
    try {
      setLoading(true);
      const token = getApiToken();
      const response = await fetch('/api/admin/tags?enabled=true', {
        headers: {
          'Authorization': `Bearer ${token}`,
        },
      });
      
      if (!response.ok) {
        throw new Error('Failed to load tags');
      }
      
      const data: TagListResponse = await response.json();
      setAllTags(data.tags);
    } catch (error) {
      console.error('Failed to load tags:', error);
    } finally {
      setLoading(false);
    }
  };

  // Build tree data: dimension tags as parents, category tags as children
  const treeData = useMemo(() => {
    const dimensionTags = allTags.filter(t => t.type === 'dimension');
    const categoryTags = allTags.filter(t => t.type === 'category');
    
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
  }, [allTags]);

  if (loading) {
    return <Spin size="small" />;
  }

  return (
    <TreeSelect
      value={value}
      onChange={onChange}
      treeData={treeData}
      placeholder={placeholder}
      showSearch
      treeDefaultExpandAll
      style={{ width: '100%' }}
    />
  );
};

/**
 * Other tags selector - shows industry and frequency tags (category tags under industry/frequency dimensions)
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
      
      // Load ALL enabled tags, then filter for category tags under industry and frequency dimensions
      const response = await fetch('/api/admin/tags?enabled=true', {
        headers: { 'Authorization': `Bearer ${token}` },
      });
      
      if (!response.ok) {
        throw new Error('Failed to load tags');
      }
      
      const data: TagListResponse = await response.json();
      
      // Filter: category tags whose parent_id is 'industry' or 'frequency'
      const industryAndFrequencyTags = data.tags.filter(
        t => t.type === 'category' && (t.parent_id === 'industry' || t.parent_id === 'frequency')
      );
      
      setTags(industryAndFrequencyTags);
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