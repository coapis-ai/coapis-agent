/**
 * GroupedResponseCard — 按类型分块的自定义响应卡片
 *
 * 替代默认 AgentScopeRuntimeResponseCard，将一个回复中的内容按类型分块：
 * 1. 💭 思考过程 (REASONING) — 进行中时展开，完成后默认折叠，点击可展开
 * 2. 🔧 每个工具调用 (PLUGIN_CALL / MCP_CALL / FUNCTION_CALL) — 默认折叠，显示名称、输入、输出
 * 3. 📝 正文回复 (MESSAGE) — 默认展开
 *
 * 数据格式（对齐 qwenpaw agentscope_msg_to_message 输出）：
 *   reasoning:        content = [{ type: "text", text: "..." }]
 *   plugin_call:      content = [{ type: "data", data: { call_id, name, arguments } }]
 *   plugin_call_output: content = [{ type: "data", data: { call_id, name, output } }]
 *   message:          content = [{ type: "text", text: "..." }]
 */
import { useMemo, useState, useCallback } from 'react';
import { Markdown } from '@agentscope-ai/chat';
import {
  LoadingOutlined,
  RightOutlined,
  DownOutlined,
  BulbOutlined,
  WarningOutlined,
  CodeOutlined,
  CheckCircleOutlined,
} from '@ant-design/icons';
import styles from '../index.module.less';

// ---------------------------------------------------------------------------
// Types
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
  thinking?: string;
  data?: Record<string, any>;
  name?: string;
  input?: Record<string, any>;
  arguments?: Record<string, any>;
  output?: any;
  id?: string;
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
// Helpers
// ---------------------------------------------------------------------------

function getMessageType(msg: OutputMessage): string {
  return msg?.type || MSG_TYPE.MESSAGE;
}

function isToolCallType(type: string): boolean {
  return [
    MSG_TYPE.PLUGIN_CALL, MSG_TYPE.MCP_CALL,
    MSG_TYPE.FUNCTION_CALL, MSG_TYPE.COMPONENT_CALL,
  ].includes(type as any);
}

function isToolOutputType(type: string): boolean {
  return [
    MSG_TYPE.PLUGIN_CALL_OUTPUT, MSG_TYPE.MCP_CALL_OUTPUT,
    MSG_TYPE.FUNCTION_CALL_OUTPUT, MSG_TYPE.COMPONENT_CALL_OUTPUT,
  ].includes(type as any);
}

/**
 * Extract tool name from a tool call message.
 * Data format: content[0] = { type: "data", data: { call_id, name, arguments } }
 * Fallback: content[0].name (legacy flat format)
 */
function getToolName(msg: OutputMessage): string {
  try {
    const c = msg?.content?.[0];
    if (!c) return 'Unknown Tool';
    // qwenpaw format: data nested
    if (c.data?.name) return c.data.name;
    // legacy flat format
    if (c.name) return c.name;
    // Legacy tool_use block
    if (c.type === 'tool_use' && c.name) return c.name;
  } catch { /* ignore */ }
  return 'Unknown Tool';
}

/**
 * Extract tool call_id from a tool call/output message.
 * Used for matching calls with outputs.
 */
function getCallId(msg: OutputMessage): string {
  try {
    const c = msg?.content?.[0];
    if (!c) return '';
    return c.data?.call_id || c.id || '';
  } catch { /* ignore */ }
  return '';
}

/**
 * Extract tool input (arguments) from a tool call message.
 */
function getToolInput(msg: OutputMessage): any {
  const c = msg?.content?.[0];
  if (!c) return null;
  return c.data?.arguments ?? c.arguments ?? c.input ?? c.data?.input ?? null;
}

/**
 * Extract tool output from a tool result message.
 */
function getToolOutput(msg: OutputMessage): any {
  const c = msg?.content?.[0];
  if (!c) return null;
  return c.data?.output ?? c.output ?? c.data?.result ?? null;
}

/** Format any value to displayable string */
function formatValue(val: any): string {
  if (val == null) return '';
  if (typeof val === 'string') return val;
  try { return JSON.stringify(val, null, 2); } catch { return String(val); }
}

