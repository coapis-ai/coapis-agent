/**
 * C2AToolCard — c2a_render_card 工具的结果卡片
 *
 * 注册到 AgentScopeRuntimeWebUI 的 customToolRenderConfig（工具名
 * `c2a_render_card`）。后端 c2a-c2a 包的 c2a_render_card 工具返回：
 *   { status: 'success' | 'failed' | 'skipped',
 *     c2a_message: {...}, c2a_json: "...", errors: [...] }
 * 本组件解析该 JSON，把 c2a_message 交给独立的 @coapis-c2a/renderer
 * 渲染（数据表格 + 行级链接 + 快捷建议）。
 */
import { useMemo } from 'react';
import { Typography } from 'antd';
import C2ARenderer from '@coapis-c2a/renderer/C2ARenderer';
import type { C2AMessage } from '@coapis-c2a/renderer/types';

const { Text, Paragraph } = Typography;

// ---------------------------------------------------------------------------
// Types（与 EnhancedToolCallCard 的 ToolData 保持一致）
// ---------------------------------------------------------------------------

interface ToolData {
  content?: Array<{
    data?: {
      name?: string;
      arguments?: string;
      output?: string;
      server_label?: string;
    };
  }>;
  status?: string;
}

interface C2AToolCardProps {
  data: ToolData;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** 解析工具输出：可能是 JSON 字符串，也可能已是对象。 */
function parseToolOutput(raw: unknown): Record<string, any> | null {
  if (!raw) return null;
  if (typeof raw === 'object') return raw as Record<string, any>;
  if (typeof raw !== 'string') return null;
  try {
    return JSON.parse(raw) as Record<string, any>;
  } catch {
    return null;
  }
}

/** 归一化 C2A 消息：补齐 C2ARenderer 需要的必填字段。 */
function normalizeMessage(msg: any): C2AMessage {
  return {
    protocol_version: msg?.protocol_version || 'c2a-v1.0',
    message_id: msg?.message_id || `msg_${Date.now()}`,
    context_ref: msg?.context_ref || { session_id: 'default_session' },
    metadata: msg?.metadata || { generated_by: 'c2a' },
    blocks: Array.isArray(msg?.blocks) ? msg.blocks : [],
    actions: Array.isArray(msg?.actions) ? msg.actions : [],
    suggestions: Array.isArray(msg?.suggestions) ? msg.suggestions : [],
    state: msg?.state || { status: 'rendered' },
  } as C2AMessage;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function C2AToolCard({ data }: C2AToolCardProps) {
  const output = data?.content?.[0]?.data?.output;

  const parsed = useMemo(() => parseToolOutput(output), [output]);
  const c2aMessage = useMemo(
    () =>
      parsed && parsed.status === 'success' && parsed.c2a_message
        ? normalizeMessage(parsed.c2a_message)
        : null,
    [parsed],
  );

  // 1) 成功 → 渲染 C2A 卡片（表格 + 行链接 + 建议）
  if (c2aMessage) {
    return (
      <div className="c2a-tool-card">
        <C2ARenderer message={c2aMessage} />
      </div>
    );
  }

  // 2) 跳过（工具输出里没有可渲染的数据列表）→ 提示 + 原始输出
  if (parsed && parsed.status === 'skipped') {
    return (
      <div className="c2a-tool-card">
        <Text type="secondary">
          ℹ️ {Array.isArray(parsed.errors) && parsed.errors[0]
            ? parsed.errors[0]
            : '无可渲染的 C2A 卡片数据'}
        </Text>
        {output ? (
          <Paragraph
            style={{
              whiteSpace: 'pre-wrap',
              wordBreak: 'break-word',
              fontSize: 12,
              color: '#999',
              marginTop: 8,
            }}
            ellipsis={{ rows: 4, expandable: true, symbol: '展开' }}
          >
            {typeof output === 'string' ? output : JSON.stringify(output)}
          </Paragraph>
        ) : null}
      </div>
    );
  }

  // 3) 失败或无法解析 → 显示错误 / 原始输出
  const errorText =
    parsed && Array.isArray(parsed.errors) && parsed.errors.length > 0
      ? parsed.errors.join('; ')
      : null;

  return (
    <div className="c2a-tool-card">
      {errorText ? <Text type="danger">⚠️ {errorText}</Text> : null}
      {output ? (
        <Paragraph
          style={{
            whiteSpace: 'pre-wrap',
            wordBreak: 'break-word',
            fontSize: 12,
            color: '#999',
            marginTop: errorText ? 8 : 0,
          }}
          ellipsis={{ rows: 6, expandable: true, symbol: '展开' }}
        >
          {typeof output === 'string' ? output : JSON.stringify(output)}
        </Paragraph>
      ) : null}
    </div>
  );
}
