/**
 * GroupedResponseCard — 按类型分块的自定义响应卡片
 *
 * 替代默认 AgentScopeRuntimeResponseCard，将一个回复中的内容按类型分块：
 * 1. 💭 思考过程 (REASONING) — 进行中时展开，完成后折叠
 * 2. 🔧 每个工具调用 (PLUGIN_CALL / MCP_CALL / FUNCTION_CALL) — 默认折叠，显示输入输出
 * 3. 📝 正文回复 (MESSAGE) — 默认展开
 *
 * 通过 options.cards 注册：
 *   cards: { 'AgentScopeRuntimeResponseCard': GroupedResponseCard }
 */
import React, { useMemo } from 'react';
import { Markdown } from '@agentscope-ai/chat';
import {
  LoadingOutlined,
  RightOutlined,
  BulbOutlined,
  WarningOutlined,
  CodeOutlined,
  CheckCircleOutlined,
} from '@ant-design/icons';
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
  type?: string;
  text?: string;
  data?: Record<string, any>;
  [key: string]: any;
}

interface OutputMessage {
  id?: string;
  type?: string;
  content?: ContentItem[];
  status?: string;
  role?: string;
  message?: string;
  [key: string]: any;
}

interface GroupedResponseCardProps {
  data?: {
    output?: OutputMessage[];
    status?: string;
    [key: string]: any;
  };
}

// ---------------------------------------------------------------------------
// Helper: safely get message type
// ---------------------------------------------------------------------------
function getMessageType(msg: OutputMessage): string {
  return msg?.type || MSG_TYPE.MESSAGE;
}

// ---------------------------------------------------------------------------
// Helper: check if a message is a tool input (call)
// ---------------------------------------------------------------------------
function maybeToolInput(msg: OutputMessage): boolean {
  const type = getMessageType(msg);
  return (MSG_TYPE as Record<string, string>)[type] !== undefined && 
         ['PLUGIN_CALL', 'MCP_CALL', 'FUNCTION_CALL', 'COMPONENT_CALL'].includes(type.toUpperCase());
}

// ---------------------------------------------------------------------------
// Helper: check if a message is a tool output
// ---------------------------------------------------------------------------
function maybeToolOutput(msg: OutputMessage): boolean {
  const type = getMessageType(msg);
  return (MSG_TYPE as Record<string, string>)[type] !== undefined && 
         ['PLUGIN_CALL_OUTPUT', 'MCP_CALL_OUTPUT', 'FUNCTION_CALL_OUTPUT', 'COMPONENT_CALL_OUTPUT'].includes(type.toUpperCase());
}

// ---------------------------------------------------------------------------
// Helper: get tool name from message
// ---------------------------------------------------------------------------
function getToolName(msg: OutputMessage): string {
  try {
    const content = msg?.content as ContentItem[];
    if (Array.isArray(content) && content.length > 0 && content[0]?.data?.name) {
      return content[0].data.name;
    }
  } catch (e) {
    // ignore
  }
  return 'Unknown Tool';
}

// ---------------------------------------------------------------------------
// Thinking Block
// ---------------------------------------------------------------------------
function ThinkingBlock({ msg }: { msg: OutputMessage }) {
  try {
    const content = msg?.content as ContentItem[];
    if (!Array.isArray(content) || content.length === 0) return null;

    const text = content[0]?.text || '';
    const isInProgress = msg?.status === RUN_STATUS.IN_PROGRESS;
    const isCompleted = msg?.status === RUN_STATUS.COMPLETED || msg?.status === RUN_STATUS.CANCELED;

    // 如果已完成且没有内容，不显示
    if (isCompleted && !text) return null;

    return (
      <div className={styles.thinkingBlock}>
        <div
          className={styles.thinkingHeader}
          onClick={(e) => {
            const target = e.currentTarget.nextElementSibling as HTMLElement;
            if (target) {
              target.style.display = target.style.display === 'none' ? 'block' : 'none';
            }
          }}
        >
          <BulbOutlined style={{ color: '#faad14', marginRight: 8 }} />
          <span>Thinking</span>
          {isInProgress && <LoadingOutlined spin style={{ marginLeft: 8, color: '#faad14' }} />}
          <RightOutlined className={styles.expandIcon} />
        </div>
        <div className={styles.thinkingContent} style={{ display: isInProgress ? 'block' : 'none' }}>
          <div className={styles.thinkingText}>{text}</div>
        </div>
      </div>
    );
  } catch (e) {
    console.error('[GroupedResponseCard] ThinkingBlock error:', e);
    return null;
  }
}

