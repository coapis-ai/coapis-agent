/**
 * Recommendation card component.
 */

import React from "react";
import { Card, Typography } from "antd";
import { RightOutlined } from "@ant-design/icons";
import type { RecommendationItem, RecommendationLayout } from "./types";

const { Text } = Typography;

interface RecommendationCardProps {
  item: RecommendationItem;
  layout?: RecommendationLayout;
  onClick?: (item: RecommendationItem) => void;
  onDismiss?: (item: RecommendationItem) => void;
}

const RecommendationCard: React.FC<RecommendationCardProps> = ({
  item,
  layout = "grid",
  onClick,
  onDismiss: _onDismiss,
}) => {
  const handleClick = () => {
    onClick?.(item);
  };

  // Grid layout (default)
  if (layout === "grid") {
    return (
      <Card
        hoverable
        size="small"
        onClick={handleClick}
        style={{
          height: "100%",
          cursor: "pointer",
          transition: "all 0.2s",
        }}
        styles={{
          body: {
            padding: "12px 16px",
            display: "flex",
            alignItems: "center",
            gap: 12,
          },
        }}
      >
        <div style={{ fontSize: 24, flexShrink: 0 }}>{item.icon}</div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <Text
            strong
            style={{
              fontSize: 14,
              display: "block",
              overflow: "hidden",
              textOverflow: "ellipsis",
              whiteSpace: "nowrap",
            }}
          >
            {item.title}
          </Text>
          <Text
            type="secondary"
            style={{
              fontSize: 12,
              display: "block",
              overflow: "hidden",
              textOverflow: "ellipsis",
              whiteSpace: "nowrap",
            }}
          >
            {item.description}
          </Text>
        </div>
        <RightOutlined
          style={{ color: "#bbb", fontSize: 12, flexShrink: 0 }}
        />
      </Card>
    );
  }

  // List layout
  if (layout === "list") {
    return (
      <div
        onClick={handleClick}
        style={{
          display: "flex",
          alignItems: "center",
          gap: 12,
          padding: "8px 12px",
          borderRadius: 8,
          cursor: "pointer",
          transition: "background 0.2s",
        }}
        onMouseEnter={(e) => {
          e.currentTarget.style.background = "#f5f5f5";
        }}
        onMouseLeave={(e) => {
          e.currentTarget.style.background = "transparent";
        }}
      >
        <div style={{ fontSize: 20, flexShrink: 0 }}>{item.icon}</div>
        <Text
          style={{
            fontSize: 14,
            flex: 1,
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
          }}
        >
          {item.title}
        </Text>
        <RightOutlined style={{ color: "#bbb", fontSize: 12 }} />
      </div>
    );
  }

  // Carousel layout (simplified for now)
  return (
    <Card
      hoverable
      onClick={handleClick}
      style={{
        width: 200,
        cursor: "pointer",
      }}
      styles={{
        body: {
          padding: 16,
          textAlign: "center",
        },
      }}
    >
      <div style={{ fontSize: 32, marginBottom: 8 }}>{item.icon}</div>
      <Text strong style={{ display: "block", marginBottom: 4 }}>
        {item.title}
      </Text>
      <Text type="secondary" style={{ fontSize: 12 }}>
        {item.description}
      </Text>
    </Card>
  );
};

export default RecommendationCard;
