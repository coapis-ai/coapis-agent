/**
 * CoApisDeepThinking — wrapper around the library's DeepThinking component
 * that adds autoCloseOnFinish behavior + i18n title + hideThinking wiring.
 *
 * Behavior (2026-11-12 D2 拍板):
 * - hideThinking=false（详细模式默认）：starts EXPANDED (defaultOpen=true)，
 *   thinking 结束自动收起 (autoCloseOnFinish=true)，保持原有行为
 * - hideThinking=true：只显示折叠条（标题「思考已收起 · 展开」），
 *   默认收起、不自动展开；用户点击展开才显示内容
 * - title 走 i18n（chat.deepThinking），服务端下发 data.title 优先
 */
import React from "react";
import { useTranslation } from "react-i18next";
import {
  DeepThinking as LibraryDeepThinking,
  type IDeepThinking,
} from "@agentscope-ai/chat";
import { useChatDisplayConfig } from "./SimplifiedResponseCard";

const CoApisDeepThinking: React.FC<{ data: IDeepThinking }> = ({ data }) => {
  const { t } = useTranslation();
  const config = useChatDisplayConfig();
  if (!data) return null;
  const hideThinking = config.hideThinking;
  return (
    <LibraryDeepThinking
      defaultOpen={hideThinking ? false : true}
      autoCloseOnFinish={hideThinking ? false : true}
      title={
        hideThinking
          ? t("chat.deepThinkingCollapsed", "思考已收起 · 展开")
          : data.title || t("chat.deepThinking", "深度思考")
      }
      loading={data.loading}
      content={data.content}
      className={data.className}
      maxHeight={data.maxHeight}
    />
  );
};

export default CoApisDeepThinking;
