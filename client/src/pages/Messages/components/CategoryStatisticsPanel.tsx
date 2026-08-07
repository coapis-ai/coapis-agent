import { Card, Tag } from "antd";

export interface CategoryStats {
  category_name: string;
  unread_count: number;
  read_count: number;
}

interface CategoryStatisticsPanelProps {
  categories: CategoryStats[];
  onCategoryClick?: (categoryName: string) => void;
}

export default function CategoryStatisticsPanel({ 
  categories, 
  onCategoryClick 
}: CategoryStatisticsPanelProps) {
  return (
    <Card title="常用分类及统计" style={{ marginBottom: 24 }}>
      <div style={{ display: "flex", gap: 16, flexWrap: "wrap" }}>
        {categories.map((cat) => (
          <Tag
            key={cat.category_name}
            color={cat.unread_count > 0 ? "red" : "default"}
            style={{ 
              cursor: onCategoryClick ? "pointer" : "default",
              padding: "4px 12px",
              fontSize: 14,
            }}
            onClick={() => onCategoryClick?.(cat.category_name)}
          >
            {cat.category_name}
            <span style={{ marginLeft: 8 }}>
              未读: {cat.unread_count} | 已读: {cat.read_count}
            </span>
          </Tag>
        ))}
      </div>
    </Card>
  );
}
