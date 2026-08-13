/**
 * C2A Card Registry - Component registry mapping card_type to React components.
 */

import { CardData } from './types';

// Import card components
import { ApprovalCard } from '../ApprovalCard/ApprovalCard';
import ActionLinkCard from './ActionLinkCard';
import DataTableCard from './DataTableCard';
import FilePreviewCard from './FilePreviewCard';
import NotificationCard from './NotificationCard';
// import ExecutionResultCard from './ExecutionResultCard';

export type CardComponentProps = {
  cardData: CardData;
  onAction?: (action: string, params?: Record<string, any>) => void;
};

// Registry mapping card_type to React components
export const CARD_COMPONENTS: Record<string, any> = {
  approval: ApprovalCard,
  action_link: ActionLinkCard,
  data_table: DataTableCard,
  file_preview: FilePreviewCard,
  notification: NotificationCard,
  // execution_result: ExecutionResultCard,
};

/**
 * Render a card component based on card_type.
 */
export function CardRenderer({ cardData, onAction }: CardComponentProps) {
  const Component = CARD_COMPONENTS[cardData.cardType];
  
  if (!Component) {
    console.warn(`[CardRegistry] Unknown card_type: ${cardData.cardType}`);
    return null;
  }

  // Map cardData to component props (adapter pattern)
  const componentProps: any = {
    ...cardData,
    onAction,
  };

  // Special handling for approval cards (they have specific prop names like onApprove/onDeny)
  if (cardData.cardType === 'approval') {
    return <ApprovalCard {...componentProps} />;
  }

  const Comp = Component as any;
  return <Comp cardData={cardData} onAction={onAction} />;
}

/**
 * Register a new card component type.
 */
export function registerCardType(cardType: string, Component: any) {
  CARD_COMPONENTS[cardType] = Component;
}

/**
 * Get all registered card types.
 */
export function getRegisteredCardTypes(): string[] {
  return Object.keys(CARD_COMPONENTS);
}
