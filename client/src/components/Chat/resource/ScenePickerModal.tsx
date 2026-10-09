import { useEffect, useState } from "react";
import { Modal, Spin } from "antd";
import { useTranslation } from "react-i18next";
import api from "@/api";
import ScenePicker from "@/components/ScenePicker";
import type { SceneConfig } from "@/pages/Workbench/types";
import styles from "./resource.module.less";

interface SceneListResponse {
  scenes?: SceneConfig[];
}

interface ScenePickerModalProps {
  open: boolean;
  onClose: () => void;
  /** 选中场景：进入该场景（由调用方决定浮窗/全屏行为），选中后自动关闭弹窗 */
  onPick: (scene: SceneConfig) => void;
  /** 当前场景 id：卡片高亮 + 「当前」标记 + 置顶 */
  currentSceneId?: string;
  /** 浮窗模式：弹窗限定在浮窗容器内（不覆盖整个浏览器） */
  embedded?: boolean;
}

const FLOATING_SELECTOR = "[data-floating-window]";

function getFloatingEl(): HTMLElement | null {
  return document.querySelector(FLOATING_SELECTOR) as HTMLElement | null;
}

/**
 * 「切换场景」弹窗 —— 复用共享 ScenePicker（搜索 + 标签 + 卡片栅格）。
 * 选中场景后关闭弹窗并进入该场景的会话（不弹新窗）。
 * 浮窗模式下弹窗渲染在浮窗容器内，尺寸随浮窗自适应。
 */
export default function ScenePickerModal(props: ScenePickerModalProps) {
  const { t } = useTranslation();
  const { open, onClose, onPick, currentSceneId, embedded = false } = props;

  const [scenes, setScenes] = useState<SceneConfig[]>([]);
  const [loading, setLoading] = useState(false);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    if (!open || loaded) return;
    setLoading(true);
    api
      .get<SceneListResponse>("/scenes")
      .then((resp) => {
        const list = Array.isArray(resp)
          ? (resp as unknown as SceneConfig[])
          : Array.isArray(resp?.scenes)
            ? resp.scenes!
            : [];
        setScenes(list.filter((s) => (s.status ?? "active") === "active"));
        setLoaded(true);
      })
      .catch(() => {
        setScenes([]);
        setLoaded(true);
      })
      .finally(() => setLoading(false));
  }, [open, loaded]);

  // 浮窗模式：弹窗尺寸随浮窗容器自适应
  const container = open ? getFloatingEl() : null;
  const width = container
    ? Math.min(680, Math.max(320, container.clientWidth - 24))
    : 720;
  const bodyMax = container
    ? Math.max(200, Math.min(420, container.clientHeight - 180))
    : Math.round(window.innerHeight * 0.6);

  return (
    <Modal
      title={t("resourceMenu.scene")}
      open={open}
      onCancel={onClose}
      width={width}
      footer={null}
      destroyOnClose
      centered
      getContainer={
        embedded
          ? () => getFloatingEl() ?? (document.body as HTMLElement)
          : undefined
      }
      wrapClassName={embedded ? styles.embeddedWrap : undefined}
      styles={{
        mask: embedded ? { position: "absolute", inset: 0 } : undefined,
        body: { paddingTop: 8 },
      }}
    >
      <Spin spinning={loading}>
        <ScenePicker
          scenes={scenes}
          onSelect={(scene) => {
            onPick(scene);
            onClose();
          }}
          currentSceneId={currentSceneId}
          maxHeight={bodyMax}
          cols={{ xs: 24, sm: 12, md: 12, lg: 12 }}
          autoFocusSearch
        />
      </Spin>
    </Modal>
  );
}
