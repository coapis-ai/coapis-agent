/**
 * C2ACardRenderer — C2A 协议卡片渲染器
 *
 * 负责渲染后端发送的 type="c2a_protocol" 消息。
 * 支持：
 * - text_markdown
 * - data_table（含 row_actions）
 * - suggestions（快捷操作）
 *
 * 通过 customCardRenderConfig 注册到 AgentScopeRuntimeWebUI。
 */
import React, { useMemo } from 'react';
import { Button, Tag, Table, Space, Typography, message } from 'antd';
import { EyeOutlined } from '@ant-design/icons';
import ReactMarkdown from 'react-markdown';
import styles from '../index.module.less';

const { Text } = Typography;

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface C2AAction {
  action_id: string;
  label: string;
  suggestion_id?: string;
  type?: string;
  style?: string;
  url_template?: string;
  params_mapping?: Record<string, string>;
  business_intent?: string;
  context_data?: Record<string, unknown>;
}

interface C2ABlock {
  block_id?: string;
  type: string;
  content: Record<string, unknown>;
}

interface C2APayload {
  protocol_version?: string;
  message_id?: string;
  context_ref?: Record<string, unknown>;
  metadata?: Record<string, unknown>;
  blocks: C2ABlock[];
  actions?: C2AAction[];
  suggestions?: C2AAction[];
  state?: Record<string, unknown>;
}

