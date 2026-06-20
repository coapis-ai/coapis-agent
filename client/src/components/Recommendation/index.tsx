/**
 * Recommendation component - Main entry point.
 * 
 * Usage:
 *   <Recommendation scene="chat_welcome" limit={6} onRecommend={handleRecommend} />
 */

import React from "react";
import { Spin, Empty, Typography } from "antd";
import { useRecommendations } from "./hooks";
import RecommendationCard from "./RecommendationCard";
import type { RecommendationProps, RecommendationItem, RecommendationLayout } from "./types";

const { Text } = Typography;

const Recommendation: React.FC<RecommendationProps> = ({
  scene = "chat_welcome",
  limit = 6,
  layout = "grid",
  category,
  onRecommend,
  onDismiss,
  className,
  loading: externalLoading,
}) => {
  const {
    recommendations,
    loading: internalLoading,
    error,
  } = useRecommendations({
    scene,
    limit,
    category,
  });

  const loading = externalLoading || internalLoading;

  const handleClick = (item: RecommendationItem) => {
    onRecommend?.(item.prompt, item);
  };

  if (loading && recommendations.length === 0) {
    return (
      <div style={{ textAlign: "center", padding: "20px 0" }}>
        <Spin size="small" />
      </div>
    );
  }

  if (error && recommendations.length === 0) {
    // Silently fail, don't show error to user
    return null;
  }

  if (recommendations.length === 0) {
    return null;
  }

  // Grid layout
  if (layout === "grid") {
    return (
      <div className={className}>
        <div style={{ marginBottom: 8, color: "#999", fontSize: 12 }}>
          {recommendations.some(r => r.category === "history")
            ? "基于你的使用习惯"
            : "为你推荐"}
        </div>
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))",
            gap: 12,
          }}
        >
          {recommendations.map((item) => (
            <RecommendationCard
              key={item.id}
              item={item}
              layout="grid"
              onClick={handleClick}
            />
          ))}
        </div>
      </div>
    );
  }

  // List layout
  if (layout === "list") {
    return (
      <div className={className}>
        {recommendations.map((item) => (
          <RecommendationCard
            key={item.id}
            item={item}
            layout="list"
            onClick={handleClick}
          />
        ))}
      </div>
    );
  }

  // Carousel layout
  return (
    <div
      className={className}
      style={{
        display: "flex",
        gap: 16,
        overflowX: "auto",
        padding: "8px 0",
      }}
    >
      {recommendations.map((item) => (
        <RecommendationCard
          key={item.id}
          item={item}
          layout="carousel"
          onClick={handleClick}
        />
      ))}
    </div>
  );
};

export default Recommendation;
export { RecommendationCard };
export { useRecommendations, useRecommendationFeedback } from "./hooks";
export type {
  RecommendationItem,
  RecommendationProps,
  RecommendationScene,
  RecommendationLayout,
} from "./types";
