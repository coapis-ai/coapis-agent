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
  CheckCircleOutlined,
  LoadingOutlined,
  RightOutlined,
} from '@ant-design/icons';
import { useTheme } from '../../../contexts/ThemeContext';

const { Text } = Typography;

// ---------------------------------------------------------------------------
// Types
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
        eval: '执行JS',
        evaluate: '执行JS',
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
}

const StatusIndicator: React.FC<StatusIndicatorProps> = ({ loading, elapsed }) => {
  if (loading) {
    return (
      <Space size={4} style={{ flexShrink: 0 }}>
        <LoadingOutlined style={{ color: '#1890ff', fontSize: 12 }} />
        <Text type="secondary" style={{ fontSize: 11, fontVariantNumeric: 'tabular-nums' }}>
          {elapsed > 0 ? `${elapsed}s` : ''}
        </Text>
      </Space>
    );
  }
  return (
    <CheckCircleOutlined style={{ color: '#52c41a', fontSize: 12, flexShrink: 0 }} />
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
// EnhancedToolCallCard 主组件
// ---------------------------------------------------------------------------

const EnhancedToolCallCard: React.FC<EnhancedToolCallCardProps> = ({ data }) => {
  const { isDark } = useTheme();
  const content = data.content;
  if (!content || content.length === 0) return null;

  const toolName = content[0]?.data?.name || 'unknown';
  const serverLabel = content[0]?.data?.server_label;
  const argumentsStr = content[0]?.data?.arguments;
  const outputStr = content[1]?.data?.output;
  const loading = data.status === 'in_progress';

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

  // 格式化输出
  const { text: formattedOutput, isLong: isOutputLong } = useMemo(
    () => formatOutput(outputStr),
    [outputStr],
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

  // 构建标题
  const titleText = serverLabel ? `${serverLabel} / ${toolName}` : toolName;

  return (
    <div
      style={{
        border: `1px solid ${loading ? themeColors.accentColor : themeColors.borderColor}`,
        borderLeft: `3px solid ${themeColors.accentColor}`,
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
          expandIcon={({ isActive }) => (
            <RightOutlined
              rotate={isActive ? 90 : 0}
              style={{ fontSize: 11, color: '#999', padding: '4px 0' }}
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

                  {/* 工具名 */}
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

                  {/* 状态指示器 */}
                  <div style={{ marginLeft: 'auto', marginRight: 8 }}>
                    <StatusIndicator loading={loading} elapsed={elapsed} />
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

                  {/* 输入参数 */}
                  {argumentsStr && (
                    <div style={{ marginBottom: outputStr ? 8 : 0 }}>
                      <Text type="secondary" style={{ fontSize: 11 }}>
                        输入:
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
                        输出:
                        {isOutputLong && (
                          <Tag style={{ marginLeft: 4, fontSize: 10, background: themeColors.tagBg, color: themeColors.textSecondary }}>
                            已截断
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
                          borderLeft: `2px solid ${loading ? '#faad14' : '#52c41a'}`,
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
            <StatusIndicator loading={loading} elapsed={elapsed} />
          </div>
        </div>
      )}
    </div>
  );
};

export default EnhancedToolCallCard;
