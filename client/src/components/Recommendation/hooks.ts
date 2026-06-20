/**
 * Recommendation system hooks.
 */

import { useState, useEffect, useCallback } from "react";
import { getApiUrl } from "../../api/config";
import { buildAuthHeaders } from "../../api/authHeaders";
import type {
  RecommendationItem,
  RecommendationResponse,
} from "./types";

interface UseRecommendationsOptions {
  scene?: string;
  limit?: number;
  category?: string;
  enabled?: boolean;
}

interface UseRecommendationsResult {
  recommendations: RecommendationItem[];
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
}

/**
 * Hook to fetch recommendations.
 */
export function useRecommendations({
  scene = "chat_welcome",
  limit = 6,
  category,
  enabled = true,
}: UseRecommendationsOptions = {}): UseRecommendationsResult {
  const [recommendations, setRecommendations] = useState<RecommendationItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchRecommendations = useCallback(async () => {
    if (!enabled) return;

    setLoading(true);
    setError(null);

    try {
      const params = new URLSearchParams({
        scene,
        limit: String(limit),
      });
      if (category) {
        params.set("category", category);
      }

      const res = await fetch(
        getApiUrl(`/api/recommendations?${params.toString()}`),
        {
          headers: {
            ...buildAuthHeaders(),
          },
        }
      );

      if (!res.ok) {
        throw new Error(`Failed to fetch recommendations: ${res.status}`);
      }

      const data: RecommendationResponse = await res.json();
      setRecommendations(data.recommendations || []);
    } catch (err) {
      console.error("Failed to fetch recommendations:", err);
      setError(err instanceof Error ? err.message : "Unknown error");
      // Don't clear recommendations on error, keep previous
    } finally {
      setLoading(false);
    }
  }, [scene, limit, category, enabled]);

  useEffect(() => {
    fetchRecommendations();
  }, [fetchRecommendations]);

  return {
    recommendations,
    loading,
    error,
    refresh: fetchRecommendations,
  };
}

interface UseRecommendationFeedbackResult {
  sendFeedback: (
    recommendationId: string,
    action: "click" | "dismiss" | "hide",
    scene?: string
  ) => Promise<void>;
}

/**
 * Hook to send recommendation feedback.
 */
export function useRecommendationFeedback(): UseRecommendationFeedbackResult {
  const sendFeedback = useCallback(
    async (
      recommendationId: string,
      action: "click" | "dismiss" | "hide",
      scene?: string
    ) => {
      try {
        await fetch(getApiUrl("/api/recommendations/feedback"), {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            ...buildAuthHeaders(),
          },
          body: JSON.stringify({
            recommendation_id: recommendationId,
            action,
            scene,
          }),
        });
      } catch (err) {
        console.error("Failed to send feedback:", err);
      }
    },
    []
  );

  return { sendFeedback };
}
