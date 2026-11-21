/**
 * EnhancedToolCallCard — 增强版工具调用卡片
 *
 * 替代 @agentscope-ai/chat 默认的 ToolCall 卡片，提供：
 * - 智能摘要（人类可读的工具执行描述）
 * - 工具分类图标和颜色
 * - 执行状态指示（pending/running/success/error）
 * - 执行耗时显示
 * - 格式化的输入/输出展示
 *
 * 通过 customToolRenderConfig 注册到 AgentScopeRuntimeWebUI。
 */
import React, { useState, useEffect, useMemo, useRef } from 'react';
import { Collapse, Tag, Space, Typography } from 'antd';
import {
  CaretRightFilled,
  CheckCircleOutlined,
  CloseCircleOutlined,
  StopOutlined,
  LoadingOutlined,
} from '@ant-design/icons';
import { useTranslation } from 'react-i18next';
import { useTheme } from '../../../contexts/ThemeContext';
import { useChatDisplayConfig } from './SimplifiedResponseCard';
import { toolRunningLabel, toolStepLabel } from './toolLabels';

const { Text } = Typography;

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface ToolData {
  content?: Array<{
    data?: {
      name?: string;
      arguments?: string;
      /** 运行时可能是字符串，也可能是 [{type:'text',text}] 块数组或其 JSON 串 */
      output?: unknown;
      server_label?: string;
    };
  }>;
  status?: string;
}

interface EnhancedToolCallCardProps {
  data: ToolData;
}

// ---------------------------------------------------------------------------
// 工具分类配置
// ---------------------------------------------------------------------------

interface ToolCategory {
  icon: string;
  color: string;
  darkColor: string;  // 深色模式下的强调色
  label: string;
  bgColor: string;
  darkBgColor: string;  // 深色模式下的背景色
}

