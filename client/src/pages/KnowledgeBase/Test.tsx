/**
 * 知识库 RAG 问答测试界面 (企业版)
 * 
 * 功能：
 * - 对话输入区（用户输入问题 Query）
 * - AI 回答展示区（渲染 LLM 生成的回复内容）
 * - 溯源信息展示区（Citations / Sources，显示被召回的 Chunk 片段及来源文档）
 */

import { useState } from 'react';
import { Card, Input, Button, Space, message, Spin, Divider, Tag, List } from 'antd';
import { SendOutlined, ReloadOutlined } from '@ant-design/icons';
import { useParams } from 'react-router-dom';
import { PageHeader } from '@/components/PageHeader';
import { knowledgeApi } from '@/api/modules/knowledge';

interface SourceItem {
  chunk_id: string;
  text: string;
  source_title: string;
  score: number;
}

export default function KnowledgeTestPage() {
  const { id: kbId } = useParams<{ id: string }>();
  
  const [query, setQuery] = useState('');
  const [loading, setLoading] = useState(false);
  const [answer, setAnswer] = useState<string>('');
  const [sources, setSources] = useState<SourceItem[]>([]);

  // Handle RAG test query submission
  const handleTestQuery = async () => {
    if (!query.trim()) {
      message.warning('请输入查询问题');
      return;
    }
    
    if (!kbId) {
      message.error('知识库 ID 无效');
      return;
    }

    setLoading(true);
    setAnswer('');
    setSources([]);

    try {
      const res = await knowledgeApi.testRagQuery([kbId], query.trim(), 5);
      
      if (res.answer) {
        setAnswer(res.answer);
      } else {
        setAnswer('未获取到回答，请稍后重试。');
      }

      // Process sources/citations
      if (res.sources && res.sources.length > 0) {
        const formattedSources: SourceItem[] = res.sources.map((s: any) => ({
          chunk_id: s.chunk_id || s.id,
          text: s.text || s.content || '',
          source_title: s.source_title || s.source || '未知文档',
          score: s.score || 0,
        }));
        setSources(formattedSources);
      } else {
        message.info('未找到相关文档片段');
      }
    } catch (error) {
      console.error('RAG 测试查询失败:', error);
      message.error('查询失败，请稍后重试');
      setAnswer('查询过程中发生错误，请检查知识库配置或稍后重试。');
    } finally {
      setLoading(false);
    }
  };

  // Handle Enter key press in input
  const handleKeyPress = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleTestQuery();
    }
  };

  return (
    <div style={{ padding: 24 }}>
      <PageHeader 
        parent="知识库管理"
        current="RAG 问答测试"
        backTo="/knowledge/bases"
      />

      <Space direction="vertical" size="large" style={{ width: '100%' }}>
        {/* Query Input Card */}
        <Card title="查询输入">
          <Input.TextArea
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="请输入您想查询的问题，例如：产品的核心功能是什么？"
            rows={4}
            onPressEnter={handleKeyPress}
          />
          <div style={{ marginTop: 12, textAlign: 'right' }}>
            <Space>
              <Button icon={<ReloadOutlined />} onClick={() => { setQuery(''); setAnswer(''); setSources([]); }}>
                清空
              </Button>
              <Button 
                type="primary" 
                icon={<SendOutlined />} 
                loading={loading}
                onClick={handleTestQuery}
              >
                提交查询
              </Button>
            </Space>
          </div>
        </Card>

        {/* AI Answer & Sources Card */}
        <Card title="RAG 测试结果" loading={loading && !answer}>
          {loading && !answer ? (
            <Spin tip="正在检索知识库并生成回答..." />
          ) : (
            <>
              {/* AI Answer Display */}
              <div style={{ marginBottom: 24 }}>
                <h3>AI 回答：</h3>
                <Card size="small" style={{ backgroundColor: '#f5f5f5' }}>
                  <div style={{ whiteSpace: 'pre-wrap', lineHeight: 1.6 }}>
                    {answer || '暂无回答，请提交查询。'}
                  </div>
                </Card>
              </div>

              {/* Sources / Citations Display */}
              {sources.length > 0 && (
                <>
                  <Divider orientation="left">溯源信息 (Citations / Sources)</Divider>
                  
                  <List
                    dataSource={sources.sort((a, b) => b.score - a.score)}
                    renderItem={(source, index) => (
                      <List.Item key={source.chunk_id}>
                        <List.Item.Meta
                          title={
                            <Space>
                              <Tag color="blue">来源 {index + 1}</Tag>
                              <span>{source.source_title}</span>
                              <Tag color="green">相似度: {(source.score * 100).toFixed(1)}%</Tag>
                            </Space>
                          }
                          description={
                            <div style={{ 
                              backgroundColor: '#fafafa', 
                              padding: '8px 12px', 
                              borderRadius: '4px',
                              fontSize: '13px',
                              lineHeight: 1.5,
                              maxHeight: 100,
                              overflowY: 'auto'
                            }}>
                              {source.text}
                            </div>
                          }
                        />
                      </List.Item>
                    )}
                  />
                  
                  <div style={{ marginTop: 12, fontSize: '12px', color: '#999' }}>
                    * 提示：如果重排序服务不可用，系统已自动回退到基础相似度检索。
                  </div>
                </>
              )}

              {sources.length === 0 && answer && !loading && (
                <div style={{ textAlign: 'center', color: '#999', padding: 20 }}>
                  未找到相关文档片段，AI 可能使用了通用知识或回答“不知道”。
                </div>
              )}
            </>
          )}
        </Card>
      </Space>
    </div>
  );
}
