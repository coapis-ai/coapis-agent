import { ReactNode } from "react";

export interface DefaultModelSelectorProps {
  modelType: "chat" | "embedding" | "rerank" | "audio" | "vision";
  label: string;
  icon: ReactNode;
  value?: { providerId: string; modelId: string } | null;
  onChange: (value: { providerId: string; modelId: string } | null) => void;
  /** Increment to force-reload model list (e.g. after provider config changes) */
  refreshKey?: number;
}

export interface ModelTypeTabsProps {
  activeType: string | undefined;
  onChange: (type: string | undefined) => void;
  providers: any[];
}
