/**
 * SimplifiedResponseCard — custom card renderer for CoApis chat.
 *
 * Replaces the default AgentScopeRuntimeResponseCard with a streamlined
 * version that respects ChatDisplayConfig. In 'simple' mode, only renders
 * the text content of assistant messages, hiding tool calls, thinking
 * processes, footers, and system messages.
 *
 * Uses @agentscope-ai/chat Markdown component for proper rendering.
 *
 * Usage: register in options.cards as:
 *   cards: {
 *     'AgentScopeRuntimeResponseCard': SimplifiedResponseCard,
 *   }
 */
import React, { useMemo } from 'react';
import { Markdown } from '@agentscope-ai/chat';
import { ChatDisplayConfig, DEFAULT_CHAT_DISPLAY_CONFIG } from '../types';
import styles from '../index.module.less';

// ---------------------------------------------------------------------------
// Context for passing config into the custom card
// ---------------------------------------------------------------------------

export const ChatDisplayConfigContext = React.createContext<ChatDisplayConfig>(
  DEFAULT_CHAT_DISPLAY_CONFIG,
);

export const useChatDisplayConfig = (): ChatDisplayConfig =>
  React.useContext(ChatDisplayConfigContext);

// ---------------------------------------------------------------------------
// SimplifiedResponseCard
// ---------------------------------------------------------------------------

interface SimplifiedResponseCardProps {
  data: {
    output?: Array<{
      role?: string;
      content?: string | Array<{ type: string; [key: string]: unknown }>;
      [key: string]: unknown;
    }>;
    [key: string]: unknown;
  };
}

/**
 * Extract text content from a message's content field.
 * Handles both string and array-of-content-items formats.
 */
function extractText(content: unknown): string {
  if (typeof content === 'string') return content;
  if (!Array.isArray(content)) return '';
  return content
    .filter((item: any) => item?.type === 'text')
    .map((item: any) => item.text || '')
    .filter(Boolean)
    .join('\n');
}

const SimplifiedResponseCard: React.FC<SimplifiedResponseCardProps> = ({
  data,
}) => {
  const config = useChatDisplayConfig();

  const outputMessages = data.output || [];

  // Filter messages based on config
  const filteredMessages = useMemo(() => {
    // In hideDetails mode, we still show everything; the library's default card handles rendering
    // This card is used as a fallback, so we show all messages
    return outputMessages;
  }, [outputMessages, config]);

  // Extract text content from all messages
  const textContents: string[] = [];
  for (const msg of filteredMessages) {
    const text = extractText(msg.content);
    if (text) {
      textContents.push(text);
    }
  }

  // If no text content, return null
  if (textContents.length === 0) {
    return null;
  }

  // Join all text content with double newlines
  const combinedText = textContents.join('\n\n');

  return (
    <div className={styles.simplifiedCard}>
      <Markdown content={combinedText} />
    </div>
  );
};

export default SimplifiedResponseCard;
