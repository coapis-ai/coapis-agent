import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import {
  userModelPrefsApi,
  type ModelPrefsUpdate,
} from "../api/modules/user_model_prefs";
import { useUser } from "../contexts/UserContext";

/**
 * 用户全局模型偏好（D2：按用户全局生效，不分智能体/场景）。
 *
 * - 后端 /user/model-prefs 是权威存储；localStorage 只做首屏缓存，
 *   避免刷新页面时芯片闪空。
 * - 模型以 (provider_id, model) 成对存储：同名模型可能来自不同 provider
 *   （dev 实测 a3/A3 与 local3-new/A3 并存），只存模型名会选错 provider。
 * - 聊天模型变更后后端会热重载智能体，无需重启服务。
 * - 只保留聊天模型：嵌入/重排序无运行时消费者，且换嵌入模型会让已入库
 *   向量失效，属系统级/库级资源，不作用户级偏好。
 */
export interface ModelSlot {
  providerId: string | null;
  model: string | null;
  /** 展示名；后端只存模型 id，展示时优先用 available 列表里的 model_name */
  name: string | null;
}

const EMPTY_SLOT: ModelSlot = { providerId: null, model: null, name: null };

const STORAGE_KEY = "coapis.modelChoice.v1";

function loadCache(): ModelSlot {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return EMPTY_SLOT;
    const parsed = JSON.parse(raw);
    // 兼容旧缓存（{chat:{...}} 与 {id, name} 两种形态）
    const src = parsed.chat ?? {
      providerId: parsed.providerId,
      model: parsed.id,
      name: parsed.name,
    };
    return src && src.model
      ? {
          providerId: src.providerId ?? null,
          model: String(src.model),
          name: src.name ? String(src.name) : String(src.model),
        }
      : EMPTY_SLOT;
  } catch {
    return EMPTY_SLOT;
  }
}

function saveCache(slot: ModelSlot) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ chat: slot }));
  } catch {
    /* ignore */
  }
}

interface ModelChoiceCtx {
  chat: ModelSlot;
  loading: boolean;
  /** 设置聊天模型（providerId + model 成对写入，后端热重载智能体） */
  setChat: (slot: ModelSlot) => Promise<void>;
  /** 展示名回填：从 available 列表拿到 model_name 后补进芯片显示 */
  displayName: (slot: ModelSlot) => string;
}

const Ctx = createContext<ModelChoiceCtx>({
  chat: EMPTY_SLOT,
  loading: true,
  setChat: async () => {},
  displayName: (slot) => slot.name ?? slot.model ?? "",
});

export function ModelChoiceProvider({ children }: { children: React.ReactNode }) {
  const [chat, setChatState] = useState<ModelSlot>(loadCache);
  const [loading, setLoading] = useState(true);
  const { user } = useUser();

  // 首屏以后端为权威（localStorage 只是缓存）。
  // 依赖 user.username：偏好是按用户的，登录前拉取会拿到空值，登录/切换用户后必须重拉。
  useEffect(() => {
    if (!user?.username) return;
    let cancelled = false;
    userModelPrefsApi
      .getModelPrefs()
      .then((p) => {
        if (cancelled) return;
        const next: ModelSlot = p.default_model
          ? {
              providerId: p.default_provider_id ?? null,
              model: p.default_model,
              name: p.default_model,
            }
          : EMPTY_SLOT;
        setChatState(next);
        saveCache(next);
      })
      .catch(() => {
        /* 拉取失败保留缓存值，不阻塞聊天 */
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [user?.username]);

  const setChat = useCallback(
    async (slot: ModelSlot) => {
      setChatState(slot);
      saveCache(slot);
      const patch: ModelPrefsUpdate = {
        default_model: slot.model ?? "",
        default_provider_id: slot.providerId ?? "",
      };
      try {
        await userModelPrefsApi.updateModelPrefs(patch);
      } catch (e) {
        // 后端拒绝（provider/模型已失效）时回滚到后端现状
        console.error("保存模型偏好失败:", e);
        throw e;
      }
    },
    [],
  );

  const displayName = useCallback(
    (slot: ModelSlot) => slot.name ?? slot.model ?? "",
    [],
  );

  const value = useMemo(
    () => ({ chat, loading, setChat, displayName }),
    [chat, loading, setChat, displayName],
  );

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useModelPrefs() {
  return useContext(Ctx);
}