const TOOL_CATEGORIES: Record<string, ToolCategory> = {
  // Shell / 终端
  execute_shell_command: {
    icon: '🖥️',
    color: '#1890ff',
    darkColor: '#4096ff',
    label: '终端',
    bgColor: '#e6f4ff',
    darkBgColor: '#111d2c',
  },

  // 文件读写
  read_file: {
    icon: '📖',
    color: '#52c41a',
    darkColor: '#73d13d',
    label: '读取',
    bgColor: '#f6ffed',
    darkBgColor: '#162312',
  },
  write_file: {
    icon: '✏️',
    color: '#faad14',
    darkColor: '#ffc53d',
    label: '写入',
    bgColor: '#fffbe6',
    darkBgColor: '#2b2111',
  },
  edit_file: {
    icon: '🔧',
    color: '#faad14',
    darkColor: '#ffc53d',
    label: '编辑',
    bgColor: '#fffbe6',
    darkBgColor: '#2b2111',
  },

  // 搜索
  grep_search: {
    icon: '🔍',
    color: '#722ed1',
    darkColor: '#b37feb',
    label: '搜索',
    bgColor: '#f9f0ff',
    darkBgColor: '#1a1325',
  },
  glob_search: {
    icon: '📁',
    color: '#13c2c2',
    darkColor: '#36cfc9',
    label: '查找',
    bgColor: '#e6fffb',
    darkBgColor: '#112123',
  },
  web_search: {
    icon: '🔎',
    color: '#2f54eb',
    darkColor: '#597ef7',
    label: '网页搜索',
    bgColor: '#f0f5ff',
    darkBgColor: '#131629',
  },

  // 浏览器
  browser_use: {
    icon: '🌐',
    color: '#eb2f96',
    darkColor: '#f759ab',
    label: '浏览器',
    bgColor: '#fff0f6',
    darkBgColor: '#2d1225',
  },

  // 记忆
  memory_search: {
    icon: '🧠',
    color: '#f5222d',
    darkColor: '#ff4d4f',
    label: '记忆',
    bgColor: '#fff1f0',
    darkBgColor: '#2a1215',
  },

  // 时间
  get_current_time: {
    icon: '🕐',
    color: '#595959',
    darkColor: '#8c8c8c',
    label: '时间',
    bgColor: '#fafafa',
    darkBgColor: '#1f1f1f',
  },
  set_user_timezone: {
    icon: '🕐',
    color: '#595959',
    darkColor: '#8c8c8c',
    label: '时区',
    bgColor: '#fafafa',
    darkBgColor: '#1f1f1f',
  },

  // 文件传输
  send_file_to_user: {
    icon: '📤',
    color: '#389e0d',
    darkColor: '#52c41a',
    label: '发送',
    bgColor: '#f6ffed',
    darkBgColor: '#162312',
  },

  // Agent 通信
  chat_with_agent: {
    icon: '🤖',
    color: '#1677ff',
    darkColor: '#4096ff',
    label: 'Agent',
    bgColor: '#e6f4ff',
    darkBgColor: '#111d2c',
  },
  submit_to_agent: {
    icon: '🤖',
    color: '#1677ff',
    darkColor: '#4096ff',
    label: 'Agent',
    bgColor: '#e6f4ff',
    darkBgColor: '#111d2c',
  },
  check_agent_task: {
    icon: '🤖',
    color: '#1677ff',
    darkColor: '#4096ff',
    label: 'Agent',
    bgColor: '#e6f4ff',
    darkBgColor: '#111d2c',
  },
  spawn_subagent: {
    icon: '🤖',
    color: '#1677ff',
    darkColor: '#4096ff',
    label: '子Agent',
    bgColor: '#e6f4ff',
    darkBgColor: '#111d2c',
  },

  // 计划
  create_plan: {
    icon: '📋',
    color: '#722ed1',
    darkColor: '#b37feb',
    label: '计划',
    bgColor: '#f9f0ff',
    darkBgColor: '#1a1325',
  },
  revise_current_plan: {
    icon: '📋',
    color: '#722ed1',
    darkColor: '#b37feb',
    label: '计划',
    bgColor: '#f9f0ff',
    darkBgColor: '#1a1325',
  },
  finish_plan: {
    icon: '📋',
    color: '#722ed1',
    darkColor: '#b37feb',
    label: '计划',
    bgColor: '#f9f0ff',
    darkBgColor: '#1a1325',
  },
  view_historical_plans: {
    icon: '📋',
    color: '#722ed1',
    darkColor: '#b37feb',
    label: '计划',
    bgColor: '#f9f0ff',
    darkBgColor: '#1a1325',
  },

  // Token
  get_token_usage: {
    icon: '📊',
    color: '#fa8c16',
    darkColor: '#ffa940',
    label: '统计',
    bgColor: '#fff7e6',
    darkBgColor: '#2b1d11',
  },

  // 视图
  view_image: {
    icon: '🖼️',
    color: '#13c2c2',
    darkColor: '#36cfc9',
    label: '图片',
    bgColor: '#e6fffb',
    darkBgColor: '#112123',
  },
  view_video: {
    icon: '🎬',
    color: '#13c2c2',
    darkColor: '#36cfc9',
    label: '视频',
    bgColor: '#e6fffb',
    darkBgColor: '#112123',
  },
  desktop_screenshot: {
    icon: '📸',
    color: '#13c2c2',
    darkColor: '#36cfc9',
    label: '截图',
    bgColor: '#e6fffb',
    darkBgColor: '#112123',
  },

  // 列表/视图
  list_agents: {
    icon: '👥',
    color: '#595959',
    darkColor: '#8c8c8c',
    label: '列表',
    bgColor: '#fafafa',
    darkBgColor: '#1f1f1f',
  },
};

const DEFAULT_CATEGORY: ToolCategory = {
  icon: '⚙️',
  color: '#595959',
  darkColor: '#8c8c8c',
  label: '工具',
  bgColor: '#fafafa',
  darkBgColor: '#1f1f1f',
};

// ---------------------------------------------------------------------------
// 智能摘要生成器
// ---------------------------------------------------------------------------

