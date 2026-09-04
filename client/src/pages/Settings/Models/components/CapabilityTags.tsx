import { Tag } from "@agentscope-ai/design";
import {
  AppstoreOutlined,
  EyeOutlined,
  VideoCameraOutlined,
  FileTextOutlined,
  QuestionCircleOutlined,
} from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import type { ModelInfo } from "@/api/types";

export const tagColors = (isDark: boolean) => ({
  multimodal: {
    backgroundColor: isDark ? "rgba(24,144,255,0.15)" : "#e6f7ff",
    color: "#1890ff",
    borderColor: isDark ? "rgba(24,144,255,0.3)" : "#91d5ff",
  },
  vision: {
    backgroundColor: isDark ? "rgba(19,194,194,0.15)" : "#e6fffb",
    color: "#13c2c2",
    borderColor: isDark ? "rgba(19,194,194,0.3)" : "#87e8de",
  },
  video: {
    backgroundColor: isDark ? "rgba(114,46,211,0.15)" : "#f9f0ff",
    color: "#722ed1",
    borderColor: isDark ? "rgba(114,46,211,0.3)" : "#d3adf7",
  },
  text: {
    backgroundColor: isDark ? "rgba(255,255,255,0.1)" : "#f5f5f5",
    color: isDark ? "rgba(255,255,255,0.65)" : "#595959",
    borderColor: isDark ? "rgba(255,255,255,0.15)" : "#d9d9d9",
  },
  notProbed: {
    backgroundColor: isDark ? "rgba(255,255,255,0.1)" : "#f5f5f5",
    color: isDark ? "rgba(255,255,255,0.65)" : "#8c8c8c",
    borderColor: isDark ? "rgba(255,255,255,0.15)" : "#d9d9d9",
  },
  builtin: {
    backgroundColor: isDark ? "rgba(82,196,26,0.15)" : "#f6ffed",
    color: "#52c41a",
    borderColor: isDark ? "rgba(82,196,26,0.3)" : "#b7eb8f",
  },
  free: {
    backgroundColor: isDark ? "rgba(82,196,26,0.15)" : "#f6ffed",
    color: "#52c41a",
    borderColor: isDark ? "rgba(82,196,26,0.3)" : "#b7eb8f",
  },
  userAdded: {
    backgroundColor: isDark ? "rgba(24,144,255,0.15)" : "#e6f7ff",
    color: "#1890ff",
    borderColor: isDark ? "rgba(24,144,255,0.3)" : "#91d5ff",
  },
});

export function CapabilityTags({
  model,
  isDark,
}: {
  model: ModelInfo;
  isDark: boolean;
}) {
  const { t } = useTranslation();
  const c = tagColors(isDark);
  if (model.supports_image && model.supports_video) {
    return (
      <Tag style={{ fontSize: 11, marginRight: 4, ...c.multimodal }}>
        <AppstoreOutlined style={{ fontSize: 10, marginRight: 3 }} />
        {t("models.tagMultimodal", "多模态")}
      </Tag>
    );
  }
  if (model.supports_image) {
    return (
      <Tag style={{ fontSize: 11, marginRight: 4, ...c.vision }}>
        <EyeOutlined style={{ fontSize: 10, marginRight: 3 }} />
        {t("models.tagVision", "视觉")}
      </Tag>
    );
  }
  if (model.supports_video) {
    return (
      <Tag style={{ fontSize: 11, marginRight: 4, ...c.video }}>
        <VideoCameraOutlined style={{ fontSize: 10, marginRight: 3 }} />
        {t("models.tagVideo", "视频")}
      </Tag>
    );
  }
  if (model.supports_multimodal === false) {
    return (
      <Tag style={{ fontSize: 11, marginRight: 4, ...c.text }}>
        <FileTextOutlined style={{ fontSize: 10, marginRight: 3 }} />
        {t("models.tagText", "文本")}
      </Tag>
    );
  }
  return (
    <Tag style={{ fontSize: 11, marginRight: 4, ...c.notProbed }}>
      <QuestionCircleOutlined style={{ fontSize: 10, marginRight: 3 }} />
      {t("models.tagNotProbed", "未检测")}
    </Tag>
  );
}
