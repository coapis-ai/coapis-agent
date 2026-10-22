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
  /**
   * 指定展开根（相对 files 根，如 `/2026-10/2026-10-22_季度报告`）。
   * 「本会话目录」入口用它，避免用户从我的空间一层层点进自己的会话目录。
   */
  rootPath?: string | null;
}

export default function CascadePickerModal(props: CascadePickerModalProps) {
  const { open, mode, onClose, checked, onToggle, rootPath } = props;
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
          // 根节点是导航容器，勾选它没有可引用对象（见 ResourcePlusMenu 同注释）
          selectable: false,
        },
      ];
    }
    if (mode === "files" && rootPath) {
      // 从指定目录展开：标题用目录名，用户一眼看出这是"哪次会话的目录"
      const name = rootPath.replace(/\/+$/, "").split("/").pop() || rootPath;
      return [
        {
          key: `files:${rootPath}`,
          name,
          kind: "group" as const,
          selectable: false,
        },
      ];
    }
    return mode === "knowledge"
      ? [{ key: KB_ROOT_KEY, name: t("resourceMenu.knowledge"), kind: "group" as const, selectable: false }]
      : [{ key: SPACE_ROOT_KEY, name: t("resourceMenu.mySpace"), kind: "group" as const, selectable: false }];
  }, [kw, mode, t, rootPath]);

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
          : rootPath
            ? t("resourceMenu.sessionDir", "本会话目录")
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
