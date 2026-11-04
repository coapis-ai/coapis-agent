/**
 * 槽位图标表（JSX 必须住在 .tsx 里）。
 *
 * 拆出去的唯一理由：`modelSlots.ts` 是"槽位名单的单一来源"，纯数据；
 * 图标是 JSX，写在 .ts 里 tsc 直接语法报错（TS1005），构建挂。
 */
import {
  AudioOutlined,
  DatabaseOutlined,
  EyeOutlined,
  MessageOutlined,
  SwapOutlined,
} from "@ant-design/icons";
import type { DefaultSlot } from "./modelSlots";

export const SLOT_ICONS: Record<DefaultSlot, JSX.Element> = {
  chat: <MessageOutlined />,
  embedding: <DatabaseOutlined />,
  rerank: <SwapOutlined />,
  audio: <AudioOutlined />,
  vision: <EyeOutlined />,
  decision: <SwapOutlined />,
};
