import React from "react";
import type { ProviderInfo, ActiveModelsInfo } from "../../../../../api/types";
import { RemoteProviderCard } from "./RemoteProviderCard";

interface ProviderCardProps {
  provider: ProviderInfo;
  activeModels: ActiveModelsInfo | null;
  onSaved: () => void;
}

export const ProviderCard = React.memo(function ProviderCard({
  provider,
  activeModels,
  onSaved,
}: ProviderCardProps) {
  return (
    <RemoteProviderCard
      provider={provider}
      activeModels={activeModels}
      onSaved={onSaved}
    />
  );
});