function generateSummary(toolName: string, input: Record<string, any>): string {
  switch (toolName) {
    case 'execute_shell_command': {
      const cmd = input.command || '';
      const cwd = input.cwd || '';
      const shortCmd = cmd.length > 80 ? cmd.slice(0, 80) + '...' : cmd;
      return cwd ? `${shortCmd}` : shortCmd;
    }

    case 'read_file': {
      const path = input.file_path || '';
      const start = input.start_line;
      const end = input.end_line;
      if (start || end) {
        return `${path} (L${start || 1}-${end || 'end'})`;
      }
      return path;
    }

    case 'write_file':
      return input.file_path || '';

    case 'edit_file': {
      const path = input.file_path || '';
      const old = (input.old_text || '').slice(0, 30);
      return `${path}: "${old}${old.length >= 30 ? '...' : ''}" → ...`;
    }

    case 'grep_search': {
      const pattern = input.pattern || '';
      const path = input.path || '';
      const shortPattern = pattern.length > 40 ? pattern.slice(0, 40) + '...' : pattern;
      return path ? `"${shortPattern}" in ${path}` : `"${shortPattern}"`;
    }

    case 'glob_search':
      return input.pattern || '';

    case 'browser_use': {
      const action = input.action || '';
      const url = input.url || '';
      const text = input.text || '';
      const actions: Record<string, string> = {
        open: '打开',
        navigate: '导航',
        snapshot: '快照',
        screenshot: '截图',
        click: '点击',
        type: '输入',
        start: '启动',
        stop: '停止',
        press_key: '按键',
        wait_for: '等待',
        eval: '执行脚本',
        evaluate: '执行脚本',
        hover: '悬停',
        select_option: '选择',
        file_upload: '上传',
        file_download: '下载',
        fill_form: '填表',
        batch: '批量操作',
      };
      const actionLabel = actions[action] || action;
      if (url) return `${actionLabel} ${url.length > 60 ? url.slice(0, 60) + '...' : url}`;
      if (text) return `${actionLabel} "${text.slice(0, 40)}${text.length > 40 ? '...' : ''}"`;
      return actionLabel;
    }

    case 'web_search':
      return `"${input.query || ''}"`;

    case 'memory_search':
      return `"${input.query || ''}"`;

    case 'send_file_to_user':
      return input.file_path || '';

    case 'chat_with_agent':
    case 'submit_to_agent':
      return `→ ${input.to_agent || ''}`;

    case 'spawn_subagent':
      return (input.task || '').slice(0, 60) + ((input.task || '').length > 60 ? '...' : '');

    case 'create_plan':
      return input.name || '';

    case 'get_current_time':
      return '';

    case 'set_user_timezone':
      return input.timezone_name || '';

    case 'get_token_usage':
      return input.model_name ? `模型: ${input.model_name}` : `最近 ${input.days || 30} 天`;

    case 'view_image':
    case 'view_video':
      return input.image_path || input.video_path || '';

    case 'desktop_screenshot':
      return '';

    case 'list_agents':
      return '';

    default: {
      // 兜底：显示第一个参数
      const keys = Object.keys(input || {});
      if (keys.length === 0) return '';
      const firstKey = keys[0];
      const firstVal = input[firstKey];
      if (typeof firstVal === 'string') {
        return firstVal.length > 50 ? firstVal.slice(0, 50) + '...' : firstVal;
      }
      return JSON.stringify(firstVal).slice(0, 50);
    }
  }
}

// ---------------------------------------------------------------------------
// 状态图标组件
// ---------------------------------------------------------------------------

interface StatusIndicatorProps {
  loading: boolean;
  elapsed: number;
  failed?: boolean;
  aborted?: boolean;
  /** 被安全规则拦下：动作没执行，不能显示绿色✅ */
  blocked?: boolean;
  /** 运行中动作文案（按工具类别给，如「读取中/写入中/检索中」） */
  runningText?: string;
}

