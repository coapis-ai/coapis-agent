/**
 * GroupedResponseCard — 按类型分块的自定义响应卡片
 *
 * 替代默认 AgentScopeRuntimeResponseCard，将一个回复中的内容按类型分块：
 * 1. 💭 思考过程 (REASONING) — 单独一块，默认折叠
 * 2. 🔧 每个工具调用 (PLUGIN_CALL / MCP_CALL / FUNCTION_CALL) — 每个单独一块，默认折叠
 * 3. 📝 正文回复 (MESSAGE) — 单独一块，默认展开
 *
 * 支持摘要模式（hideDetails=true）：每个分块只显示摘要，点击可展开
 *
 * 通过 options.cards 注册：
 *   cards: { 'AgentScopeRuntimeResponseCard': GroupedResponseCard }
 */
import React, { useState, useMemo } from 'react';
import { Markdown } from '@agentscope-ai/chat';
import {
  CheckCircleOutlined,
  LoadingOutlined,
  RightOutlined,
  BulbOutlined,
  WarningOutlined,
} from '@ant-design/icons';
import { useChatDisplayConfig } from './SimplifiedResponseCard';
import styles from '../index.module.less';

// ---------------------------------------------------------------------------
// Types (mirror @agentscope-ai/chat internal types)
// ---------------------------------------------------------------------------

const MSG_TYPE = {
  MESSAGE: 'message',
  REASONING: 'reasoning',
  PLUGIN_CALL: 'plugin_call',
  PLUGIN_CALL_OUTPUT: 'plugin_call_output',
  MCP_CALL: 'mcp_call',
  MCP_CALL_OUTPUT: 'mcp_call_output',
  MCP_APPROVAL_REQUEST: 'mcp_approval_request',
  FUNCTION_CALL: 'function_call',
  FUNCTION_CALL_OUTPUT: 'function_call_output',
  COMPONENT_CALL: 'component_call',
  COMPONENT_CALL_OUTPUT: 'component_call_output',
  ERROR: 'error',
  HEARTBEAT: 'heartbeat',
} as const;

const RUN_STATUS = {
  CREATED: 'created',
  IN_PROGRESS: 'in_progress',
  COMPLETED: 'completed',
  CANCELED: 'canceled',
  FAILED: 'failed',
} as const;

interface ContentItem {
  type: string;
  text?: string;
  data?: Record<string, any>;
  [key: string]: any;
}

interface OutputMessage {
  id: string;
  type: string;
  content?: ContentItem[];
  status?: string;
  role?: string;
  message?: string;
  [key: string]: any;
}

interface GroupedResponseCardProps {
  data: {
    output?: OutputMessage[];
    status?: string;
    [key: string]: any;
  };
}

// ---------------------------------------------------------------------------
// Helper: check if a message is a tool input (call)
// ---------------------------------------------------------------------------
function maybeToolInput(msg: OutputMessage): boolean {
  return [MSG_TYPE.PLUGIN_CALL, MSG_TYPE.MCP_CALL, MSG_TYPE.FUNCTION_CALL, MSG_TYPE.COMPONENT_CALL].includes(msg.type as any);
}

// ---------------------------------------------------------------------------
// Helper: check if a message is a tool output
// ---------------------------------------------------------------------------
function maybeToolOutput(msg: OutputMessage): boolean {
  return [MSG_TYPE.PLUGIN_CALL_OUTPUT, MSG_TYPE.MCP_CALL_OUTPUT, MSG_TYPE.FUNCTION_CALL_OUTPUT, MSG_TYPE.COMPONENT_CALL_OUTPUT].includes(msg.type as any);
}

// ---------------------------------------------------------------------------
// Helper: check if response is still generating
// ---------------------------------------------------------------------------
function maybeGenerating(data: { status?: string }): boolean {
  return [RUN_STATUS.IN_PROGRESS, RUN_STATUS.CREATED].includes(data.status as any);
}

// ---------------------------------------------------------------------------
// Merge tool input/output messages (like @agentscope-ai/chat Builder)
// ---------------------------------------------------------------------------
function mergeToolMessages(messages: OutputMessage[]): OutputMessage[] {
  const bufferMessagesMap = new Map<string, ContentItem>();
  const resMessages: OutputMessage[] = [];

  for (const message of messages || []) {
    if (maybeToolInput(message) && message.content?.length) {
      const content = message.content[0];
      const key = content.data?.call_id || content.data?.name;
      bufferMessagesMap.set(key, content);
      resMessages.push(message);
    } else if (maybeToolOutput(message) && message.content?.length) {
      const content = message.content[0];
      const key = content.data?.call_id || content.data?.name;
      const bufferContent = bufferMessagesMap.get(key);
      if (bufferContent) {
        // Merge output into the input message
        resMessages.forEach((item, idx) => {
          if (maybeToolInput(item)) {
            const preContent = item.content?.[0];
            const preKey = preContent?.data?.call_id || preContent?.data?.name;
            if (preKey === key) {
              resMessages[idx] = {
                ...message,
                content: [...(item.content || []), content],
              };
            }
          }
        });
      }
    } else {
      resMessages.push(message);
    }
  }
  return resMessages;
}

