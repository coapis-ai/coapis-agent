import { useCallback, useEffect, useRef, useState } from "react";

import type { ChatResourceItem } from "../../../api/modules/chat";
import {
  getChatResourcesShared,
  invalidateChatResourcesShared,
} from "./useChatResourceLedger";

export type ResourceStripScope = "chat" | "session";

export interface ScopedResources {
  items: ChatResourceItem[];
  total: number;
  loading: boolean;
  reload: (force?: boolean) => void;
}

/**
 * 按作用域订阅台账（右侧栏资源条用：上半区 session、下半区 chat）。
 *
 * 复用同一份共享缓存/在途去重，不自己发请求 —— 台账永远只有一份数。
 * `refreshSignal` 自增即强制刷新；聊天页 200ms 轮询不会多打接口。
 */
export function useScopedResources(
  chatId: string | undefined,
  scope: ResourceStripScope,
  refreshSignal = 0,
): ScopedResources {
  const [items, setItems] = useState<ChatResourceItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const alive = useRef(true);

  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);

  const load = useCallback(
    async (force = false) => {
      if (!chatId) {
        setItems([]);
        setTotal(0);
        return;
      }
      setLoading(true);
      try {
        const entry = await getChatResourcesShared(chatId, force, scope);
        if (!alive.current) return;
        setItems(entry.items);
        setTotal(entry.total);
      } catch {
        if (alive.current) {
          setItems([]);
          setTotal(0);
        }
      } finally {
        if (alive.current) setLoading(false);
      }
    },
    [chatId, scope],
  );

  // 作用域/会话切换：先亮出已有缓存，再补拉
  useEffect(() => {
    if (!chatId) {
      setItems([]);
      setTotal(0);
      return;
    }
    const cached = getChatResourcesShared(chatId, false, scope);
    let mounted = true;
    cached
      .then((entry) => {
        if (!mounted) return;
        setItems(entry.items);
        setTotal(entry.total);
      })
      .catch(() => {
        if (mounted) {
          setItems([]);
          setTotal(0);
        }
      });
    return () => {
      mounted = false;
    };
  }, [chatId, scope]);

  // 外部刷新信号（聊天页「刷新」按钮、资源变更后）
  useEffect(() => {
    if (!refreshSignal) return;
    void load(true);
  }, [refreshSignal, load]);

  return { items, total, loading, reload: load };
}

export { invalidateChatResourcesShared };