const StatusIndicator: React.FC<StatusIndicatorProps> = ({
  loading,
  elapsed,
  failed,
  aborted,
  blocked,
  runningText,
}) => {
  const { t } = useTranslation();

  if (loading) {
    return (
      <Space size={6}>
        <LoadingOutlined style={{ fontSize: 14, color: '#1677ff' }} spin />
        {elapsed > 0 && (
          <Text type="secondary" style={{ fontSize: 11 }}>
            {`${elapsed}s`}
          </Text>
        )}
        <Text type="secondary" style={{ fontSize: 11 }}>
          {runningText || t('chat.tool.running', '正在处理')}
        </Text>
      </Space>
    );
  }

  if (blocked) {
    return (
      <Space size={4}>
        <StopOutlined style={{ fontSize: 14, color: '#ff4d4f' }} />
        <Text style={{ fontSize: 11, color: '#ff4d4f' }}>
          {t('chat.tool.blocked', '已拦下')}
        </Text>
      </Space>
    );
  }

  if (failed) {
    return (
      <Space size={4}>
        <CloseCircleOutlined style={{ fontSize: 12, color: '#ff4d4f' }} />
        <Text type="secondary" style={{ fontSize: 11 }}>
          {t('chat.tool.failed', '没成功')}
        </Text>
      </Space>
    );
  }

  if (aborted) {
    return (
      <Space size={4}>
        <StopOutlined style={{ fontSize: 12, color: '#faad14' }} />
        <Text type="secondary" style={{ fontSize: 11 }}>
          {t('chat.tool.aborted', '已停止')}
        </Text>
      </Space>
    );
  }

  return (
    <Space size={4}>
      <CheckCircleOutlined style={{ fontSize: 14, color: '#52c41a' }} />
      {elapsed > 0 && (
        <Text type="secondary" style={{ fontSize: 11 }}>
          {`${elapsed}s`}
        </Text>
      )}
    </Space>
  );
};

// ---------------------------------------------------------------------------
// 格式化输出
// ---------------------------------------------------------------------------

function formatOutput(output: string | undefined): { text: string; isLong: boolean } {
  if (!output) return { text: '', isLong: false };

  let display = output;

  // 尝试解析 JSON 并格式化
  try {
    const parsed = JSON.parse(output);
    display = JSON.stringify(parsed, null, 2);
  } catch {
    // 非 JSON，直接使用原文
    display = output;
  }

  const isLong = display.length > 500;
  if (isLong) {
    display = display.slice(0, 500) + '\n... (已截断)';
  }

  return { text: display, isLong };
}

// ---------------------------------------------------------------------------
// 拦截哨兵（尾巴1：被拦下的工具以前在界面里显示绿色✅）
// ---------------------------------------------------------------------------
//
// 工具结果一路到前端只剩一条 `output` 字符串，没有 error 位可用；后端
// `tool_guard_mixin` 在自动拦截时会把一枚哨兵放在输出**首行**：
//   [[coapis:tool-blocked]] kind=plan_scope_pending
// 卡片据此判定「这个动作其实没执行」，渲染成 ⛔ 已拦下 + 原因，并把这一行
// 机器标记从展示文本里剥掉。只有首行以哨兵开头才算被拦下——正文里偶然出现
// 同样字样不会误判。
export const GUARD_BLOCK_SENTINEL = '[[coapis:tool-blocked]]';

/** kind → [i18n key, 中文兜底] */
const GUARD_BLOCK_REASONS: Record<string, [string, string]> = {
  plan_scope_pending: [
    'chat.tool.blockedReason.planScopePending',
    '方案还没确认，这个动作已拦下',
  ],
  guard_denied: [
    'chat.tool.blockedReason.guardDenied',
    '安全规则拦下了这个动作',
  ],
};