// ---------------------------------------------------------------------------
// Group messages by type (细粒度分块)
// ---------------------------------------------------------------------------

interface MessageBlock {
  type: 'thinking' | 'tool' | 'message' | 'error';
  items: OutputMessage[];
}

function groupMessages(output: OutputMessage[]): MessageBlock[] {
  const blocks: MessageBlock[] = [];

  for (const msg of output) {
    const t = msg.type;
    
    if (t === MSG_TYPE.REASONING) {
      // 思考过程：单独一块
      blocks.push({ type: 'thinking', items: [msg] });
    } else if (maybeToolInput(msg)) {
      // 工具调用：每个单独一块
      blocks.push({ type: 'tool', items: [msg] });
    } else if (t === MSG_TYPE.MESSAGE) {
      // 正文回复：单独一块
      blocks.push({ type: 'message', items: [msg] });
    } else if (t === MSG_TYPE.ERROR) {
      // 错误：单独一块
      blocks.push({ type: 'error', items: [msg] });
    }
    // Skip OUTPUT types, HEARTBEAT — they are handled within their parent
  }

  return blocks;
}

// ---------------------------------------------------------------------------
// Tool info extraction
// ---------------------------------------------------------------------------

function getToolInfo(msg: OutputMessage) {
  const toolName = msg.content?.[0]?.data?.name || 'unknown';
  const TOOL_ICONS: Record<string, { icon: string; color: string; label: string }> = {
    execute_shell_command: { icon: '🖥️', color: '#1890ff', label: '终端' },
    read_file: { icon: '📖', color: '#52c41a', label: '读取' },
    write_file: { icon: '✏️', color: '#faad14', label: '写入' },
    edit_file: { icon: '🔧', color: '#faad14', label: '编辑' },
    grep_search: { icon: '🔍', color: '#722ed1', label: '搜索' },
    glob_search: { icon: '📁', color: '#13c2c2', label: '查找' },
    web_search: { icon: '🔎', color: '#2f54eb', label: '网页' },
    browser_use: { icon: '🌐', color: '#1677ff', label: '浏览器' },
    memory_search: { icon: '🧠', color: '#eb2f96', label: '记忆' },
    view_image: { icon: '🖼️', color: '#13c2c2', label: '图片' },
    send_file_to_user: { icon: '📤', color: '#fa8c16', label: '发送' },
    chat_with_agent: { icon: '💬', color: '#722ed1', label: '对话' },
  };
  return TOOL_ICONS[toolName] || { icon: '⚡', color: '#999', label: toolName };
}

function generateToolSummary(msg: OutputMessage): string {
  const toolName = msg.content?.[0]?.data?.name || 'unknown';
  const args = msg.content?.[0]?.data?.args;
  if (!args) return getToolInfo(msg).label;

  // Generate brief summary based on tool type
  if (toolName === 'execute_shell_command' && args.command) {
    const cmd = String(args.command);
    return cmd.length > 30 ? cmd.slice(0, 30) + '...' : cmd;
  }
  if ((toolName === 'read_file' || toolName === 'write_file') && args.file_path) {
    const path = String(args.file_path);
    const parts = path.split('/');
    return parts[parts.length - 1] || path;
  }
  if (toolName === 'grep_search' && args.pattern) {
    return `搜索 "${args.pattern}"`;
  }
  if (toolName === 'web_search' && args.query) {
    return `搜索 "${args.query}"`;
  }

  return getToolInfo(msg).label;
}

// ---------------------------------------------------------------------------
// Collapsible section component
// ---------------------------------------------------------------------------

interface CollapsibleSectionProps {
  icon: React.ReactNode;
  title: string;
  badge?: React.ReactNode;
  defaultExpanded?: boolean;
  children: React.ReactNode;
  summary?: string;
}

const CollapsibleSection: React.FC<CollapsibleSectionProps> = ({
  icon,
  title,
  badge,
  defaultExpanded = false,
  children,
  summary,
}) => {
  const config = useChatDisplayConfig();
  const [expanded, setExpanded] = useState(defaultExpanded);

  // Determine what to show in header
  const showSummaryInHeader = config.hideDetails && !expanded && summary;
  const showExpandArrow = summary && config.hideDetails;

  return (
    <div className={styles.groupedSection}>
      <div
        className={styles.groupedSectionHeader}
        onClick={() => setExpanded(!expanded)}
      >
        <div className={styles.groupedSectionTitle}>
          {icon}
          <span>{title}</span>
          {badge}
        </div>
        {showExpandArrow && (
          <RightOutlined
            className={styles.groupedSectionArrow}
            style={{ transform: expanded ? 'rotate(90deg)' : 'none' }}
          />
        )}
      </div>
      {showSummaryInHeader ? (
        <div className={styles.groupedSectionSummary} onClick={() => setExpanded(true)}>
          {summary}
        </div>
      ) : (
        expanded && <div className={styles.groupedSectionContent}>{children}</div>
      )}
    </div>
  );
};

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

