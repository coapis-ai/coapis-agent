/**
 * C2A Card Parser Utility - Parses chat messages/tool responses for C2A card data.
 */

import { CardData } from '../components/Cards/types';

export const CARD_MARKER_START = '<!-- CARD_START -->';
export const CARD_MARKER_END = '<!-- CARD_END -->';

/**
 * Extract card JSON from a text response.
 * Looks for <!-- CARD_START --> ... <!-- CARD_END --> blocks or standalone JSON objects matching CardData structure.
 */
export function extractCardData(text: string): CardData | null {
  // Try to find card marker block first
  const startMarker = text.indexOf(CARD_MARKER_START);
  const endMarker = text.indexOf(CARD_MARKER_END, startMarker !== -1 ? startMarker : 0);

  let jsonStr = '';
  if (startMarker !== -1 && endMarker !== -1 && endMarker > startMarker) {
    jsonStr = text.slice(startMarker + CARD_MARKER_START.length, endMarker).trim();
  } else {
    // Fallback: try to parse as standalone JSON object if it looks like CardData
    try {
      const parsed = JSON.parse(text);
      if (parsed && typeof parsed === 'object' && 'cardId' in parsed && 'cardType' in parsed) {
        return parsed as CardData;
      }
    } catch {
      // Not a valid JSON or not a card data object
    }
    return null;
  }

  try {
    const parsed = JSON.parse(jsonStr);
    if (parsed && typeof parsed === 'object' && 'cardId' in parsed && 'cardType' in parsed) {
      return parsed as CardData;
    }
  } catch (e) {
    console.warn('[CardParser] Failed to parse card data from text:', e);
  }

  return null;
}

/**
 * Split text into regular content and card data.
 */
export function splitTextAndCards(text: string): { content: string; cards: CardData[] } {
  const cards: CardData[] = [];
  let content = text;

  const startMarker = text.indexOf(CARD_MARKER_START);
  if (startMarker !== -1) {
    // Extract all card blocks
    let remainingText = text;
    while (true) {
      const startIdx = remainingText.indexOf(CARD_MARKER_START);
      if (startIdx === -1) break;

      const endIdx = remainingText.indexOf(CARD_MARKER_END, startIdx + CARD_MARKER_START.length);
      if (endIdx === -1) break;

      const jsonStr = remainingText.slice(startIdx + CARD_MARKER_START.length, endIdx).trim();
      try {
        const parsed = JSON.parse(jsonStr);
        if (parsed && typeof parsed === 'object' && 'cardId' in parsed && 'cardType' in parsed) {
          cards.push(parsed as CardData);
        }
      } catch {
        // Ignore invalid card JSON
      }

      // Remove the card block from remaining text for content
      remainingText = remainingText.slice(endIdx + CARD_MARKER_END.length).trim();
    }
    content = remainingText;
  } else {
    // Try to extract standalone JSON card at the beginning or end
    const parsedCard = extractCardData(text);
    if (parsedCard) {
      cards.push(parsedCard);
      content = text.replace(JSON.stringify(parsedCard), '').trim();
    }
  }

  return { content, cards };
}