// ---------------------------------------------------------------------------
// Tool Block — 自渲染，不依赖 ToolCall 组件
// ---------------------------------------------------------------------------
function ToolBlock({ msg }: { msg: OutputMessage }) {
  try {
    const content = msg?.content as ContentItem[];
    if (!Array.isArray(content) || content.length === 0) return null;

    const toolData = content[0]?.data;
    const toolName = toolData?.name || 'Unknown Tool';
    const input = toolData?.arguments;
    const output = toolData?.output;
    const isInProgress = msg?.status === RUN_STATUS.IN_PROGRESS;

    const inputStr = input ? (typeof input === 'string' ? input : JSON.stringify(input, null, 2)) : '';
    const outputStr = output ? (typeof output === 'string' ? output : JSON.stringify(output, null, 2)) : (isInProgress ? '处理中...' : '');

    return (
      <div className={styles.toolBlock}>
        <div
          className={styles.toolHeader}
          onClick={(e) => {
            const target = e.currentTarget.nextElementSibling as HTMLElement;
            if (target) {
              target.style.display = target.style.display === 'none' ? 'block' : 'none';
            }
          }}
        >
          <CodeOutlined style={{ color: '#1890ff', marginRight: 8 }} />
          <span style={{ fontWeight: 500 }}>{toolName}</span>
          {isInProgress && <LoadingOutlined spin style={{ marginLeft: 8, color: '#1890ff' }} />}
          {!isInProgress && output && <CheckCircleOutlined style={{ marginLeft: 8, color: '#52c41a' }} />}
          <RightOutlined className={styles.expandIcon} />
        </div>
        <div className={styles.toolContent} style={{ display: 'none' }}>
          {inputStr && (
            <div className={styles.toolSection}>
              <div className={styles.toolSectionTitle}>输入参数:</div>
              <pre className={styles.toolPre}>{inputStr}</pre>
            </div>
          )}
          {outputStr && (
            <div className={styles.toolSection}>
              <div className={styles.toolSectionTitle}>输出结果:</div>
              <pre className={styles.toolPre}>{outputStr}</pre>
            </div>
          )}
        </div>
      </div>
    );
  } catch (e) {
    console.error('[GroupedResponseCard] ToolBlock error:', e);
    return null;
  }
}

// ---------------------------------------------------------------------------
// Message Block
// ---------------------------------------------------------------------------
function MessageBlock({ msg }: { msg: OutputMessage }) {
  try {
    const content = msg?.content as ContentItem[];
    if (!Array.isArray(content) || content.length === 0) return null;

    const text = content[0]?.text || '';
    if (!text) return null;

    return (
      <div className={styles.messageBlock}>
        <Markdown content={text} />
      </div>
    );
  } catch (e) {
    console.error('[GroupedResponseCard] MessageBlock error:', e);
    // Fallback: show raw text
    const text = msg?.content?.[0]?.text || '';
    return (
      <div className={styles.messageBlock}>
        <pre style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>{text}</pre>
      </div>
    );
  }
}

// ---------------------------------------------------------------------------
// Error Block
// ---------------------------------------------------------------------------
function ErrorBlock({ msg }: { msg: OutputMessage }) {
  try {
    const text = msg?.message || msg?.content?.[0]?.text || 'Unknown error';
    return (
      <div className={styles.errorBlock}>
        <WarningOutlined style={{ color: '#ff4d4f', marginRight: 8 }} />
        <span>{text}</span>
      </div>
    );
  } catch (e) {
    return (
      <div className={styles.errorBlock}>
        <WarningOutlined style={{ color: '#ff4d4f', marginRight: 8 }} />
        <span>An error occurred</span>
      </div>
    );
  }
}

