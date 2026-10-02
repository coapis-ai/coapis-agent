import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";

/**
 * 全局模型选择（M4：模型选择移入个人下拉）。
 * - 选中结果持久化到 localStorage，跨页面共享（ProfileButton 写入，Chat 芯片条展示）。
 * - 后端暂不支持按消息覆盖模型，model_id 仅随 biz_params 预留透传。
 */
export interface ModelChoice {
  id: string | null;
  name: string | null;
}

const STORAGE_KEY = "coapis.modelChoice.v1";
const EMPTY: ModelChoice = { id: null, name: null };

interface ModelChoiceCtx {
  choice: ModelChoice;
  setChoice: (c: ModelChoice) => void;
  clearChoice: () => void;
}

const Ctx = createContext<ModelChoiceCtx>({
  choice: EMPTY,
  setChoice: () => {},
  clearChoice: () => {},
});

function loadInitial(): ModelChoice {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) {
      const parsed = JSON.parse(raw);
      if (parsed && parsed.id) {
        return { id: String(parsed.id), name: parsed.name ? String(parsed.name) : String(parsed.id) };
      }
    }
  } catch {
    /* ignore */
  }
  return EMPTY;
}

export function ModelChoiceProvider({ children }: { children: React.ReactNode }) {
  const [choice, setChoiceState] = useState<ModelChoice>(loadInitial);

  useEffect(() => {
    try {
      if (choice.id) {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(choice));
      } else {
        localStorage.removeItem(STORAGE_KEY);
      }
    } catch {
      /* ignore */
    }
  }, [choice]);

  const setChoice = useCallback((c: ModelChoice) => setChoiceState(c), []);
  const clearChoice = useCallback(() => setChoiceState(EMPTY), []);

  const value = useMemo(() => ({ choice, setChoice, clearChoice }), [choice, setChoice, clearChoice]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useModelChoice() {
  return useContext(Ctx);
}
