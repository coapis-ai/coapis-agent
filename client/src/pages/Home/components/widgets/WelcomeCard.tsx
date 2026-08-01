/**
 * 欢迎卡片组件
 */

import React, { useState, useEffect } from 'react';
import { EditOutlined, CheckOutlined } from '@ant-design/icons';
import { message } from 'antd';
import styles from '../../styles.module.less';
import { WidgetProps } from '../../types';

interface WelcomeCardProps extends WidgetProps {}

// 可选的职能标签列表
const AVAILABLE_TAGS = [
  { id: 'hr', name: '人力资源', icon: '👥' },
  { id: 'finance', name: '财务管理', icon: '💰' },
  { id: 'project', name: '项目管理', icon: '📋' },
  { id: 'marketing', name: '市场营销', icon: '📊' },
  { id: 'research', name: '研究开发', icon: '🔬' },
  { id: 'operations', name: '运营管理', icon: '⚙️' },
  { id: 'customer-service', name: '客户服务', icon: '🤝' },
  { id: 'legal', name: '法务合规', icon: '⚖️' },
  { id: 'it', name: 'IT技术', icon: '💻' },
  { id: 'administration', name: '行政管理', icon: '🏢' },
];

const WelcomeCard: React.FC<WelcomeCardProps> = ({ onRefresh }) => {
  const [functionTags, setFunctionTags] = useState<string[]>([]);
  const [isEditing, setIsEditing] = useState(false);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    loadFunctionTags();
  }, []);

  /**
   * 加载职能标签
   */
  const loadFunctionTags = async () => {
    setLoading(true);
    try {
      // 获取token
      const token = localStorage.getItem('coapis_auth_token');
      
      if (!token) {
        // 未登录，使用默认标签
        setFunctionTags(['office-collaboration', 'document-processing']);
        return;
      }

      const response = await fetch('/api/user/scene-preferences/function-tags', {
        headers: {
          'Authorization': `Bearer ${token}`
        }
      });

      if (response.ok) {
        const data = await response.json();
        setFunctionTags(data.tags || []);
      } else {
        console.error('Failed to load function tags');
        setFunctionTags([]);
      }
    } catch (error) {
      console.error('加载职能标签失败:', error);
      setFunctionTags([]);
    } finally {
      setLoading(false);
    }
  };

  /**
   * 保存职能标签
   */
  const handleSaveTags = async () => {
    setSaving(true);
    try {
      const token = localStorage.getItem('coapis_auth_token');
      
      if (!token) {
        message.warning('请先登录');
        setIsEditing(false);
        return;
      }

      const response = await fetch('/api/user/scene-preferences/function-tags', {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({ tags: functionTags })
      });

      if (response.ok) {
        message.success('保存成功');
        setIsEditing(false);
        if (onRefresh) onRefresh();
      } else {
        message.error('保存失败');
      }
    } catch (error) {
      console.error('保存职能标签失败:', error);
      message.error('保存失败');
    } finally {
      setSaving(false);
    }
  };

  /**
   * 切换标签选择
   */
  const handleToggleTag = (tagId: string) => {
    if (functionTags.includes(tagId)) {
      setFunctionTags(functionTags.filter(t => t !== tagId));
    } else {
      setFunctionTags([...functionTags, tagId]);
    }
  };

  // 获取当前选中的标签
  const selectedTags = AVAILABLE_TAGS.filter(tag => functionTags.includes(tag.id));

  return (
    <div className={styles.widget}>
      <div className={styles.widgetHeader}>
        <div className={styles.widgetTitle}>
          <span className={styles.widgetIcon}>👋</span>
          <span>欢迎回来</span>
        </div>
        {!isEditing ? (
          <button
            className={styles.editButton}
            onClick={() => setIsEditing(true)}
            style={{
              background: 'none',
              border: 'none',
              cursor: 'pointer',
              color: '#1890ff',
              fontSize: 14
            }}
          >
            <EditOutlined /> 编辑
          </button>
        ) : (
          <button
            className={styles.saveButton}
            onClick={handleSaveTags}
            disabled={saving}
            style={{
              background: 'none',
              border: 'none',
              cursor: saving ? 'not-allowed' : 'pointer',
              color: '#52c41a',
              fontSize: 14,
              opacity: saving ? 0.5 : 1
            }}
          >
            <CheckOutlined /> {saving ? '保存中...' : '保存'}
          </button>
        )}
      </div>
      <div className={styles.widgetBody}>
        {loading ? (
          <div className={styles.loadingState}>
            <div className={styles.loadingSpinner} />
          </div>
        ) : (
          <>
            <div className={styles.welcomeMessage} style={{ marginBottom: 12 }}>
              <div style={{ fontSize: 16, fontWeight: 500, marginBottom: 8 }}>
                您的职能标签
              </div>
              <div style={{ fontSize: 14, color: '#868e96' }}>
                选择标签后，系统会为您推荐相关场景
              </div>
            </div>

            {!isEditing && selectedTags.length > 0 ? (
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                {selectedTags.map(tag => (
                  <div
                    key={tag.id}
                    className={styles.tag}
                    style={{
                      padding: '4px 12px',
                      background: '#f0f0f0',
                      borderRadius: 4,
                      fontSize: 14
                    }}
                  >
                    {tag.icon} {tag.name}
                  </div>
                ))}
              </div>
            ) : isEditing ? (
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                {AVAILABLE_TAGS.map(tag => (
                  <div
                    key={tag.id}
                    onClick={() => handleToggleTag(tag.id)}
                    style={{
                      padding: '4px 12px',
                      background: functionTags.includes(tag.id) ? '#1890ff' : '#f0f0f0',
                      color: functionTags.includes(tag.id) ? '#fff' : '#000',
                      borderRadius: 4,
                      fontSize: 14,
                      cursor: 'pointer',
                      transition: 'all 0.3s'
                    }}
                  >
                    {tag.icon} {tag.name}
                  </div>
                ))}
              </div>
            ) : (
              <div style={{ color: '#868e96', fontSize: 14 }}>
                点击右上角"编辑"选择您的职能标签
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
};

export default WelcomeCard;
