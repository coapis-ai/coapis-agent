/**
 * C2A Card Display Component - Renders C2A cards in the chat message stream.
 */

import { useEffect, useState } from 'react';
import { CardData } from './types';
import { CardRenderer } from './CardRegistry';
import { extractCardData } from '../../utils/cardParser';

export interface C2ACardDisplayProps {
  content: string;
  onAction?: (action: string, params?: Record<string, any>) => void;
}

export function C2ACardDisplay({ content, onAction }: C2ACardDisplayProps) {
  const [cardData, setCardData] = useState<CardData | null>(null);

  useEffect(() => {
    const parsedCard = extractCardData(content);
    if (parsedCard) {
      setCardData(parsedCard);
    }
  }, [content]);

  if (!cardData) {
    return null;
  }

  return (
    <div className="c2a-card-display">
      <CardRenderer cardData={cardData} onAction={onAction} />
    </div>
  );
}

export default C2ACardDisplay;
