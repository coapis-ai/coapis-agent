/**
 * GroupedResponseCard — 按类型分组的自定义响应卡片
 *
 * 替代默认 AgentScopeRuntimeResponseCard，将一个回复中的内容按类型分组：
 * 1. 💭 思考过程 (REASONING) — 默认折叠
 * 2. 🔧 执行步骤 (TOOL_CALL / MCP_CALL) — 默认折叠，显示工具名+状态
 * 3. 📝 正文回复 (MESSAGE) — 默认展开，完整 Markdown
 *
 * 通过 options.cards 注册：
 *   cards: { 'AgentScopeRuntimeResponseCard': GroupedResponseCard }
 */
import React, { useState, useMemo, useEffect } from 'react';
import { Markdown } from '@agentscope-ai/chat';
import {
  CheckCircleOutlined,
  LoadingOutlined,
  RightOutlined,
  BulbOutlined,
  ToolOutlined,
  WarningOutlined,
} from '@ant-design/icons';
import { Avatar, Flex } from 'antd';
import { useChatAnywhereOptions } from '@agentscope-ai/chat/lib/AgentScopeRuntimeWebUI/core/Context/ChatAnywhereOptionsContext';
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
// 分组逻辑
// ---------------------------------------------------------------------------

interface MessageGroup {
  type: 'thinking' | 'tools' | 'message' | 'error';
  items: OutputMessage[];
}

function groupMessages(output: OutputMessage[]): MessageGroup[] {
  const groups: MessageGroup[] = [];
  let currentTools: OutputMessage[] = [];

  const flushTools = () => {
    if (currentTools.length > 0) {
      groups.push({ type: 'tools', items: [...currentTools] });
      currentTools = [];
    }
  };

  for (const msg of output) {
    const t = msg.type;
    if (t === MSG_TYPE.REASONING) {
      flushTools();
      groups.push({ type: 'thinking', items: [msg] });
    } else if (
      t === MSG_TYPE.PLUGIN_CALL ||
      t === MSG_TYPE.MCP_CALL ||
      t === MSG_TYPE.FUNCTION_CALL ||
      t === MSG_TYPE.COMPONENT_CALL
    ) {
      currentTools.push(msg);
    } else if (t === MSG_TYPE.MESSAGE) {
      flushTools();
      groups.push({ type: 'message', items: [msg] });
    } else if (t === MSG_TYPE.ERROR) {
      flushTools();
      groups.push({ type: 'error', items: [msg] });
    }
    // Skip OUTPUT types, HEARTBEAT — they are handled within their parent
  }

  flushTools();
  return groups;
}

// ---------------------------------------------------------------------------
// 工具信息提取
// ---------------------------------------------------------------------------

function getToolInfo(msg: OutputMessage): {
  name: string;
  icon: string;
  color: string;
  label: string;
  loading: boolean;
} {
  const content = msg.content || [];
  const first = content[0];
  const toolName = first?.data?.name || 'unknown';

  // Simplified tool category mapping
  const TOOL_ICONS: Record<string, { icon: string; color: string; label: string }> = {
    execute_shell_command: { icon: '🖥️', color: '#8c8c8c', label: '命令' },
    read_file: { icon: '📄', color: '#1890ff', label: '读取' },
    write_file: { icon: '✏️', color: '#52c41a', label: '写入' },
    edit_file: { icon: '✏️', color: '#faad14', label: '编辑' },
    grep_search: { icon: '🔍', color: '#1890ff', label: '搜索' },
    glob_search: { icon: '📁', color: '#1890ff', label: '搜索' },
    browser_use: { icon: '🌐', color: '#722ed1', label: '浏览器' },
    web_search: { icon: '🌐', color: '#722ed1', label: '搜索' },
    memory_search: { icon: '🧠', color: '#eb2f96', label: '记忆' },
    view_image: { icon: '🖼️', color: '#13c2c2', label: '图片' },
    send_file_to_user: { icon: '📤', color: '#fa8c16', label: '发送' },
    chat_with_agent: { icon: '🤖', color: '#1677ff', label: 'Agent' },
  };

  const cat = TOOL_ICONS[toolName] || { icon: '⚙️', color: '#595959', label: '工具' };
  return {
    name: toolName,
    icon: cat.icon,
    color: cat.color,
    label: cat.label,
    loading: msg.status === RUN_STATUS.IN_PROGRESS,
  };
}

