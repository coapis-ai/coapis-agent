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
    if (config.displayMode === 'detailed') {
      return outputMessages;
    }

    return outputMessages.filter((msg) => {
      const role = msg.role || '';

      // Always show assistant messages
      if (role === 'assistant') return true;

      // Hide system messages when configured
      if (config.hideSystemMessages && role === 'system') return false;

      // Hide tool messages when configured
      if (config.hideToolCall && role === 'tool') return false;

      return true;
    });
  }, [outputMessages, config]);

  // In simple mode, render combined text content with Markdown
  if (config.displayMode === 'simple') {
    const textContents: string[] = [];

    for (const msg of filteredMessages) {
      const text = extractText(msg.content);
      if (text.trim()) textContents.push(text);
    }

    const combinedText = textContents.join('\n\n');

    if (!combinedText.trim()) {
      return null;
    }

    // Use @agentscope-ai/chat Markdown component for proper rendering
    return (
      <div className={styles.simplifiedResponse}>
        <Markdown
          content={combinedText}
          baseFontSize={config.fontSize === 'small' ? 13 : config.fontSize === 'large' ? 16 : 14}
          baseLineHeight={1.7}
          raw={false}
        />
      </div>
    );
  }

  // In detailed mode, render all messages with proper formatting
  return (
    <div className={styles.simplifiedResponse}>
      {filteredMessages.map((msg, idx) => {
        const role = msg.role || '';
        const text = extractText(msg.content);

        if (!text.trim()) {
          return null;
        }

        return (
          <div
            key={idx}
            className={styles[`${role}Message`]}
            data-role={role}
          >
            <Markdown
              content={text}
              baseFontSize={config.fontSize === 'small' ? 13 : config.fontSize === 'large' ? 16 : 14}
              baseLineHeight={1.7}
              raw={false}
            />
          </div>
        );
      })}
    </div>
  );
};

export default SimplifiedResponseCard;
