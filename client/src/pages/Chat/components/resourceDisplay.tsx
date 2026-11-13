// 聊天资源「怎么显示」的唯一尺子：类别 → 图标形状、来源 → 四类标签。
//
// 分类本身沿用 resourceCategory.ts（后端台账契约的镜像，纯数据、不碰样式）；
// 这里只把分类结果落到图标与来源标签上，供三处共用：
//   · 聊天内的本轮资源条（CoApisChatResourceBar）
//   · 左栏会话行下方的整会话资源（ChatSessionResources/Inline）
//   · 「查看全部」打开的资源抽屉（ChatSessionResources）
// 三处必须同一口径 —— 同一条资源在任何位置形状、颜色、标签一致。
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

/**
 * 类别 → 图标组件（键集必须与 resourceCategory 的 CATEGORY_ICON 一致，测试钉住）。
 */
const CATEGORY_ICON_NODE: Record<string, ReactNode> = {
  "file-text": <FileTextOutlined />,
  "file-excel": <FileExcelOutlined />,
  "file-ppt": <FilePptOutlined />,
  "file-pdf": <FilePdfOutlined />,
  "file-word": <FileWordOutlined />,
  "file-image": <FileImageOutlined />,
  "file-video": <VideoCameraOutlined />,
  "file-archive": <BoxPlotOutlined />,
  "file-code": <CodeOutlined />,
  web: <GlobalOutlined />,
  chat: <MessageOutlined />,
  db: <DatabaseOutlined />,
  kb: <BookOutlined />,
  mcp: <ApiOutlined />,
};

/**
 * 大类 → 颜色。形状按细类走（Excel / PPT / PDF 各有各的形），颜色按大类走，
 * 一眼能分「文档 / 知识库 / 网页 / 数据源 / 工具」，同时避免整屏同图标。
 */
const GROUP_COLOR: Record<string, string> = {
  file: "#1677ff",
  web: "#52c41a",
  chat: "#2f54eb",
  db: "#13c2c2",
  kb: "#722ed1",
  mcp: "#fa8c16",
  other: "#8c8c8c",
};

/** 该条资源的类别（14 类之一）。 */
export function categoryOf(item: ChatResourceItem): string {
  return resolveCategory(item.kind, item.path);
}

/** 该条资源所属大类。 */
export function categoryGroupOf(item: ChatResourceItem): string {
  const category = categoryOf(item);
  return category.startsWith("file-") ? "file" : category;
}

/** 该条资源的图标（按细类取形状、按大类取颜色）。 */
export function categoryIconOf(item: ChatResourceItem, size?: number): ReactNode {
  const category = categoryOf(item);
  const group = categoryGroupOf(item);
  const glyph = CATEGORY_ICON_NODE[category] || CATEGORY_ICON_NODE.file;
  return (
    <span
      style={{
        color: GROUP_COLOR[group] || GROUP_COLOR.other,
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
 *   1. 台账角色是 producer 或导出件 → 产出
 *   2. kind = kb                   → 知识库
 *   3. kind = web                  → 网页
 *   4. 其余引用件（上传文件、工具、数据表）→ 引用
 * 只看台账 role + kind 两列，零推断。后续要细分（如「上传」「智能体引用」）
 * 只改这一处，三处渲染同时生效。
 */
export type ResourceSource = "produced" | "kb" | "web" | "reference";

export function sourceOf(item: ChatResourceItem): ResourceSource {
  if (item.role === "producer" || item.metadata?.export === true) return "produced";
  if (item.kind === "kb") return "kb";
  if (item.kind === "web") return "web";
  return "reference";
}

/** 来源标签文案（复用既有四语词条，零新增）。 */
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
