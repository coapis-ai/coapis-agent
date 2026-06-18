import type { ProviderInfo } from "../../../../../api/types";
import { RemoteModelManageModal } from "./RemoteModelManageModal";

interface ModelManageModalProps {
  provider: ProviderInfo;
  open: boolean;
  onClose: () => void;
  onSaved: () => void;
}

export function ModelManageModal({
  provider,
  open,
  onClose,
  onSaved,
}: ModelManageModalProps) {
  return (
    <RemoteModelManageModal
      provider={provider}
      open={open}
      onClose={onClose}
      onSaved={onSaved}
    />
  );
}