interface C2ACardRendererProps {
  data: {
    content?: Array<{
      type: string;
      data?: C2APayload;
      text?: string;
      [key: string]: unknown;
    }>;
    metadata?: Record<string, unknown>;
    [key: string]: unknown;
  };
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function extractC2APayload(content: unknown): C2APayload | null {
  if (!Array.isArray(content)) return null;
  const block = content.find((c: any) => c?.type === 'c2a_protocol' && c?.data);
  if (!block) return null;
  return (block.data as C2APayload) || null;
}

function renderMarkdownText(text: string): React.ReactNode {
  return <ReactMarkdown>{text}</ReactMarkdown>;
}

function renderDataTable(block: C2ABlock): React.ReactNode {
  const content = block.content || {};
  // Support both formats: {data: {headers, rows}} and direct {headers, rows}
  const data = (content.data as any) || content;
  const headers: string[] = data.headers || [];
  const rows: string[][] = data.rows || [];
  const rowActions = (data.row_actions as Record<string, C2AAction>) || {};

  // Separate row_link (inline hyperlink) from button-style actions
  const linkActions: Record<string, C2AAction> = {};
  const buttonActions: Record<string, C2AAction> = {};
  
  Object.entries(rowActions).forEach(([key, action]) => {
    if (action.style === 'link') {
      linkActions[key] = action;
    } else {
      buttonActions[key] = action;
    }
  });

  const columns = headers.map((header, idx) => ({
    title: header,
    dataIndex: `col_${idx}`,
    key: `col_${idx}`,
    render: (_text: unknown, _record: Record<string, unknown>) => {
      const value = _record[`col_${idx}`] || '';
      
      // Check if any link-style action applies to this cell
      const linkActionKeys = Object.keys(linkActions);
      if (linkActionKeys.length > 0) {
        const actionKey = linkActionKeys[0];
        const action = linkActions[actionKey];
        if (action?.url_template) {
          const url = action.url_template.replace(/\{(\w+)\}/g, (_, key) => {
            return String(_record[key] || `{${key}}`);
          });
          return (
            <a href={url} target="_blank" rel="noopener noreferrer">
              {String(value)}
            </a>
          );
        }
      }
      
      return <span>{String(value)}</span>;
    },
  }));

  const tableData = rows.map((row, idx) => {
    const obj: Record<string, unknown> = { key: idx };
    row.forEach((cell, cellIdx) => {
      obj[`col_${cellIdx}`] = cell;
    });
    return obj;
  });

  const hasButtonActions = Object.keys(buttonActions).length > 0;

  return (
    <div>
      <Table columns={columns} dataSource={tableData} pagination={false} size="small" bordered />
      {hasButtonActions && (
        <Space className={styles.c2aRowActions} style={{ marginTop: 8 }}>
          {Object.entries(buttonActions).map(([key, action]) => (
            <Button
              key={key}
              size="small"
              type="primary"
              icon={<EyeOutlined />}
              onClick={() => {
                if (action.url_template) {
                  const firstRow = rows[0] || [];
                  const url = action.url_template.replace(/\{(\w+)\}/g, (_, k) => {
                    const params: Record<string, string> = {};
                    headers.forEach((h, i) => {
                      params[h] = String(firstRow[i] || '');
                    });
                    return params[k] || `{${k}}`;
                  });
                  window.open(url, '_blank');
                } else {
                  message.info(String(action.label));
                }
              }}
            >
              {action.label}
            </Button>
          ))}
        </Space>
      )}
    </div>
  );
}

function renderSuggestions(suggestions: C2AAction[]): React.ReactNode {
  if (!suggestions || suggestions.length === 0) return null;
  return (
    <div className={styles.c2aSuggestions}>
      {suggestions.map((sug, idx) => {
        // Handle standard action types
        const isExport = sug.business_intent === 'export_list_to_excel' || sug.label.includes('导出');
        const isMore = sug.business_intent === 'open_full_list' || sug.label.includes('更多');
        
        return (
          <Button
            key={sug.suggestion_id || sug.action_id || idx}
            size="small"
            onClick={() => {
              // For export_list with url_template, trigger download/navigation
              if (isExport && sug.context_data && (sug.context_data as any).url_template) {
                const url = String((sug.context_data as any).url_template);
                window.open(url, '_blank');
                return;
              }
              // For more with url_template, open full list page
              if (isMore && sug.context_data && (sug.context_data as any).url_template) {
                const url = String((sug.context_data as any).url_template);
                window.open(url, '_blank');
                return;
              }
              // Default: show intent or label as info
              if (sug.context_data) {
                message.info(String(sug.business_intent));
              } else {
                message.info(String(sug.label));
              }
            }}
          >
            {sug.label}
          </Button>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// C2ACardRenderer
// ---------------------------------------------------------------------------

const C2ACardRenderer: React.FC<C2ACardRendererProps> = ({ data }) => {

  const payload = useMemo(() => extractC2APayload(data.content), [data.content]);
  if (!payload) return null;

  const blocks = payload.blocks || [];
  const actions = payload.actions || [];
  const suggestions = payload.suggestions || [];

  // 如果没有任何 blocks，返回 null
  if (blocks.length === 0 && actions.length === 0 && suggestions.length === 0) {
    return null;
  }

  return (
    <div className={styles.c2aCard}>
      {payload.metadata?.source_system ? (
        <div className={styles.c2aHeader}>
          <Tag color="blue">{String(payload.metadata.source_system)}</Tag>
          {payload.message_id && (
            <Text type="secondary" style={{ fontSize: 12 }}>
              {payload.message_id}
            </Text>
          )}
        </div>
      ) : null}

      {blocks.map((block) => {
        if (block.type === 'text_markdown') {
          const text = (block.content as any).text || '';
          return (
            <div key={block.block_id || Math.random()} className={styles.c2aTextBlock}>
              {renderMarkdownText(text)}
            </div>
          );
        }

        if (block.type === 'data_table') {
          return (
            <div key={block.block_id || Math.random()} className={styles.c2aTableBlock}>
              {renderDataTable(block)}
            </div>
          );
        }

        // 未知块类型，降级显示 JSON
        return (
          <pre key={block.block_id || Math.random()} className={styles.c2aUnknownBlock}>
            {JSON.stringify(block, null, 2)}
          </pre>
        );
      })}

      {suggestions.length > 0 && (
        <div className={styles.c2aSuggestionsBlock}>
          {renderSuggestions(suggestions)}
        </div>
      )}

      {/* 渲染卡片级 actions（如"查看详情"按钮） */}
      {actions.length > 0 && (
        <div className={styles.c2aActionsBlock}>
          <Space className={styles.c2aActions} style={{ marginTop: 8 }}>
            {actions.map((action, idx) => (
              <Button
                key={action.action_id || action.suggestion_id || idx}
                size="small"
                type="primary"
                icon={<EyeOutlined />}
                onClick={() => {
                  if (action.url_template) {
                    const url = action.url_template.replace(/\{(\w+)\}/g, (_, k) => {
                      // 尝试从 context_data 中替换参数
                      if (action.context_data && action.context_data[k]) {
                        return String(action.context_data[k]);
                      }
                      return `{${k}}`;
                    });
                    window.open(url, '_blank');
                  } else if (action.context_data) {
                    message.info(String(action.business_intent || action.label));
                  } else {
                    message.info(String(action.label));
                  }
                }}
              >
                {action.label}
              </Button>
            ))}
          </Space>
        </div>
      )}
    </div>
  );
};

export default C2ACardRenderer;