// ---------------------------------------------------------------------------
// 折叠区段组件
// ---------------------------------------------------------------------------

interface SectionProps {
  icon: React.ReactNode;
  title: string;
  badge?: React.ReactNode;
  defaultOpen?: boolean;
  accentColor: string;
  children: React.ReactNode;
  generating?: boolean;
}

const CollapsibleSection: React.FC<SectionProps> = ({
  icon,
  title,
  badge,
  defaultOpen = false,
  accentColor,
  children,
  generating,
}) => {
  const [open, setOpen] = useState(defaultOpen);

  // Generate 时自动展开
  useEffect(() => {
    if (generating) setOpen(true);
  }, [generating]);

  return (
    <div className={styles.groupedSection} style={{ borderLeftColor: accentColor }}>
      <div
        className={styles.groupedSectionHeader}
        onClick={() => setOpen(!open)}
      >
        <div className={styles.groupedSectionHeaderLeft}>
          {icon}
          <span className={styles.groupedSectionTitle}>{title}</span>
          {badge}
          {generating && (
            <LoadingOutlined style={{ color: accentColor, fontSize: 12 }} />
          )}
        </div>
        <RightOutlined
          className={styles.groupedSectionArrow}
          style={{ transform: open ? 'rotate(90deg)' : 'rotate(0deg)' }}
        />
      </div>
      {open && (
        <div className={styles.groupedSectionBody}>
          {children}
        </div>
      )}
    </div>
  );
};

// ---------------------------------------------------------------------------
// 思考内容渲染
// ---------------------------------------------------------------------------

const ThinkingContent: React.FC<{ msg: OutputMessage }> = ({ msg }) => {
  const text = msg.content?.find((c) => c.type === 'text')?.text || '';
  if (!text) return null;
  return (
    <div className={styles.groupedThinkingContent}>
      <Markdown content={text} />
    </div>
  );
};

// ---------------------------------------------------------------------------
// 工具卡片渲染（精简版 inline 显示）
// ---------------------------------------------------------------------------

const ToolInline: React.FC<{ msg: OutputMessage }> = ({ msg }) => {
  const info = getToolInfo(msg);
  const inputStr = msg.content?.[0]?.data?.arguments;
  const serverLabel = msg.content?.[0]?.data?.server_label;

  // 解析输入以生成摘要
  const summary = useMemo(() => {
    if (!inputStr) return info.name;
    try {
      const obj = typeof inputStr === 'string' ? JSON.parse(inputStr) : inputStr;
      // 简单摘要
      const keys = Object.keys(obj);
      if (keys.length === 0) return info.name;
      const firstVal = obj[keys[0]];
      if (typeof firstVal === 'string' && firstVal.length > 0) {
        const short = firstVal.length > 60 ? firstVal.slice(0, 60) + '...' : firstVal;
        return short;
      }
      return info.name;
    } catch {
      return info.name;
    }
  }, [inputStr, info.name]);

  return (
    <div className={styles.toolInline}>
      <div className={styles.toolInlineHeader}>
        <span style={{ fontSize: 14 }}>{info.icon}</span>
        <span className={styles.toolInlineName}>
          {serverLabel ? `${serverLabel} / ` : ''}{info.name}
        </span>
        {info.loading ? (
          <LoadingOutlined style={{ color: info.color, fontSize: 11 }} />
        ) : (
          <CheckCircleOutlined style={{ color: '#52c41a', fontSize: 11 }} />
        )}
      </div>
      <div className={styles.toolInlineSummary}>
        {summary !== info.name ? summary : ''}
      </div>
    </div>
  );
};

// ---------------------------------------------------------------------------
// GroupedResponseCard 主组件
// ---------------------------------------------------------------------------

