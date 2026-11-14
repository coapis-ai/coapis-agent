// 聊天资源「怎么显示」的唯一尺子：类别 → 图标形状、来源 → 四类标签。
//
// 分类本身沿用 resourceCategory.ts（后端台账契约的镜像，纯数据、不碰样式）；
// 这里只把分类结果落到图标与来源标签上，供三处共用：
//   · 聊天内的本轮资源条（CoApisChatResourceBar）
//   · 左栏会话行下方的整会话资源（ChatSessionResources/Inline）
//   · 「查看全部」打开的资源抽屉（ChatSessionResources/index）
// 三处同一口径 —— 同一条资源在任何位置形状、颜色、标签一致。
//
// 标签文案全部复用既有的 chat.resources.* 四语词条，本次零新增词条。

import type { ReactNode } from "react";
import {
  ApiOutlined,
  BookOutlined,
  BoxPlotOutlined,
  CodeOutlined,
  DatabaseOutlined,
  FileExcelOutlined,
  FileImageOutlined,
  FileOutlined,
  FilePdfOutlined,
  FilePptOutlined,
  FileTextOutlined,
  FileWordOutlined,
  GlobalOutlined,
  MessageOutlined,
  VideoCameraOutlined,
} from "@ant-design/icons";
import type { ChatResourceItem } from "../../../api/modules/chat";
import { CATEGORY_ICON, resolveCategory } from "./resourceCategory";
import type { ResourceCategory } from "./resourceCategory";

/**
 * 图标 key → 图标组件。key 就是 resourceCategory 里 CATEGORY_ICON 的值，
 * 两边键集必须一致（测试钉住），否则新类别进来会静默掉图标。
 */
const ICON_BY_KEY: Record<string, ReactNode> = {
  "file-text": <FileTextOutlined />,
  "file-excel": <FileExcelOutlined />,
  "file-ppt": <FilePptOutlined />,
  "file-pdf": <FilePdfOutlined />,
  "file-word": <FileWordOutlined />,
  "file-image": <FileImageOutlined />,
  "video-camera": <VideoCameraOutlined />,
  "box-plot": <BoxPlotOutlined />,
  code: <CodeOutlined />,
  global: <GlobalOutlined />,
  message: <MessageOutlined />,
  database: <DatabaseOutlined />,
  book: <BookOutlined />,
  api: <ApiOutlined />,
  file: <FileOutlined />,
};

/**
 * 图标表里可用的 key（测试用它钉住「CATEGORY_ICON 的每个值都能取到图标」）。
 */
export const ICON_KEYS = Object.keys(ICON_BY_KEY);

/**
 * 类别 → 颜色。形状按细类走（Word / Excel / PPT / PDF / 图片…各有各的形），
 * 颜色按大类走，一眼能分「文档 / 知识库 / 网页 / 数据源 / 工具 / 会话记录」。
 */
const COLOR_BY_CATEGORY: Record<string, string> = {
  doc: "#1677ff",
  sheet: "#1677ff",
  slide: "#1677ff",
  pdf: "#1677ff",
  image: "#1677ff",
  media: "#1677ff",
  archive: "#1677ff",
  code: "#1677ff",
  web: "#52c41a",
  chat_record: "#2f54eb",
  db_record: "#13c2c2",
  kb_entry: "#722ed1",
  mcp_tool: "#fa8c16",
  other: "#8c8c8c",
};

/** 该条资源的类别（与后端 resolve_category 同规则）。 */
export function categoryOf(item: ChatResourceItem): string {
  return resolveCategory(item.kind, item.path);
}

/** 该条资源的图标（细类形状 + 大类颜色）。 */
export function categoryIconOf(item: ChatResourceItem, size?: number): ReactNode {
  const category = categoryOf(item);
  // ICON_BY_KEY 是 Record<string, ReactNode>：直接下标，别加 keyof 收窄
  // （keyof 会把 string 收窄成字面量联合，字符串变量就进不去）。
  // 索引都要窄类型：CATEGORY_ICON / ICON_BY_KEY 都是 Record<枚举, …>，
  // strict 下用 string 下标就是 TS7053。category 来自后端字符串，先归一到
  // 已知枚举，取不到落 "other"（不崩、不猜）。
  const knownCategories = Object.keys(CATEGORY_ICON) as ResourceCategory[];
  const safeCategory: ResourceCategory = knownCategories.includes(
    category as ResourceCategory,
  )
    ? (category as ResourceCategory)
    : "other";
  const glyphKey: string = CATEGORY_ICON[safeCategory];
  const glyph: ReactNode =
    (ICON_BY_KEY as Record<string, ReactNode>)[glyphKey] ||
    (ICON_BY_KEY as Record<string, ReactNode>).file;
  return (
    <span
      style={{
        color: COLOR_BY_CATEGORY[category] || COLOR_BY_CATEGORY.other,
        fontSize: size,
        lineHeight: 1,
      }}
      aria-hidden
    >
      {glyph}
    </span>
  );
}

// ── 来源四类 ──────────────────────────────────────────────────

/**
 * 来源四类：产出 / 知识库 / 网页 / 引用。
 *
 * 判定顺序固定（先角色后类型，保证一条只有一个来源）：
 *   1. 台账角色是 producer 或 export（导出件）→ 产出
 *      —— 与左栏既有的 PRODUCED_ROLES 同集合，两处不能各说各话
 *   2. kind = kb  → 知识库
 *   3. kind = web → 网页
 *   4. 其余引用件（上传附件、工具、数据表）→ 引用
 * 只看台账 role + kind 两列，零推断。后续要再细分（如「上传」「会话记录」）
 * 只改这一处，三处渲染同时生效。
 */
export type ResourceSource = "produced" | "kb" | "web" | "reference";

export function sourceOf(item: ChatResourceItem): ResourceSource {
  if (item.role === "producer" || item.role === "export") return "produced";
  if (item.kind === "kb") return "kb";
  if (item.kind === "web") return "web";
  return "reference";
}

/** 来源标签文案 key（复用既有四语词条，零新增）。 */
export const SOURCE_LABEL_KEY: Record<ResourceSource, string> = {
  produced: "chat.resources.produced",
  kb: "chat.resources.kindKb",
  web: "chat.resources.kindWeb",
  reference: "chat.resources.reference",
};

/** 来源标签配色（antd Tag 预设色名）。 */
export const SOURCE_COLOR: Record<ResourceSource, string> = {
  produced: "green",
  kb: "purple",
  web: "cyan",
  reference: "geekblue",
};
