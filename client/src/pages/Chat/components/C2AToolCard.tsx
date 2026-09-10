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
import C2ARenderer, { setUrlNavigate } from '@coapis-c2a/renderer/C2ARenderer';
import type { C2AMessage } from '@coapis-c2a/renderer/types';
import { openExternalUrl } from '@/utils/externalNav';

const { Text } = Typography;

// 外部系统导航拦截：C2A 卡片里的行链接 / 按钮 / 快捷建议点击外部 URL 时，
// 先向后端换取带身份断言的签名 URL 再打开（浏览器无法带自定义请求头）。
// 非外部 URL 或后端不可用时，externalNav 会兜底直接打开。
setUrlNavigate(openExternalUrl);

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

/**
 * 从 agentscope 内容块数组中提取真正的 C2A 结果对象。
 *
 * 工具返回的 dict 在 SSE/历史消息里被 runtime 包装成内容块数组：
 *   '[{"type": "text", "text": "<C2A 结果的 JSON 字符串>"}]'
 * text 字段是二次 JSON 字符串，需再 parse 一次。
 */
function unwrapContentBlocks(blocks: unknown[]): Record<string, any> | null {
  for (const b of blocks) {
    if (
      b &&
      typeof b === 'object' &&
      (b as any).type === 'text' &&
      typeof (b as any).text === 'string'
    ) {
      try {
        const inner = JSON.parse((b as any).text);
        if (inner && typeof inner === 'object' && !Array.isArray(inner)) {
          return inner as Record<string, any>;
        }
      } catch {
        // text 块不是 JSON，继续找下一个
      }
    }
  }
  return null;
}

/**
 * 解析工具输出，兼容四种形态：
 *   1. 已是 C2A 结果对象（dict）
 *   2. C2A 结果对象的 JSON 字符串
 *   3. 内容块数组（历史消息重载时 output 已是数组）
 *   4. 内容块数组的 JSON 字符串（实时 SSE 流的实际形态）
 */
function parseToolOutput(raw: unknown): Record<string, any> | null {
  if (!raw) return null;
  let value: unknown = raw;
  if (typeof raw === 'string') {
    try {
      value = JSON.parse(raw);
    } catch {
      return null;
    }
  }
  if (!value || typeof value !== 'object') return null;
  if (Array.isArray(value)) {
    return unwrapContentBlocks(value);
  }
  return value as Record<string, any>;
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
  // output 可能在 content[0]（plugin_call_output）或 content[1]（与默认
  // ToolCall 组件一致的形态），两处都试。
  const output =
    data?.content?.[0]?.data?.output ?? data?.content?.[1]?.data?.output;

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

  // 2) 跳过（工具输出里没有可渲染的数据列表）→ 简洁提示。
  // 不展示原始输出/技术报错——数据已由 LLM 的文字回复呈现给用户。
  if (parsed && parsed.status === 'skipped') {
    return (
      <div className="c2a-tool-card">
        <Text type="secondary">ℹ️ 暂无可展示的表格数据</Text>
      </div>
    );
  }

  // 3) 失败或无法解析 → 同样只给一句简洁提示，绝不向最终用户展示
  // 原始 JSON / 错误码 / 技术细节（数据在 LLM 的文字回复里）。
  return (
    <div className="c2a-tool-card">
      <Text type="secondary">⚠️ 卡片渲染失败，数据以文字形式展示</Text>
    </div>
  );
}