export function parseGuardBlock(
  output: string | undefined,
): { kind: string; text: string } | null {
  if (!output) return null;
  const lines = output.split('\n');
  let firstIdx = -1;
  for (let i = 0; i < lines.length; i += 1) {
    if (lines[i].trim().length > 0) {
      firstIdx = i;
      break;
    }
  }
  if (firstIdx < 0 || !lines[firstIdx].trim().startsWith(GUARD_BLOCK_SENTINEL)) {
    return null;
  }
  const head = lines[firstIdx].trim();
  const matched = /kind=([A-Za-z0-9_-]+)/.exec(head.slice(GUARD_BLOCK_SENTINEL.length));
  const text = [
    ...lines.slice(0, firstIdx),
    ...lines.slice(firstIdx + 1),
  ]
    .join('\n')
    .trim();
  return { kind: matched ? matched[1] : 'guard_denied', text };
}

export function guardBlockReason(
  kind: string,
  translate: (key: string, defaultValue: string) => string,
): string {
  const entry = GUARD_BLOCK_REASONS[kind] || GUARD_BLOCK_REASONS.guard_denied;
  return translate(entry[0], entry[1]);
}
/**
 * 把工具输出归一成纯文本。
 *
 * 运行时这里可能收到三种形状：字符串、`[{type:'text',text}]` 块数组、以及块
 * 数组的 JSON 串（历史消息回灌时最常见）。不归一的话哨兵永远在第二行以后，
 * "被拦下"就会被判成普通成功；顺带也不再往界面上吐生 JSON。认不出文本块的
 * JSON（工具真的返回 JSON 数据）保持原样，不吞内容。
 */
export function coerceToolOutput(raw: unknown): string {
  const blocksToText = (value: unknown): string => {
    if (value == null) return '';
    if (typeof value === 'string') return value;
    if (Array.isArray(value)) {
      return value.map(blocksToText).filter((s) => s.length > 0).join('\n');
    }
    if (typeof value === 'object') {
      const obj = value as Record<string, unknown>;
      if (typeof obj.text === 'string') return obj.text;
      if (obj.output !== undefined) return blocksToText(obj.output);
    }
    return '';
  };

  if (raw == null) return '';
  if (typeof raw === 'string') {
    const trimmed = raw.trim();
    if (trimmed.startsWith('[') || trimmed.startsWith('{')) {
      try {
        const text = blocksToText(JSON.parse(trimmed));
        if (text) return text;
      } catch {
        /* 不是合法 JSON，原样展示 */
      }
    }
    return raw;
  }
  const fromBlocks = blocksToText(raw);
  if (fromBlocks) return fromBlocks;
  try {
    return JSON.stringify(raw, null, 2);
  } catch {
    return String(raw);
  }
}

// ---------------------------------------------------------------------------
// EnhancedToolCallCard 主组件
// ---------------------------------------------------------------------------

/**
 * 展开态尺子（SSOT，2026-11-12 用户拍板 / B0 契约锁）
 * ---------------------------------------------------------------------------
 * 规则只有一条：**运行中或被拦下时临时展开，正常完成即收起**；
 * `manualOpen === null` 表示用户从没手动开合过 → 完全跟随运行状态；
 * 用户一旦手动开合，之后一律以用户的为准，机器不再抢状态。
 *
 * 抽成纯函数的原因：这条规则是这个组件唯一的"状态机"，之前只能靠肉眼看
 * 渲染结果来验收。测试要钉住它，就得让它脱离 React 也能被调用。
 * 组件里的调用点必须走这里，不要再写第二份等价表达式。
 */
export function computeCardActiveKey({
  hasDetails,
  loading,
  manualOpen,
  blocked = false,
}: {
  hasDetails: boolean;
  loading: boolean;
  manualOpen: boolean | null;
  /** 被安全规则拦下时默认展开——用户得看得到"为什么没执行" */
  blocked?: boolean;
}): string[] {
  return hasDetails && (manualOpen ?? (loading || blocked)) ? ["1"] : [];
}