const GroupedResponseCard: React.FC<GroupedResponseCardProps> = ({ data }) => {
  // Use mergeToolMessages like the original AgentScopeRuntimeResponseCard
  const messages = useMemo(() => mergeToolMessages(data.output || []), [data.output]);
  const blocks = useMemo(() => groupMessages(messages), [messages]);

  // Check if generating (like original component)
  const isGenerating = maybeGenerating(data);

  // Show spinner if no messages and still generating (like original component)
  if (!messages.length && isGenerating) {
    return (
      <div className={styles.groupedCard}>
        <div className={styles.groupedCardSpinner}>
          <LoadingOutlined style={{ fontSize: 16, color: '#999' }} />
          <span style={{ marginLeft: 8, color: '#999', fontSize: 13 }}>思考中...</span>
        </div>
      </div>
    );
  }

  if (blocks.length === 0) return null;

  return (
    <div className={styles.groupedCard}>
      {blocks.map((block, idx) => {
        // ── 思考过程（默认折叠）──
        if (block.type === 'thinking') {
          const text = block.items[0]?.content?.find((c: any) => c.type === 'text')?.text || '';
          const charCount = text.length;
          const summary = text.length <= 80 ? text : text.slice(0, 80) + '...';
          
          return (
            <CollapsibleSection
              key={`thinking-${idx}`}
              icon={<BulbOutlined style={{ color: '#722ed1', fontSize: 13 }} />}
              title="思考过程"
              badge={
                <span className={styles.groupedBadge} style={{ color: '#722ed1' }}>
                  {charCount} 字
                </span>
              }
              defaultExpanded={false}
              summary={summary}
            >
              <div className={styles.groupedContent}>
                <Markdown content={text} />
              </div>
            </CollapsibleSection>
          );
        }

        // ── 工具调用（每个单独一块，默认折叠）──
        if (block.type === 'tool') {
          const msg = block.items[0];
          const info = getToolInfo(msg);
          const toolName = msg.content?.[0]?.data?.name || 'unknown';
          const hasOutput = msg.content && msg.content.length > 1;
          const statusIcon = hasOutput ? (
            <CheckCircleOutlined style={{ color: '#52c41a', fontSize: 12 }} />
          ) : (
            <LoadingOutlined style={{ color: '#faad14', fontSize: 12 }} />
          );
          const summary = generateToolSummary(msg);
          
          return (
            <CollapsibleSection
              key={`tool-${idx}`}
              icon={<span style={{ fontSize: 14 }}>{info.icon}</span>}
              title={toolName}
              badge={statusIcon}
              defaultExpanded={false}
              summary={summary}
            >
              <div className={styles.toolItem}>
                {/* Show tool output */}
                {hasOutput && msg.content?.slice(1).map((output, oi) => (
                  <div key={`output-${oi}`} className={styles.toolOutput}>
                    {output.text && (
                      <pre style={{ 
                        margin: '4px 0', 
                        padding: '8px', 
                        background: '#f5f5f5', 
                        borderRadius: '4px',
                        fontSize: '12px',
                        overflow: 'auto',
                        maxHeight: '150px'
                      }}>
                        {output.text.slice(0, 500)}
                        {output.text.length > 500 && '...'}
                      </pre>
                    )}
                  </div>
                ))}
              </div>
            </CollapsibleSection>
          );
        }

        // ── 正文回复（默认展开）──
        if (block.type === 'message') {
          const text = block.items[0]?.content?.find((c: any) => c.type === 'text')?.text || '';
          const summary = text.length <= 200 ? text : text.slice(0, 200) + '...';
          
          return (
            <CollapsibleSection
              key={`message-${idx}`}
              icon={<span style={{ fontSize: 13 }}>📝</span>}
              title="正文回复"
              defaultExpanded={true}
              summary={summary}
            >
              <div className={styles.groupedContent}>
                <Markdown content={text} />
              </div>
            </CollapsibleSection>
          );
        }

        // ── 错误（默认展开）──
        if (block.type === 'error') {
          const errorMsg = block.items[0]?.content?.find((c: any) => c.type === 'text')?.text || block.items[0]?.message || '未知错误';
          return (
            <div key={`error-${idx}`} className={styles.errorSection}>
              <WarningOutlined style={{ color: '#ff4d4f', marginRight: 8 }} />
              <span style={{ color: '#ff4d4f' }}>{errorMsg}</span>
            </div>
          );
        }

        return null;
      })}

      {/* 如果正在生成，显示加载状态 */}
      {isGenerating && blocks.length > 0 && (
        <div className={styles.generatingIndicator}>
          <LoadingOutlined style={{ fontSize: 12, color: '#999' }} />
          <span style={{ marginLeft: 4, color: '#999', fontSize: 12 }}>正在处理...</span>
        </div>
      )}
    </div>
  );
};

export default GroupedResponseCard;
