/**
 * C2A Card Protocol - TypeScript types for Card-to-Action / Context-to-Application system.
 */

export type CardActionType = 'primary' | 'secondary' | 'danger' | 'success';

export interface CardAction {
  label: string;
  type?: CardActionType;
  action: string;
  params?: Record<string, any>;
}

export interface CardContent {
  // For data_table cards
  columns?: Array<Record<string, any>>;
  rows?: Array<Record<string, any>>;
  
  // For file_preview cards
  fileName?: string;
  fileSize?: number;
  previewUrl?: string;
  
  // For notification cards
  message?: string;
  priority?: 'low' | 'medium' | 'high';
}

export interface CardMetadata {
  sessionId: string;
  timeoutSeconds?: number;
  requiresAuth?: boolean;
  createdAt?: number;
}

export type CardType = 
  | 'approval'
  | 'action_link'
  | 'data_table'
  | 'notification'
  | 'file_preview'
  | 'execution_result';

export interface CardData {
  cardId: string;
  cardType: CardType;
  title: string;
  description?: string;
  content?: CardContent;
  actions?: CardAction[];
  metadata?: CardMetadata;
}
