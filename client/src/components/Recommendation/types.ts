/**
 * Recommendation system types.
 */

export interface RecommendationItem {
  id: string;
  title: string;
  description: string;
  prompt: string;
  category: "skill" | "history" | "context" | "popularity";
  icon: string;
  score: number;
  metadata?: Record<string, any>;
}

export interface RecommendationMeta {
  count: number;
  generated_at: string;
  scene?: string;
  strategies_used?: string[];
  total_candidates?: number;
  unique_candidates?: number;
}

export interface RecommendationResponse {
  recommendations: RecommendationItem[];
  meta: RecommendationMeta;
}

export interface RecommendationScene {
  scene: string;
  max_items: number;
  strategies: string[];
  layout: "grid" | "list" | "carousel";
}

export type RecommendationLayout = "grid" | "list" | "carousel";

export interface RecommendationProps {
  /** Scene identifier */
  scene?: string;
  /** Maximum items to show */
  limit?: number;
  /** Layout mode */
  layout?: RecommendationLayout;
  /** Filter by category */
  category?: string;
  /** Callback when recommendation is clicked */
  onRecommend?: (prompt: string, item: RecommendationItem) => void;
  /** Callback when recommendation is dismissed */
  onDismiss?: (item: RecommendationItem) => void;
  /** Custom className */
  className?: string;
  /** Show loading state */
  loading?: boolean;
}