/** Extract text from output (handles arrays of content items) */
function extractOutputText(output: any): string {
  if (!output) return '';
  if (typeof output === 'string') return output;
  if (Array.isArray(output)) {
    return output.map((item: any) => {
      if (typeof item === 'string') return item;
      if (item?.text) return item.text;
      if (item?.content) return item.content;
      return JSON.stringify(item);
    }).join('\n');
  }
  return formatValue(output);
}

// ---------------------------------------------------------------------------
// Thinking Block — 用 state 管理折叠，默认折叠已完成的
// ---------------------------------------------------------------------------
function ThinkingBlock({ msg }: { msg: OutputMessage }) {
  const content = msg?.content;
  if (!Array.isArray(content) || content.length === 0) return null;

  // qwenpaw format: content = [{ type: "text", text: "..." }]
  // Legacy format:   content = [{ type: "thinking", thinking: "..." }]
  const text = content[0]?.text || content[0]?.thinking || '';
  const isInProgress = msg?.status === RUN_STATUS.IN_PROGRESS;
  const isCompleted = msg?.status === RUN_STATUS.COMPLETED || msg?.status === RUN_STATUS.CANCELED;

  // 完成且无内容不显示
  if (isCompleted && !text) return null;

  // 进行中默认展开，完成后默认折叠
  const [expanded, setExpanded] = useState(isInProgress);
  const toggle = useCallback(() => setExpanded(v => !v), []);

  return (
    <div className={styles.thinkingBlock}>
      <div className={styles.thinkingHeader} onClick={toggle}>
        <BulbOutlined style={{ color: '#faad14', marginRight: 8 }} />
        <span>思考过程</span>
        {isInProgress && <LoadingOutlined spin style={{ marginLeft: 8, color: '#faad14' }} />}
        {expanded
          ? <DownOutlined className={styles.expandIcon} />
          : <RightOutlined className={styles.expandIcon} />
        }
      </div>
      {expanded && (
        <div className={styles.thinkingContent}>
          <div className={styles.thinkingText}>{text}</div>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Tool Block — 显示工具名称、输入参数、输出结果
// ---------------------------------------------------------------------------
function ToolBlock({ msg }: { msg: OutputMessage }) {
  const toolName = getToolName(msg);
  const input = getToolInput(msg);
  const output = getToolOutput(msg);
  const isInProgress = msg?.status === RUN_STATUS.IN_PROGRESS;

  const inputStr = formatValue(input);
  const outputText = extractOutputText(output);

  // 默认折叠
  const [expanded, setExpanded] = useState(false);
  const toggle = useCallback(() => setExpanded(v => !v), []);

  return (
    <div className={styles.toolBlock}>
      <div className={styles.toolHeader} onClick={toggle}>
        <CodeOutlined style={{ color: '#1890ff', marginRight: 8 }} />
        <span style={{ fontWeight: 500 }}>{toolName}</span>
        {inputStr && (
          <span style={{ color: '#999', marginLeft: 8, fontSize: 12 }}>
            {inputStr.length > 60 ? inputStr.slice(0, 60) + '...' : inputStr}
          </span>
        )}
        {isInProgress && <LoadingOutlined spin style={{ marginLeft: 8, color: '#1890ff' }} />}
        {!isInProgress && (output != null) && <CheckCircleOutlined style={{ marginLeft: 8, color: '#52c41a' }} />}
        {expanded
          ? <DownOutlined className={styles.expandIcon} />
          : <RightOutlined className={styles.expandIcon} />
        }
      </div>
      {expanded && (
        <div className={styles.toolContent}>
          {inputStr && (
            <div className={styles.toolSection}>
              <div className={styles.toolSectionTitle}>输入参数:</div>
              <pre className={styles.toolPre}>{inputStr}</pre>
            </div>
          )}
          {outputText && (
            <div className={styles.toolSection}>
              <div className={styles.toolSectionTitle}>输出结果:</div>
              <div className={styles.toolPre}><Markdown content={outputText} /></div>
            </div>
          )}
          {isInProgress && !outputText && (
            <div className={styles.toolSection}>
              <div style={{ color: '#999' }}><LoadingOutlined spin style={{ marginRight: 8 }} />处理中...</div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Message Block
// ---------------------------------------------------------------------------
function MessageBlock({ msg }: { msg: OutputMessage }) {
  const content = msg?.content;
  if (!Array.isArray(content) || content.length === 0) return null;

  // 可能有多个 text block，合并
  const text = content
    .filter(c => c.type === 'text' || c.text)
    .map(c => c.text || '')
    .filter(Boolean)
    .join('\n');

  if (!text) return null;

  return (
    <div className={styles.messageBlock}>
      <Markdown content={text} />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Error Block
// ---------------------------------------------------------------------------
function ErrorBlock({ msg }: { msg: OutputMessage }) {
  const text = msg?.message || msg?.content?.[0]?.text || 'Unknown error';
  return (
    <div className={styles.errorBlock}>
      <WarningOutlined style={{ color: '#ff4d4f', marginRight: 8 }} />
      <span>{text}</span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Merge tool call + output pairs using call_id
// ---------------------------------------------------------------------------
function mergeToolMessages(output: OutputMessage[]): OutputMessage[] {
  if (!Array.isArray(output) || output.length === 0) return [];

  const result: OutputMessage[] = [];
  // Index tool calls by call_id and tool name
  const callByIdMap = new Map<string, OutputMessage>();
  const callByNameMap = new Map<string, OutputMessage>();

  for (const msg of output) {
    if (isToolCallType(getMessageType(msg))) {
      const callId = getCallId(msg);
      const toolName = getToolName(msg);
      if (callId) callByIdMap.set(callId, msg);
      if (toolName && toolName !== 'Unknown Tool') {
        callByNameMap.set(toolName, msg);
      }
    }
  }

  // Merge outputs into calls
  const mergedCallIds = new Set<string>();
  for (const msg of output) {
    if (isToolOutputType(getMessageType(msg))) {
      const callId = getCallId(msg);
      const toolName = msg?.content?.[0]?.data?.name || getToolName(msg);

      // Find matching call
      let callMsg = (callId && callByIdMap.get(callId)) || undefined;
      if (!callMsg && toolName && toolName !== 'Unknown Tool') {
        callMsg = callByNameMap.get(toolName);
      }

      if (callMsg) {
        // Merge: attach output data to the call message
        const outputData = getToolOutput(msg);
        if (outputData != null && callMsg.content?.[0]) {
          // Store output in the call's data for ToolBlock to read
          if (!callMsg.content[0].data) callMsg.content[0].data = {};
          callMsg.content[0].data.output = outputData;
        }
        // Update status
        if (msg.status) callMsg.status = msg.status;
        mergedCallIds.add(callId || toolName);
      } else {
        // No matching call found — render as standalone output
        result.push(msg);
      }
    }
  }

  // Collect all messages in order: calls, then reasoning, then messages
  for (const msg of output) {
    const type = getMessageType(msg);
    if (isToolCallType(type)) {
      result.push(msg);
    } else if (!isToolOutputType(type)) {
      result.push(msg);
    }
    // Tool outputs that were merged are skipped; standalone ones already added above
  }

  return result;
}

// ---------------------------------------------------------------------------
// Main Component
// ---------------------------------------------------------------------------
function GroupedResponseCard({ data }: GroupedResponseCardProps) {
  if (!data) return null;

  const output = data?.output || [];
  const status = data?.status;
  const isGenerating = status === 'in_progress';

  const mergedMessages = useMemo(() => {
    try {
      return mergeToolMessages(output);
    } catch (e) {
      console.error('[GroupedResponseCard] mergeToolMessages error:', e);
      return Array.isArray(output) ? output : [];
    }
  }, [output]);

  const messages = useMemo(
    () => (Array.isArray(mergedMessages) ? mergedMessages : []).filter(
      (msg) => getMessageType(msg) !== MSG_TYPE.HEARTBEAT
    ),
    [mergedMessages],
  );

  if (!messages.length && isGenerating) {
    return (
      <div className={styles.messageBlock}>
        <LoadingOutlined spin style={{ marginRight: 8 }} />
        <span>正在思考...</span>
      </div>
    );
  }

  if (!messages.length) return null;

  return (
    <div className={styles.groupedCard}>
      {messages.map((msg, index) => {
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
            if (msg?.content?.[0]?.text) {
              return <MessageBlock key={key} msg={msg} />;
            }
            return null;
        }
      })}
    </div>
  );
}

export default GroupedResponseCard;