const EnhancedToolCallCard: React.FC<EnhancedToolCallCardProps> = ({ data }) => {
  const { isDark } = useTheme();
  const { t, i18n } = useTranslation();
  const displayCfg = useChatDisplayConfig();
  const content = data.content;
  if (!content || content.length === 0) return null;

  const toolName = content[0]?.data?.name || 'unknown';
  const serverLabel = content[0]?.data?.server_label;
  const argumentsStr = content[0]?.data?.arguments;
  const outputStr = coerceToolOutput(content[1]?.data?.output);
  const loading = data.status === 'in_progress';
  const failed = data.status === 'failed' || data.status === 'rejected';
  const aborted = data.status === 'canceled';

  // 被安全规则拦下的动作其实没有执行。以前卡片照旧显示绿色✅，等于界面在
  // 撒谎（尾巴1）；这里解析后端哨兵，把"拦下"这件事如实体现在界面上，
  // 并把拦截原因摊开给用户看（尾巴2：拦下之后用户看不到任何说明）。
  const guardBlock = useMemo(() => parseGuardBlock(outputStr), [outputStr]);
  const blocked = guardBlock !== null;
  const blockedReason = guardBlock
    ? guardBlockReason(guardBlock.kind, t)
    : '';

  // 解析输入参数
  const inputObj = useMemo(() => {
    if (!argumentsStr) return {};
    try {
      return typeof argumentsStr === 'string' ? JSON.parse(argumentsStr) : argumentsStr;
    } catch {
      return {};
    }
  }, [argumentsStr]);

  // 获取工具分类
  const category = TOOL_CATEGORIES[toolName] || DEFAULT_CATEGORY;

  // 根据主题动态获取颜色
  const themeColors = useMemo(() => ({
    accentColor: isDark ? category.darkColor : category.color,
    bgColor: isDark ? category.darkBgColor : category.bgColor,
    cardBg: isDark ? '#1f1f1f' : '#fff',
    borderColor: isDark ? '#303030' : '#e8e8e8',
    textPrimary: isDark ? 'rgba(255,255,255,0.88)' : 'rgba(0,0,0,0.88)',
    textSecondary: isDark ? 'rgba(255,255,255,0.65)' : 'rgba(0,0,0,0.65)',
    textTertiary: isDark ? 'rgba(255,255,255,0.45)' : 'rgba(0,0,0,0.45)',
    codeBg: isDark ? '#141414' : '#f5f5f5',
    outputBg: isDark ? '#141414' : '#f6ffed',
    tagBg: isDark ? '#262626' : '#fafafa',
  }), [isDark, category]);

  // 生成智能摘要
  const summary = useMemo(() => generateSummary(toolName, inputObj), [toolName, inputObj]);

  /**
   * Structured preview of a plan created inside the stream. The raw JSON dump
   * below stays available, but a plan is only useful when its steps are
   * readable where the model announced it.
  */
  const planSteps = useMemo(() => {
    if (toolName !== "create_plan" && toolName !== "revise_current_plan") {
      return [] as { name: string; description?: string }[];
    }
    const obj = inputObj as Record<string, unknown> | null;
    const nested = obj?.plan as Record<string, unknown> | undefined;
    const raw = obj?.subtasks ?? nested?.subtasks;
    if (!Array.isArray(raw)) return [] as { name: string; description?: string }[];
    return raw
      .map((item) => {
        const s = (item ?? {}) as Record<string, unknown>;
        const name = typeof s.name === "string" ? s.name.trim() : "";
        const desc = typeof s.description === "string" ? s.description.trim() : "";
        return { name, description: desc || undefined };
      })
      .filter((s) => s.name.length > 0);
  }, [toolName, inputObj]);

  // 格式化输出（先剥掉哨兵行，别让机器标记漏进界面）
  const { text: formattedOutput, isLong: isOutputLong } = useMemo(
    () => formatOutput(guardBlock ? guardBlock.text : outputStr),
    [outputStr, guardBlock],
  );

  // 计时器
  const startTimeRef = useRef<number>(Date.now());
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    if (loading) {
      startTimeRef.current = Date.now();
      const timer = setInterval(() => {
        setElapsed(Math.floor((Date.now() - startTimeRef.current) / 1000));
      }, 1000);
      return () => clearInterval(timer);
    } else {
      setElapsed(Math.floor((Date.now() - startTimeRef.current) / 1000));
    }
  }, [loading]);

  // 构建标题（D5 拍板：中文动词走 toolLabels SSOT，原始工具名保留在后，双语跟随界面语言）
  const zhVerb = toolStepLabel(toolName, i18n.language);
  // 标题只说人话（2026-11-12 用户拍板）：中文环境用中文动词收尾，不再拖英文工具名尾巴；
  // MCP 工具保留服务器名，否则看不出在调哪个系统。
  const titleText =
    zhVerb && zhVerb !== toolName
      ? (serverLabel ? `${zhVerb} · ${serverLabel}` : zhVerb)
      : serverLabel
        ? `${serverLabel} / ${toolName}`
        : toolName;

  // 展开态尺子（2026-11-12 用户拍板）：统一收起——只有运行中临时展开，完成即收起。
  // manualOpen 为 null 表示用户从没手动开合过，此时完全跟随运行状态；
  // 用户一旦手动开合，之后一律以用户的为准，机器不再抢状态。
  const hasDetails = Boolean(argumentsStr || outputStr) && !displayCfg.hideDetails;
  const [manualOpen, setManualOpen] = useState<boolean | null>(null);
  const activeKey = computeCardActiveKey({ hasDetails, loading, manualOpen, blocked });

  return (
    <div
      style={{
        border: `1px solid ${
          blocked ? '#ff4d4f' : loading ? themeColors.accentColor : themeColors.borderColor
        }`,
        borderLeft: `3px solid ${blocked ? '#ff4d4f' : themeColors.accentColor}`,
        borderRadius: 6,
        marginBottom: 8,
        background: loading ? themeColors.bgColor : themeColors.cardBg,
        transition: 'all 0.3s ease',
        overflow: 'hidden',
      }}
    >
      {/* 头部：图标 + 工具名 + 折叠按钮（右侧） */}
      {(argumentsStr || outputStr) ? (
        <Collapse
          ghost
          size="small"
          expandIconPosition="end"
          activeKey={activeKey}
          onChange={(keys) => setManualOpen((keys as string[]).length > 0)}
          expandIcon={({ isActive }) => (
            <CaretRightFilled
              rotate={isActive ? 90 : 0}
              style={{ fontSize: 18, color: '#8c8c8c', padding: '4px 2px' }}
            />
          )}
          items={[
            {
              key: '1',
              label: (
                <div
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 6,
                    padding: '2px 0',
                  }}
                >
                  {/* 工具图标 */}
                  <span style={{ fontSize: 14, flexShrink: 0 }}>{category.icon}</span>

                  {/* 工具名（被拦下时紧跟一行原因：收起状态也看得见） */}
                  <div style={{ flex: '1 1 auto', minWidth: 0 }}>
                    <Text
                      strong
                      style={{
                        fontSize: 12,
                        display: 'block',
                        overflow: 'hidden',
                        textOverflow: 'ellipsis',
                        whiteSpace: 'nowrap',
                      }}
                    >
                      {titleText}
                    </Text>
                    {blocked && (
                      <Text
                        style={{
                          fontSize: 11,
                          display: 'block',
                          color: '#ff4d4f',
                          lineHeight: '16px',
                        }}
                      >
                        {blockedReason}
                      </Text>
                    )}
                  </div>

                  {/* 状态指示器 */}
                  <div style={{ marginRight: 8 }}>
                    <StatusIndicator
                      loading={loading}
                      elapsed={elapsed}
                      failed={failed}
                      aborted={aborted}
                      blocked={blocked}
                      runningText={toolRunningLabel(toolName, i18n.language)}
                    />
                  </div>
                </div>
              ),
              children: (
                <div style={{ fontSize: 12, padding: '0 0 8px' }}>
                  {/* 智能摘要 */}
                  {summary && (
                    <div style={{ marginBottom: 8, color: themeColors.textSecondary, fontSize: 12 }}>
                      {summary}
                    </div>
                  )}

                  {/* 计划步骤预览：让流里的计划卡不再只有一个名字 */}
                  {planSteps.length > 0 && (
                    <div style={{ marginBottom: 8 }}>
                      <Text
                        strong
                        style={{ fontSize: 11, color: themeColors.textSecondary }}
                      >
                        {t('chat.toolCall.planSteps', '计划步骤')} (
                        {planSteps.length})
                      </Text>
                      <ol
                        style={{
                          margin: '4px 0 0',
                          paddingInlineStart: 18,
                          fontSize: 11,
                          color: themeColors.textPrimary,
                        }}
                      >
                        {planSteps.map((s, i) => (
                          <li key={`${s.name}-${i}`} style={{ marginBottom: 2 }}>
                            {s.name}
                            {s.description ? ` — ${s.description}` : ''}
                          </li>
                        ))}
                      </ol>
                    </div>
                  )}

                  {/* 输入参数 */}
                  {argumentsStr && (
                    <div style={{ marginBottom: outputStr ? 8 : 0 }}>
                      <Text type="secondary" style={{ fontSize: 11 }}>
                        {t('chat.tool.params', '做什么')}:
                      </Text>
                      <pre
                        style={{
                          background: themeColors.codeBg,
                          padding: 6,
                          borderRadius: 4,
                          fontSize: 11,
                          maxHeight: 200,
                          overflow: 'auto',
                          margin: '4px 0 0',
                          whiteSpace: 'pre-wrap',
                          wordBreak: 'break-all',
                          color: themeColors.textPrimary,
                        }}
                      >
                        {typeof argumentsStr === 'string'
                          ? (() => {
                              try {
                                return JSON.stringify(JSON.parse(argumentsStr), null, 2);
                              } catch {
                                return argumentsStr;
                              }
                            })()
                          : JSON.stringify(argumentsStr, null, 2)}
                      </pre>
                    </div>
                  )}

                  {/* 输出结果 */}
                  {outputStr && (
                    <div>
                      <Text type="secondary" style={{ fontSize: 11 }}>
                        {blocked
                          ? t('chat.tool.blockedDetail', '拦下原因')
                          : t('chat.tool.output', '结果')}:
                        {isOutputLong && (
                          <Tag style={{ marginLeft: 4, fontSize: 10, background: themeColors.tagBg, color: themeColors.textSecondary }}>
                            {t('chat.tool.truncated', '已截断')}
                          </Tag>
                        )}
                      </Text>
                      <pre
                        style={{
                          background: loading ? themeColors.bgColor : themeColors.outputBg,
                          padding: 6,
                          borderRadius: 4,
                          fontSize: 11,
                          maxHeight: 300,
                          overflow: 'auto',
                          margin: '4px 0 0',
                          whiteSpace: 'pre-wrap',
                          wordBreak: 'break-all',
                          borderLeft: `2px solid ${
                            blocked ? '#ff4d4f' : loading ? '#faad14' : '#52c41a'
                          }`,
                          color: themeColors.textPrimary,
                        }}
                      >
                        {formattedOutput}
                      </pre>
                    </div>
                  )}
                </div>
              ),
            },
          ]}
        />
      ) : (
        /* 无详情时只显示标题行 */
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            padding: '4px 12px',
            gap: 6,
          }}
        >
          <span style={{ fontSize: 14, flexShrink: 0 }}>{category.icon}</span>
          <Text
            strong
            style={{
              fontSize: 12,
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
            }}
          >
            {titleText}
          </Text>
          <div style={{ marginLeft: 'auto' }}>
            <StatusIndicator
              loading={loading}
              elapsed={elapsed}
              failed={failed}
              aborted={aborted}
              blocked={blocked}
              runningText={toolRunningLabel(toolName, i18n.language)}
            />
          </div>
        </div>
      )}
    </div>
  );
};

export default EnhancedToolCallCard;
