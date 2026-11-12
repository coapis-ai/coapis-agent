/**
 * toolLabels — CoApis 工具调用中文动词映射（SSOT）
 *
 * 简洁模式步骤条与 EnhancedToolCallCard 共用此映射，
 * 保证「同一个工具在两个渲染层里说同一句中文」。
 *
 * 约定：
 * - 键 = 后端下发的工具 name（与 CoApis 运行时注册名一致）
 * - 值 = 中文动词短语（≤ 6 字为佳，步骤条一行一格）
 * - 未映射工具兜底「工具 · {name}」；非中文语言直接显示原始 name
 */

/** 中文动词映射表（SSOT，新增工具往这里加） */
export const TOOL_VERB_LABELS_ZH: Record<string, string> = {
  read_file: '读取文件',
  write_file: '写入文件',
  edit_file: '编辑文件',
  execute_shell_command: '执行命令',
  grep_search: '搜索内容',
  glob_search: '查找文件',
  list_files: '列出文件',
  view_image: '查看图片',
  view_video: '查看视频',
  desktop_screenshot: '屏幕截图',
  browser_use: '操作浏览器',
  web_search: '联网搜索',
  web_fetch: '抓取网页',
  memory_search: '检索记忆',
  Skill: '加载技能',
  spawn_subagent: '派发子任务',
  check_agent_task: '查询子任务',
  chat_with_agent: '咨询智能体',
  list_agents: '列出智能体',
  create_plan: '制定计划',
  revise_current_plan: '调整计划',
  update_subtask_state: '更新步骤状态',
  finish_subtask: '完成步骤',
  finish_plan: '完成任务',
  submit_to_agent: '提交任务给智能体',
  send_file_to_user: '发送文件',
  get_current_time: '获取时间',
  use_metadataskill: '加载技能',
  call_mcp: '调用工具',
  // 2026-11-12 补齐（尺子 = 后端 /api/tools 注册工具表 + 真实会话跑到的框架工具）
  view_text_file: '查看文件',
  write_text_file: '写入文件',
  insert_text_file: '插入文本',
  append_file: '追加写入',
  execute_python_code: '运行代码',
  code_exec: '运行代码',
  convert_file: '转换格式',
  doc_reader: '解析文档',
  git_ops: '版本操作',
  install_dependency: '安装依赖',
  cron_scheduler: '定时任务',
  todo_tool: '更新待办',
  tool_stats: '工具统计',
  skill_manager: '管理技能',
  materialize_skill: '沉淀技能',
  resource_search: '检索资源',
  session_search: '检索会话',
  record_daily_memory: '记录日志',
  recall_history: '回溯对话',
  reset_equipped_tools: '重置工具',
};

/**
 * 工具名的步骤条显示标签。
 *
 * @param name 后端下发的工具 name
 * @param lang 当前 i18n 语言（如 'zh' / 'zh-CN' / 'en' / 'ja' / 'ru'）
 * @returns 中文语言环境返回中文动词（未映射兜底「工具 · {name}」）；
 *          其他语言环境返回原始 name。
 */
export function toolStepLabel(name: string, lang: string): string {
  if (!name) return '';
  const base = (lang || 'zh').toLowerCase().split('-')[0];
  if (base === 'zh') {
    return TOOL_VERB_LABELS_ZH[name] ?? `工具 · ${name}`;
  }
  return name;
}

/**
 * 运行中的动作文案（2026-11-12）：统一的「执行中」太机械——读文件、写文件、
 * 检索时用户做的是完全不同的事，这里按工具给出贴切的进行态。
 * 非中文环境返回空串，由调用方退回通用文案。
 */
export const TOOL_RUNNING_LABELS_ZH: Record<string, string> = {
  read_file: '读取中',
  view_text_file: '读取中',
  doc_reader: '读取中',
  write_file: '写入中',
  write_text_file: '写入中',
  append_file: '写入中',
  insert_text_file: '写入中',
  edit_file: '修改中',
  convert_file: '转换中',
  grep_search: '检索中',
  glob_search: '检索中',
  list_files: '检索中',
  web_search: '检索中',
  web_fetch: '抓取中',
  resource_search: '检索中',
  session_search: '检索中',
  memory_search: '检索中',
  recall_history: '检索中',
  browser_use: '操作中',
  install_dependency: '安装中',
  git_ops: '提交中',
  code_exec: '执行中',
  execute_python_code: '执行中',
  record_daily_memory: '记录中',
  skill_manager: '整理技能中',
  cron_scheduler: '设置定时中',
};

export function toolRunningLabel(name: string, lang: string): string {
  if (!name) return '';
  const base = (lang || 'zh').toLowerCase().split('-')[0];
  if (base !== 'zh') return '';
  return TOOL_RUNNING_LABELS_ZH[name] || '';
}
