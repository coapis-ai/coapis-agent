import { useEffect, useMemo, useState } from "react";
import { Dropdown, Menu, message } from "antd";
import {
  CheckCircleFilled,
  DeploymentUnitOutlined,
  DownOutlined,
} from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import { useModelPrefs, type ModelSlot } from "../../lib/modelChoice";
import { userModelPrefsApi } from "../../api/modules/user_model_prefs";
import styles from "./ModelChips.module.less";

/** /models/available 返回的模型条目（带 model_type） */
interface AvailableModel {
  id: string;
  name: string;
  provider_id: string;
  provider_name: string;
  model_type: string;
}

type ChipKind = "chat";

const CHIP_META: Record<
  ChipKind,
  {
    icon: React.ReactNode;
    labelKey: string;
    labelDefault: string;
    tipKey: string;
    tipDefault: string;
    type: string;
  }
> = {
  chat: {
    icon: <DeploymentUnitOutlined />,
    labelKey: "chat.modelChips.llm",
    labelDefault: "聊天模型",
    tipKey: "chat.modelChips.tipChat",
    tipDefault: "选择聊天模型（对你的所有智能体与场景生效）",
    type: "chat",
  },
};

/**
 * 聊天输入区的模型芯片（仅聊天模型）。
 *
 * - 单一入口：芯片 + 下拉，按 provider 分组列出可用聊天模型。
 * - 选择即写入用户全局偏好（后端 /user/model-prefs），变更会热重载智能体。
 * - 未设置时显示"系统默认"，点击"系统默认"项清除偏好（回退智能体/全局默认）。
 * - 嵌入/重排序模型不在此提供：二者运行时无消费者（社区版记忆是关键词+LLM
 *   重排，重排跟随聊天模型；企业版嵌入走 KB 配置与全局默认槽位），且换嵌入
 *   模型会让已入库向量失效，属系统级/库级资源，不作用户级偏好。
 */
export function ModelChips() {
  const { t } = useTranslation();
  const { chat, setChat } = useModelPrefs();
  const [models, setModels] = useState<AvailableModel[]>([]);
  const [openKind, setOpenKind] = useState<ChipKind | null>(null);

  useEffect(() => {
    let cancelled = false;
    userModelPrefsApi
      .getAvailableModels()
      .then((data: any) => {
        if (cancelled) return;
        const list: AvailableModel[] = (data?.global_models ?? []).filter(
          (m: any) => m && m.id && m.provider_id,
        );
        setModels(list);
      })
      .catch(() => {
        /* 拉取失败：芯片仍显示当前偏好名，下拉为空 */
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const slots: Record<ChipKind, ModelSlot> = { chat };
  const setters: Record<ChipKind, (s: ModelSlot) => Promise<void>> = {
    chat: setChat,
  };

  /** 按类型分组，再按 provider 分组，避免同名模型来自不同 provider 时选不清 */
  const grouped = useMemo(() => {
    const byType: Record<string, AvailableModel[]> = {};
    for (const m of models) {
      const ty = m.model_type || "chat";
      (byType[ty] ??= []).push(m);
    }
    const out: Record<string, Record<string, AvailableModel[]>> = {};
    for (const [ty, list] of Object.entries(byType)) {
      const byProvider: Record<string, AvailableModel[]> = {};
      for (const m of list) {
        const key = m.provider_name || m.provider_id;
        (byProvider[key] ??= []).push(m);
      }
      out[ty] = byProvider;
    }
    return out;
  }, [models]);

  const handleSelect = async (kind: ChipKind, model: AvailableModel | null) => {
    const slot: ModelSlot = model
      ? { providerId: model.provider_id, model: model.id, name: model.name }
      : { providerId: null, model: null, name: null };
    try {
      await setters[kind](slot);
      // 让聊天页刷新多模态能力提示（芯片换模型后"图片/视频"标签要跟着变）
      window.dispatchEvent(new CustomEvent("model-switched"));
    } catch (e: any) {
      message.error(
        e?.message ?? t("chat.modelChips.saveFailed", "保存模型偏好失败"),
      );
    }
  };

  const renderChip = (kind: ChipKind) => {
    const meta = CHIP_META[kind];
    const slot = slots[kind];
    const byProvider = grouped[meta.type] ?? {};
    const hasModels = Object.keys(byProvider).length > 0;

    const items: any[] = [
      {
        key: "__default__",
        label: (
          <span style={{ color: "rgba(0,0,0,0.55)" }}>
            {t("chat.modelChips.systemDefault", "系统默认")}
            {!slot.model && (
              <CheckCircleFilled
                style={{ color: "#52c41a", marginLeft: 6, fontSize: 11 }}
              />
            )}
          </span>
        ),
      },
    ];
    for (const [providerName, list] of Object.entries(byProvider)) {
      items.push({
        key: `group-${providerName}`,
        label: (
          <span style={{ color: "rgba(0,0,0,0.45)", fontSize: 12 }}>
            {providerName}
          </span>
        ),
        disabled: true,
      });
      for (const m of list) {
        const selected = slot.model === m.id && slot.providerId === m.provider_id;
        items.push({
          key: `${m.provider_id}::${m.id}`,
          label: (
            <span>
              {m.name}
              {selected && (
                <CheckCircleFilled
                  style={{ color: "#52c41a", marginLeft: 6, fontSize: 11 }}
                />
              )}
            </span>
          ),
        });
      }
    }

    const displayName = slot.model ? (slot.name ?? slot.model) : null;

    return (
      <Dropdown
        key={kind}
        trigger={["click"]}
        open={openKind === kind}
        onOpenChange={(v) => setOpenKind(v ? kind : null)}
        dropdownRender={() => (
          <Menu
            style={{ maxHeight: 320, overflowY: "auto" }}
            items={items}
            onClick={({ key }) => {
              if (key === "__default__") {
                void handleSelect(kind, null);
              } else if (key.startsWith("group-")) {
                return;
              } else {
                const [pid, mid] = key.split("::");
                const model = models.find(
                  (m) => m.provider_id === pid && m.id === mid,
                );
                if (model) void handleSelect(kind, model);
              }
              setOpenKind(null);
            }}
          />
        )}
      >
        {/* 用原生 title 而不是 antd Tooltip：Tooltip 不会把 Dropdown 的 onClick
            透传给子元素，包在中间会让芯片点击打不开下拉。 */}
        <span
          className={styles.chip}
          title={
            hasModels
              ? t(meta.tipKey, meta.tipDefault)
              : t("chat.modelChips.noModels", "暂无可用模型，请先在设置中配置")
          }
        >
          <span className={styles.chipIcon}>{meta.icon}</span>
          <span className={styles.chipLabel}>
            {t(meta.labelKey, meta.labelDefault)}
          </span>
          <span className={styles.chipValue}>
            {displayName ?? t("chat.modelChips.systemDefault", "系统默认")}
          </span>
          <DownOutlined className={styles.chipCaret} />
        </span>
      </Dropdown>
    );
  };

  return (
    <div className={styles.chips}>
      {renderChip("chat")}
    </div>
  );
}

export default ModelChips;
