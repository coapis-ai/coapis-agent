import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { chatApi } from "../../../api/modules/chat";
import type { ChatResourceItem } from "../../../api/modules/chat";

/**
 * 会话资源台账（方案 §12.4 的**唯一数据源**）
 * ---------------------------------------------------------------------------
 * 台账端点 GET /chats/{id}/resources 是 L1 产出卡 / L2 资源条 / L3 资源 Tab
 * 三层共用的同一份数据。以前 L2 自己拉、L1 只看消息事件里的实时资源（没有
 * 大小/时间/版本），三层各说各话。这里把拉取上提到会话级，三层共用一份：
 *
 *   - L2 资源条：直接用 items/total（受控模式，不再自己发请求）
 *   - L3 资源 Tab：自己分页，仍走同一端点
 *   - L1 产出卡：按 path 反查 meta（大小 / 更新时间 / 交付版本）
 *
 * 路径归一：台账里是绝对路径，消息事件里可能是绝对 / file:// / 相对路径，
 * 反查前统一去掉协议前缀与首斜杠，避免「同一文件两条记录」。
 */

/** 台账路径 → 可比较的键。 */
export function ledgerKey(path: string): string {
  return String(path || "")
    .replace(/^file:\/\//, "")
    .replace(/^\/+/, "")
    .trim();
}

/* ------------------------------------------------------------------ *
 * 会话级共享缓存（实施细则 B4「切会话减负」第 1 项）
 * ------------------------------------------------------------------ *
 * 一次切会话原本要发两次 GET /chats/{id}/resources：台账钩子取 200 条喂
 * L1/L2，左栏面板自己取 40 条。两次请求打的是同一份数据。这里把它上提成
 * 模块级共享缓存：同一 chatId 只发一次（在途去重），5 秒内的重复请求直接
 * 命中缓存，左栏面板从同一份结果里切片。
 *
 * 缓存只存「第一页 200 条」这一种形状，切片由消费方自己做，避免键里带
 * limit 又退化成每处一发。条目上限 50 个会话，超出按写入顺序淘汰最旧的。
 */
const SHARED_LIMIT = 200;
const SHARED_TTL_MS = 5000;
const SHARED_MAX_CHATS = 50;

interface SharedEntry {
  items: ChatResourceItem[];
  total: number;
  ts: number;
}

const sharedCache = new Map<string, SharedEntry>();
const sharedInflight = new Map<string, Promise<SharedEntry>>();

export function getChatResourcesShared(
  chatId: string,
  force = false,
): Promise<SharedEntry> {
  const hit = sharedCache.get(chatId);
  if (!force && hit && Date.now() - hit.ts < SHARED_TTL_MS) {
    // 命中即回：把它重新放到 Map 尾部，维持「最近使用」顺序
    sharedCache.delete(chatId);
    sharedCache.set(chatId, hit);
    return Promise.resolve(hit);
  }
  const pending = sharedInflight.get(chatId);
  if (pending) return pending;

  const p = chatApi
    .listChatResources(chatId, SHARED_LIMIT, 0)
    .then((res) => {
      const entry: SharedEntry = {
        items: res.items || [],
        total: res.total || 0,
        ts: Date.now(),
      };
      sharedCache.set(chatId, entry);
      while (sharedCache.size > SHARED_MAX_CHATS) {
        const oldest = sharedCache.keys().next().value as string | undefined;
        if (oldest === undefined) break;
        sharedCache.delete(oldest);
      }
      return entry;
    })
    .finally(() => {
      sharedInflight.delete(chatId);
    });
  sharedInflight.set(chatId, p);
  return p;
}

/** 丢弃某会话的缓存（写入新资源后强制刷新用）；不传则清空。 */
export function invalidateChatResourcesShared(chatId?: string): void {
  if (chatId === undefined) sharedCache.clear();
  else sharedCache.delete(chatId);
}

export interface ChatResourceLedger {
  items: ChatResourceItem[];
  total: number;
  loading: boolean;
  reload: () => void;
  /** 按路径（任意写法）反查台账行；查不到返回 undefined */
  metaOf: (path: string) => ChatResourceItem | undefined;
}

export function useChatResourceLedger(
  chatId: string | undefined,
  refreshSignal = 0,
): ChatResourceLedger {
  const [items, setItems] = useState<ChatResourceItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [nonce, setNonce] = useState(0);
  const lastSignalRef = useRef<number | null>(null);

  const reload = useCallback(() => setNonce((n) => n + 1), []);

  useEffect(() => {
    if (!chatId) {
      setItems([]);
      setTotal(0);
      return;
    }
    let alive = true;
    setLoading(true);
    // 刷新信号「变化」才 force 穿透 TTL（挂载首帧命中缓存，与左栏面板共用一次请求）
    const changed =
      lastSignalRef.current !== null && refreshSignal !== lastSignalRef.current;
    lastSignalRef.current = refreshSignal;
    getChatResourcesShared(chatId, nonce > 0 || changed)
      .then((entry) => {
        if (!alive) return;
        setItems(entry.items);
        setTotal(entry.total);
      })
      .catch(() => {
        if (!alive) return;
        setItems([]);
        setTotal(0);
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [chatId, refreshSignal, nonce]);

  const index = useMemo(() => {
    const m = new Map<string, ChatResourceItem>();
    for (const it of items) m.set(ledgerKey(it.path), it);
    return m;
  }, [items]);

  const metaOf = useCallback(
    (path: string) => index.get(ledgerKey(path)),
    [index],
  );

  return { items, total, loading, reload, metaOf };
}