const GroupedResponseCard: React.FC<GroupedResponseCardProps> = ({ data }) => {
  const output = data.output || [];

  const avatar = useChatAnywhereOptions((v: any) => v.welcome?.avatar);
  const nick = useChatAnywhereOptions((v: any) => v.welcome?.nick);

  // 分组
  const groups = useMemo(() => groupMessages(output), [output]);

  // 如果没有任何内容但还在生成，显示 spinner
  if (groups.length === 0 && data.status === 'in_progress') {
    return (
      <div className={styles.groupedCard}>
        <div className={styles.groupedCardSpinner}>
          <LoadingOutlined style={{ fontSize: 16, color: '#999' }} />
          <span style={{ marginLeft: 8, color: '#999', fontSize: 13 }}>思考中...</span>
        </div>
      </div>
    );
  }

  if (groups.length === 0) return null;

  // Check if there are any active reasoning/tool steps
  const hasGeneratingReasoning = output.some(
    (m) => m.type === MSG_TYPE.REASONING && m.status === RUN_STATUS.IN_PROGRESS,
  );

  return (
    <div className={styles.groupedCard}>
      {/* 头像行 */}
      {avatar && (
        <Flex align="center" gap={8} style={{ marginBottom: 8 }}>
          <Avatar src={avatar} />
          {nick && <span style={{ fontSize: 13, color: '#999' }}>{nick}</span>}
        </Flex>
      )}

      {groups.map((group, idx) => {
        // ── 思考区 ──
        if (group.type === 'thinking') {
          const text = group.items[0]?.content?.find((c: any) => c.type === 'text')?.text || '';
          const charCount = text.length;
          return (
            <CollapsibleSection
              key={`thinking-${idx}`}
              icon={<BulbOutlined style={{ color: '#722ed1', fontSize: 13 }} />}
              title="思考过程"
              badge={
                charCount > 0 ? (
                  <span className={styles.groupedBadge} style={{ color: '#722ed1' }}>
                    {charCount} 字
                  </span>
                ) : undefined
              }
              defaultOpen={false}
              accentColor="#722ed1"
              generating={hasGeneratingReasoning}
            >
              {group.items.map((item) => (
                <ThinkingContent key={item.id} msg={item} />
              ))}
            </CollapsibleSection>
          );
        }

        // ── 工具区 ──
        if (group.type === 'tools') {
          const toolItems = group.items;
          const activeCount = toolItems.filter(
            (m) => m.status === RUN_STATUS.IN_PROGRESS,
          ).length;

          return (
            <CollapsibleSection
              key={`tools-${idx}`}
              icon={<ToolOutlined style={{ color: '#1890ff', fontSize: 13 }} />}
              title="执行步骤"
              badge={
                <span className={styles.groupedBadge} style={{ color: '#1890ff' }}>
                  {activeCount > 0
                    ? `${activeCount} 进行中 / ${toolItems.length} 步`
                    : `${toolItems.length} 步`}
                </span>
              }
              defaultOpen={false}
              accentColor="#1890ff"
              generating={activeCount > 0}
            >
              {toolItems.map((item) => (
                <ToolInline key={item.id} msg={item} />
              ))}
            </CollapsibleSection>
          );
        }

        // ── 正文区 ──
        if (group.type === 'message') {
          return (
            <div key={`message-${idx}`} className={styles.groupedMessage}>
              {group.items.map((item) => {
                const textParts = (item.content || [])
                  .filter((c: any) => c.type === 'text')
                  .map((c: any) => c.text || '')
                  .filter(Boolean);
                if (textParts.length === 0) return null;
                return (
                  <Markdown
                    key={item.id}
                    content={textParts.join('\n')}
                  />
                );
              })}
            </div>
          );
        }

        // ── 错误区 ──
        if (group.type === 'error') {
          return (
            <div key={`error-${idx}`} className={styles.groupedError}>
              <WarningOutlined style={{ color: '#ff4d4f', marginRight: 6 }} />
              {group.items.map((item) => item.message || '').filter(Boolean).join(', ')}
            </div>
          );
        }

        return null;
      })}
    </div>
  );
};

export default GroupedResponseCard;