// ---------------------------------------------------------------------------
// Merge tool call + output pairs
// ---------------------------------------------------------------------------
function mergeToolMessages(output: OutputMessage[]): OutputMessage[] {
  if (!Array.isArray(output) || output.length === 0) return [];

  const result: OutputMessage[] = [];
  const callMap = new Map<string, OutputMessage>();

  // First pass: collect all tool calls
  for (const msg of output) {
    if (maybeToolInput(msg)) {
      const toolName = getToolName(msg);
      callMap.set(`${msg?.id}_${toolName}`, msg);
    }
  }

  // Second pass: merge outputs with calls
  for (const msg of output) {
    if (maybeToolOutput(msg)) {
      // Find corresponding call and merge
      for (const [, callMsg] of callMap.entries()) {
        if (callMsg?.id === msg?.id || callMsg?.id === msg?.id?.replace('_output', '')) {
          // Merge output into call
          const mergedContent = [...(callMsg.content || [])];
          if (Array.isArray(msg.content) && msg.content.length > 0) {
            mergedContent.push(msg.content[0]);
          }
          callMsg.content = mergedContent;
          callMsg.status = msg.status;
          break;
        }
      }
    }
  }

  // Collect merged calls and other message types
  for (const msg of output) {
    if (maybeToolInput(msg)) {
      result.push(msg);
    } else {
      const type = getMessageType(msg);
      if (
        type === MSG_TYPE.MESSAGE ||
        type === MSG_TYPE.REASONING ||
        type === MSG_TYPE.ERROR
      ) {
        result.push(msg);
      }
    }
  }

  return result;
}

// ---------------------------------------------------------------------------
// Main Component
// ---------------------------------------------------------------------------
const GroupedResponseCard = React.memo(function GroupedResponseCard({
  data,
}: GroupedResponseCardProps) {
  // Handle null/undefined data
  if (!data) return null;

  const output = data?.output || [];
  const status = data?.status;
  const isGenerating = status === 'in_progress';

  // Merge tool messages
  const mergedMessages = useMemo(() => {
    try {
      return mergeToolMessages(output);
    } catch (e) {
      console.error('[GroupedResponseCard] mergeToolMessages error:', e);
      return Array.isArray(output) ? output : [];
    }
  }, [output]);

  // Filter out heartbeat messages
  const messages = useMemo(
    () => {
      if (!Array.isArray(mergedMessages)) return [];
      return mergedMessages.filter((msg) => getMessageType(msg) !== MSG_TYPE.HEARTBEAT);
    },
    [mergedMessages]
  );

  // Empty state - no messages yet
  if (!messages.length && isGenerating) {
    return (
      <div className={styles.messageBlock}>
        <LoadingOutlined spin style={{ marginRight: 8 }} />
        <span>正在思考...</span>
      </div>
    );
  }

  // No messages and not generating - don't render
  if (!messages.length) return null;

  return (
    <>
      {messages.map((msg, index) => {
        try {
          const type = getMessageType(msg);
          const key = msg?.id || `msg_${index}`;
          
          switch (type) {
            case MSG_TYPE.REASONING:
              return <ThinkingBlock key={key} msg={msg} />;
            case MSG_TYPE.PLUGIN_CALL:
            case MSG_TYPE.MCP_CALL:
            case MSG_TYPE.FUNCTION_CALL:
            case MSG_TYPE.COMPONENT_CALL:
              return <ToolBlock key={key} msg={msg} />;
            case MSG_TYPE.MESSAGE:
              return <MessageBlock key={key} msg={msg} />;
            case MSG_TYPE.ERROR:
              return <ErrorBlock key={key} msg={msg} />;
            default:
              // Unknown type, try to render as message
              if (msg?.content?.[0]?.text) {
                return <MessageBlock key={key} msg={msg} />;
              }
              return null;
          }
        } catch (e) {
          console.error('[GroupedResponseCard] Render message error:', e, msg);
          return null;
        }
      })}
    </>
  );
});

export default GroupedResponseCard;
