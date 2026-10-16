import { useMemo, useState } from "react";
import { Modal, Input } from "antd";
import { useTranslation } from "react-i18next";
import CascadeMenu from "@/components/CascadeMenu/CascadeMenu";
import type { CascadeNode } from "@/components/CascadeMenu/CascadeMenu";
import { useNarrow } from "@/components/CascadeMenu/useNarrow";
import { cascadeLoad, SPACE_ROOT_KEY, KB_ROOT_KEY } from "./cascadeAdapters";
import styles from "./resource.module.less";

/**
 * 资源浮层（搜索态）—— 跨目录检索与知识库选择。
 *
 * 菜单层不做检索（D3：跨目录检索需要搜索框，属于浮层）。浮层同样用通用
 * CascadeMenu 渲染：无关键词时是「我的空间 / 关联知识」的目录级联，输入
 * 关键词后自动展开结果列。勾选即生效（D4），无确认按钮。
 */

export interface CascadePickerModalProps {
  open: boolean;
  mode: "files" | "knowledge";
  onClose: () => void;
  checked: Set<string>;
  onToggle: (node: CascadeNode) => void;
}

export default function CascadePickerModal(props: CascadePickerModalProps) {
  const { open, mode, onClose, checked, onToggle } = props;
  const { t } = useTranslation();
  const narrow = useNarrow();
  const [kw, setKw] = useState("");

  const roots = useMemo(() => {
    const k = kw.trim();
    if (k) {
      return [
        {
          key: `search:${k}`,
          name: t("resourcePicker.searchResults", "搜索结果"),
          kind: "group" as const,
        },
      ];
    }
    return mode === "knowledge"
      ? [{ key: KB_ROOT_KEY, name: t("resourceMenu.knowledge"), kind: "group" as const }]
      : [{ key: SPACE_ROOT_KEY, name: t("resourceMenu.mySpace"), kind: "group" as const }];
  }, [kw, mode, t]);

  const load = useMemo(
    () =>
      (node: CascadeNode, force?: boolean) => cascadeLoad(node, undefined, force),
    [],
  );

  return (
    <Modal
      open={open}
      onCancel={onClose}
      footer={null}
      width={narrow ? "92vw" : 820}
      title={
        mode === "knowledge"
          ? t("resourceMenu.knowledge")
          : t("resourceMenu.mySpace")
      }
    >
      <div className={styles.modalBody}>
        {mode === "files" && (
          <Input
            allowClear
            autoFocus
            value={kw}
            onChange={(e) => setKw(e.target.value)}
            placeholder={t(
              "resourcePicker.searchPlaceholder",
              "搜索全部文件（按文件名/路径）…",
            )}
            style={{ marginBottom: 8 }}
          />
        )}
        <div style={{ display: "flex" }}>
          <CascadeMenu
            roots={roots}
            load={load}
            checked={checked}
            onToggle={onToggle}
            height={narrow ? 320 : 420}
            rootWidth={narrow ? 180 : 200}
            narrow={narrow}
            autoOpenRoot={kw.trim().length > 0}
          />
        </div>
      </div>
    </Modal>
  );
}
