/**
 * CoApisDeepThinking — wrapper around the library's DeepThinking component
 * that adds autoCloseOnFinish behavior.
 *
 * Behavior:
 * - Starts EXPANDED (defaultOpen=true) so the user can see thinking in real-time
 * - When thinking finishes (loading=false), auto-collapses (autoCloseOnFinish=true)
 * - User can still manually expand/collapse
 */
import React from 'react';
import { DeepThinking as LibraryDeepThinking, type IDeepThinking } from '@agentscope-ai/chat';

const CoApisDeepThinking: React.FC<{ data: IDeepThinking }> = ({ data }) => {
  if (!data) return null;
  return (
    <LibraryDeepThinking
      defaultOpen={true}
      autoCloseOnFinish={true}
      title={data.title}
      loading={data.loading}
      content={data.content}
      className={data.className}
      maxHeight={data.maxHeight}
    />
  );
};

export default CoApisDeepThinking;
