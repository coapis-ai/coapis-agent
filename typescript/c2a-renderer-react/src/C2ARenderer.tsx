/**
 * C2A (Chat-to-Action) Interactive Message Protocol - React Reference Renderer
 * 
 * This component renders C2A messages according to the protocol standard,
 * handling state transitions and block/action rendering.
 */

import React, { useState, useEffect } from 'react';
import { 
  C2AMessage, 
  Block, 
  Action, 
  C2AStateStatus, 
  C2AActionExecutor,
  WorkflowState,
  Attachment,
  RowActionTemplate,
  Suggestion,
  DataTableBlockContent
} from './types';

// ============================================================================
// URL Template Replacement & External Redirect Utility with Fault Tolerance
// ============================================================================

export interface UrlReplacementContext {
  [key: string]: any;
}

/**
 * Replace URL template placeholders with actual context data.
 *
 * Supports BOTH placeholder styles used across the ecosystem:
 *   - single-brace:   {approval_id}      (C2A mcp_parser / row_values contract)
 *   - double-brace:   {{approval_id}}    (legacy)
 *
 * @param urlTemplate - The URL template with placeholders
 * @param context - The replacement context data
 * @returns The replaced URL, or the original template if a placeholder is missing
 */
export function replaceUrlTemplate(urlTemplate: string, context: UrlReplacementContext): string {
  try {
    // {{key}} first (double), then {key} (single) — avoids clobbering the outer
    // braces of a double-brace placeholder.
    const result = urlTemplate
      .replace(/\{\{(\w+)\}\}/g, (_m, key: string) => {
        const value = context[key];
        if (value === undefined || value === null) {
          throw new Error(`missing placeholder: ${key}`);
        }
        return encodeURIComponent(String(value));
      })
      .replace(/\{(\w+)\}/g, (_m, key: string) => {
        const value = context[key];
        if (value === undefined || value === null) {
          throw new Error(`missing placeholder: ${key}`);
        }
        return encodeURIComponent(String(value));
      });
    return result;
  } catch (error) {
    console.error('Error replacing URL template:', error);
    return urlTemplate; // Fault tolerance: return original on error
  }
}

/**
 * Handle external redirect with fault tolerance and fallback mechanisms.
 * 
 * @param targetUrl - The target URL to redirect to
 * @param options - Redirect options including fallback behavior
 */
export function handleExternalRedirect(targetUrl: string, options?: {
  openInNewTab?: boolean;
  fallbackAction?: () => void;
}): void {
  try {
    // Accept absolute http(s) URLs AND internal relative paths (/app/xxx, #anchor).
    const isHttp = targetUrl.startsWith('http://') || targetUrl.startsWith('https://');
    const isRelative = targetUrl.startsWith('/') || targetUrl.startsWith('#');
    if (!targetUrl || (!isHttp && !isRelative)) {
      console.warn(`Invalid redirect URL: ${targetUrl}`);
      options?.fallbackAction?.();
      return;
    }

    if (options?.openInNewTab) {
      window.open(targetUrl, '_blank', 'noopener,noreferrer');
    } else {
      window.location.href = targetUrl;
    }
  } catch (error) {
    console.error('Error during external redirect:', error);
    options?.fallbackAction?.();
  }
}

/**
 * Process row action template with URL template replacement and external redirect.
 * 
 * @param rowAction - The RowActionTemplate from data_table block
 * @param rowData - The current row data context
 */
export function processRowActionResult(rowAction: RowActionTemplate, rowData: Record<string, any>): void {
  try {
    let targetUrl = '';
    
    // Determine target URL based on url_template or api_endpoint_mapping
    if (rowAction.url_template) {
      const contextData: UrlReplacementContext = {};
      
      // Map row data to template parameters using params_mapping if available
      const paramsMapping = rowAction.params_mapping;
      if (paramsMapping) {
        Object.keys(paramsMapping).forEach((paramKey) => {
          const sourceField = paramsMapping[paramKey];
          contextData[paramKey] = rowData[sourceField];
        });
      } else {
        // Default mapping: use field names directly
        Object.assign(contextData, rowData);
      }
      
      targetUrl = replaceUrlTemplate(rowAction.url_template, contextData);
    } else if (rowAction.api_endpoint_mapping) {
      // For API endpoints, construct the full URL based on current origin
      const apiEndpoint = rowAction.api_endpoint_mapping;
      const baseUrl = window.location.origin + '/api';
      targetUrl = `${baseUrl}${apiEndpoint}`;
    } else {
      console.warn('Row action has no url_template or api_endpoint_mapping');
      return;
    }

    // Handle the redirect based on business intent
    if (rowAction.business_intent === 'external_redirect' || rowAction.business_intent.includes('redirect')) {
      handleExternalRedirect(targetUrl, { 
        openInNewTab: true,
        fallbackAction: () => console.log('External redirect failed or not supported')
      });
    } else {
      // For API calls or internal actions, trigger the appropriate action
      console.log(`Processing row action intent: ${rowAction.business_intent}, url: ${targetUrl}`);
    }
  } catch (error) {
    console.error('Error processing row action result:', error);
  }
}

/**
 * Process suggestion click with URL template replacement and external redirect.
 * 
 * @param suggestion - The Suggestion object from C2A message
 */
export function processSuggestionClick(
  suggestion: Suggestion,
  onSuggestionClick?: (suggestion: Suggestion) => void,
): void {
  try {
    const ctx = suggestion.context_data || {};

    // 1) URL-based (e.g. more -> url_template)
    const urlTemplate = ctx.url_template as string | undefined;
    if (urlTemplate) {
      const targetUrl = replaceUrlTemplate(urlTemplate, ctx);
      handleExternalRedirect(targetUrl, {
        openInNewTab: true,
        fallbackAction: () => console.log('Suggestion external redirect failed'),
      });
      return;
    }

    // 2) API-based (e.g. export -> api_endpoint) or any custom intent
    if (onSuggestionClick) {
      onSuggestionClick(suggestion);
    } else {
      console.log(`Suggestion intent (no handler): ${suggestion.business_intent}`, ctx);
    }
  } catch (error) {
    console.error('Error processing suggestion click:', error);
  }
}

// ============================================================================
// Enterprise Extensions: Workflow State & Attachment Renderers
// ============================================================================

interface WorkflowStateRendererProps {
  workflowState: WorkflowState;
}

const WorkflowStateRenderer: React.FC<WorkflowStateRendererProps> = ({ workflowState }) => {
  if (!workflowState || (!workflowState.current_node && !workflowState.next_nodes?.length)) {
    return null;
  }

  return (
    <div className="c2a-workflow-state" data-workflow-node={workflowState.current_node}>
      <div className="c2a-workflow-title">Workflow Status</div>
      {workflowState.current_node && (
        <div className="c2a-workflow-current-node">
          Current Node: <span className="c2a-workflow-node-label">{workflowState.current_node}</span>
        </div>
      )}
      {workflowState.next_nodes && workflowState.next_nodes.length > 0 && (
        <div className="c2a-workflow-next-nodes">
          <span className="c2a-workflow-label">Next Nodes:</span>
          <ul className="c2a-workflow-node-list">
            {workflowState.next_nodes.map((node, idx) => (
              <li key={idx} className="c2a-workflow-node-item">{node}</li>
            ))}
          </ul>
        </div>
      )}
      {workflowState.completion_ratio && (
        <div className="c2a-workflow-completion">
          Completion: <span className="c2a-workflow-ratio-label">{workflowState.completion_ratio}</span>
        </div>
      )}
    </div>
  );
};

interface AttachmentRendererProps {
  attachments: Attachment[];
}

const AttachmentRenderer: React.FC<AttachmentRendererProps> = ({ attachments }) => {
  if (!attachments || attachments.length === 0) {
    return null;
  }

  const getAttachmentIcon = (type: string) => {
    if (type.includes('pdf')) return '📄';
    if (type.includes('image') || type.includes('png') || type.includes('jpg')) return '🖼️';
    if (type.includes('doc') || type.includes('word')) return '📝';
    if (type.includes('excel') || type.includes('csv')) return '📊';
    return '📎';
  };

  const getAttachmentPreviewUrl = (attachment: Attachment) => {
    // For image types, generate preview URL (in real implementation, this would be a dedicated preview endpoint)
    if (attachment.type.includes('image') || attachment.type.includes('png') || attachment.type.includes('jpg')) {
      return attachment.url;
    }
    return null;
  };

  return (
    <div className="c2a-attachments-container">
      <div className="c2a-attachments-title">Attachments</div>
      <ul className="c2a-attachment-list">
        {attachments.map((att) => {
          const previewUrl = getAttachmentPreviewUrl(att);
          return (
            <li key={att.id} className="c2a-attachment-item" data-attachment-id={att.id}>
              {previewUrl ? (
                <div className="c2a-attachment-preview">
                  <img 
                    src={previewUrl} 
                    alt={att.name} 
                    className="c2a-attachment-image-preview"
                    onError={(e) => {
                      // Fallback to icon if image preview fails
                      e.currentTarget.style.display = 'none';
                      const parent = e.currentTarget.parentElement;
                      if (parent) {
                        parent.classList.add('c2a-attachment-icon-only');
                      }
                    }}
                  />
                </div>
              ) : (
                <div className="c2a-attachment-icon">
                  {getAttachmentIcon(att.type)}
                </div>
              )}
              <div className="c2a-attachment-info">
                <div className="c2a-attachment-name">{att.name}</div>
                <div className="c2a-attachment-type">{att.type}</div>
              </div>
              <a 
                href={att.url} 
                target="_blank" 
                rel="noopener noreferrer"
                className="c2a-attachment-download-btn"
                download={att.name}
              >
                Download
              </a>
            </li>
          );
        })}
      </ul>
    </div>
  );
};

// ============================================================================
// 1. State Machine & Main Renderer Component
// ============================================================================

interface C2ARendererProps {
  message: C2AMessage;
  onActionClick?: (actionId: string, action: Action) => void;
  onSuggestionClick?: (suggestion: Suggestion) => void;
  executor?: C2AActionExecutor;
}

export const C2ARenderer: React.FC<C2ARendererProps> = ({
  message,
  onActionClick,
  onSuggestionClick,
  executor
}) => {
  const [currentState, setCurrentState] = useState<C2AStateStatus>(message.state.status);
  const [isExecuting, setIsExecuting] = useState(false);

  // Update state when message changes
  useEffect(() => {
    setCurrentState(message.state.status);
  }, [message.state.status]);

  // Handle action execution
  const handleActionClick = async (action: Action) => {
    if (action.disabled) return;

    // Check authentication requirement
    if (action.security?.requires_auth && !isAuthenticated()) {
      console.warn(`Action ${action.action_id} requires authentication`);
      return;
    }

    // Show confirmation prompt if required
    if (action.security?.confirmation_prompt) {
      const confirmed = window.confirm(action.security.confirmation_prompt);
      if (!confirmed) return;
    }

    setIsExecuting(true);
    
    try {
      if (executor && onActionClick) {
        await executor.executeAction(action.action_id, action, message.context_ref);
        onActionClick(action.action_id, action);
      } else if (onActionClick) {
        onActionClick(action.action_id, action);
      }

      // Update state to completed
      setCurrentState('completed');
    } catch (error) {
      console.error(`Action execution failed: ${action.action_id}`, error);
      setCurrentState('failed');
    } finally {
      setIsExecuting(false);
    }
  };

  // Helper to check authentication (mock implementation)
  const isAuthenticated = (): boolean => {
    // In a real implementation, this would check the user's session token/JWT
    return true;
  };

  // Render based on state
  if (currentState === 'idle' || currentState === 'generating') {
    return <GeneratingState message={message} />;
  }

  if (currentState === 'failed') {
    return <FailedState message={message} />;
  }

  if (currentState === 'completed') {
    return <CompletedState message={message} />;
  }

  // Render rendered/interactive/executing state
  return (
    <div className="c2a-message-container" data-message-id={message.message_id}>
      
      {/* Enterprise Extensions: Workflow State & Doc Version */}
      {message.metadata?.doc_version && (
        <div className="c2a-doc-version-info">
          <span className="c2a-doc-version-label">Document Version:</span>
          <span className="c2a-doc-version-value">{message.metadata.doc_version}</span>
        </div>
      )}

      {/* Enterprise Extensions: Workflow State Rendering */}
      {message.extensions?.workflow_state && (
        <WorkflowStateRenderer workflowState={message.extensions.workflow_state as any} />
      )}

      {/* Enterprise Extensions: Attachments Rendering */}
      {message.metadata?.attachments && message.metadata.attachments.length > 0 && (
        <AttachmentRenderer attachments={message.metadata.attachments} />
      )}

      {/* Blocks Rendering */}
      <div className="c2a-blocks">
        {message.blocks.map((block) => (
          <BlockRenderer key={block.block_id} block={block} />
        ))}
      </div>

      {/* Actions Rendering */}
      {message.actions.length > 0 && (
        <div className="c2a-actions">
          {message.actions.map((action) => (
            <ActionButton 
              key={action.action_id} 
              action={action} 
              onClick={() => handleActionClick(action)}
              isExecuting={isExecuting}
            />
          ))}
        </div>
      )}

      {/* Suggestions Rendering (LLM Guided Interactions) */}
      {message.suggestions && message.suggestions.length > 0 && (
        <div className="c2a-suggestions">
          <div className="c2a-suggestions-title">建议操作：</div>
          <div className="c2a-suggestion-list">
            {message.suggestions.map((suggestion: Suggestion) => (
              <button
                key={suggestion.suggestion_id}
                className="c2a-suggestion-btn"
                onClick={() => {
                  // URL-based suggestions open directly; API/custom intents go to the callback.
                  processSuggestionClick(suggestion, onSuggestionClick);
                }}
                data-business-intent={suggestion.business_intent}
                type="button"
              >
                {suggestion.label}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Extensions Rendering (if any) */}
      {message.extensions && Object.keys(message.extensions).length > 0 && !(message.extensions.workflow_state) && (
        <div className="c2a-extensions">
          <details>
            <summary>Extensions Data</summary>
            <pre>{JSON.stringify(message.extensions, null, 2)}</pre>
          </details>
        </div>
      )}
    </div>
  );
};

// ============================================================================
// 2. State Component Implementations
// ============================================================================

const GeneratingState: React.FC<{ message: C2AMessage }> = ({ message }) => {
  return (
    <div className="c2a-state-generating" data-message-id={message.message_id}>
      <div className="c2a-loading-spinner"></div>
      <span className="c2a-loading-text">Generating interactive content...</span>
    </div>
  );
};

const FailedState: React.FC<{ message: C2AMessage }> = ({ message }) => {
  const errorCode = message.state.error_code || 'UNKNOWN_ERROR';
  const errorMessage = message.state.error_message || 'An error occurred while processing the request.';

  return (
    <div className="c2a-state-failed" data-message-id={message.message_id}>
      <div className="c2a-error-icon">⚠️</div>
      <div className="c2a-error-content">
        <span className="c2a-error-code">Error: {errorCode}</span>
        <span className="c2a-error-message">{errorMessage}</span>
      </div>
    </div>
  );
};

const CompletedState: React.FC<{ message: C2AMessage }> = ({ message }) => {
  return (
    <div className="c2a-state-completed" data-message-id={message.message_id}>
      <div className="c2a-success-icon">✅</div>
      <span className="c2a-success-text">Action completed successfully.</span>
    </div>
  );
};

// ============================================================================
// 3. Block Renderer Implementations
// ============================================================================

const BlockRenderer: React.FC<{ block: Block }> = ({ block }) => {
  switch (block.type) {
    case 'text_markdown':
      return <TextMarkdownBlock block={block} />;
    case 'data_table':
      return <DataTableBlock block={block} />;
    case 'data_list':
      return <DataListBlock block={block} />;
    case 'form_definition':
      return <FormDefinitionBlock block={block} />;
    case 'custom_component':
      return <CustomComponentBlock block={block} />;
    default:
      return <div className="c2a-block-unknown" data-type={block.type}>Unknown block type: {block.type}</div>;
  }
};

const TextMarkdownBlock: React.FC<{ block: Block }> = ({ block }) => {
  const markdownContent = (block.content as any).markdown || '';

  // Render markdown as *text* (React escapes it) to avoid XSS. A full
  // markdown→HTML pipeline is intentionally NOT inlined here — host apps that
  // need rich markdown can pass a pre-rendered component instead.
  return (
    <div className="c2a-block-text_markdown" data-block-id={block.block_id}>
      <div
        className="c2a-markdown-content"
        style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}
      >
        {markdownContent}
      </div>
    </div>
  );
};

const DataTableBlock: React.FC<{ block: Block }> = ({ block }) => {
  const content = block.content as DataTableBlockContent;
  const tableData = content.data || {};
  const headers = tableData.headers || [];
  const rows = tableData.rows || [];
  const rowActions = (content.row_actions || {}) as Record<string, RowActionTemplate>;
  const rowValues = content.row_values || [];

  // Split row actions by style: 'link' → clickable rows; 'button' → action column.
  const allActions = Object.values(rowActions);
  const linkActions = allActions.filter((a) => (a.style || 'link') === 'link');
  const buttonActions = allActions.filter((a) => a.style === 'button');
  const hasLinkRow = linkActions.length > 0;
  const hasButtonCol = buttonActions.length > 0;

  // Inline link column: when the link action declares a link_column header,
  // render ONLY that cell as an inline hyperlink (AntD-style). Falls back to
  // whole-row click when absent or the cell value is empty.
  const linkAction = linkActions[0] as RowActionTemplate | undefined;
  const linkColIndex = linkAction?.link_column
    ? headers.indexOf(linkAction.link_column)
    : -1;
  const hasInlineLinkCol = linkColIndex >= 0;

  /** Whole-row click only when no inline link column, or its cell is empty. */
  const isRowClickable = (row: string[]): boolean =>
    hasLinkRow && !(hasInlineLinkCol && Boolean(row[linkColIndex]));

  /** Build the URL for a row: prefer row_values (hidden id), fall back to visible cells. */
  const buildRowUrl = (actionTemplate: RowActionTemplate, row: string[], rowIdx: number): string | null => {
    if (!actionTemplate.url_template) return null;
    const ctx: Record<string, any> = {};
    // 1) visible cells (by header name)
    headers.forEach((header, idx) => { ctx[header] = row[idx] || ''; });
    // 2) hidden id values from row_values override / add the id field
    const rv = rowValues[rowIdx];
    if (rv) Object.assign(ctx, rv);
    return replaceUrlTemplate(actionTemplate.url_template, ctx);
  };

  /** A URL is usable only if it exists and no placeholder survived replacement. */
  const isResolvableUrl = (url: string | null): boolean =>
    url !== null && url !== '' && !url.includes('{');

  const openRowLink = (actionTemplate: RowActionTemplate, row: string[], rowIdx: number) => {
    const url = buildRowUrl(actionTemplate, row, rowIdx);
    if (!url || !isResolvableUrl(url)) {
      console.warn(`Row link has no resolvable url for row ${rowIdx}`);
      return;
    }
    handleExternalRedirect(url, { openInNewTab: true });
  };

  return (
    <div className="c2a-block-data_table" data-block-id={block.block_id}>
      <table className="c2a-data-table">
        <thead>
          <tr>
            {headers.map((header: string, idx: number) => (
              <th key={idx}>{header}</th>
            ))}
            {hasButtonCol && <th className="c2a-data-table-actions-header">操作</th>}
          </tr>
        </thead>
        <tbody>
          {rows.map((row: string[], rowIdx: number) => {
            const rowClickable = isRowClickable(row);
            return (
            <tr
              key={rowIdx}
              className={rowClickable ? 'c2a-data-row-linkable' : undefined}
              onClick={rowClickable ? () => openRowLink(linkActions[0], row, rowIdx) : undefined}
            >
              {headers.map((_: string, colIdx: number) => {
                const cellText = row[colIdx] || '';
                // Inline link cell: declared link_column with a non-empty value
                // and a resolvable URL → render as a real <a> (new tab).
                const isLinkCell =
                  hasInlineLinkCol && colIdx === linkColIndex && cellText &&
                  isResolvableUrl(buildRowUrl(linkAction!, row, rowIdx));
                if (isLinkCell) {
                  return (
                    <td key={colIdx}>
                      <a
                        className="c2a-row-link-cell"
                        href={buildRowUrl(linkAction!, row, rowIdx) || undefined}
                        target="_blank"
                        rel="noopener noreferrer"
                        onClick={(e) => e.stopPropagation()}
                      >
                        {cellText}
                      </a>
                    </td>
                  );
                }
                return (
                  <td key={colIdx} className={rowClickable ? 'c2a-data-row-link-cell' : undefined}>
                    {cellText}
                  </td>
                );
              })}
              {hasButtonCol && (
                <td className="c2a-data-table-actions-cell">
                  <div className="c2a-row-actions" data-row-index={rowIdx} onClick={(e) => e.stopPropagation()}>
                    {buttonActions.map((actionTemplate: RowActionTemplate) => (
                      <button
                        key={actionTemplate.action_id}
                        className="c2a-row-action-btn"
                        onClick={() => openRowLink(actionTemplate, row, rowIdx)}
                        data-business-intent={actionTemplate.business_intent}
                        type="button"
                      >
                        {actionTemplate.label}
                      </button>
                    ))}
                  </div>
                </td>
              )}
            </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
};

const DataListBlock: React.FC<{ block: Block }> = ({ block }) => {
  const items = (block.content as any).items || [];

  return (
    <div className="c2a-block-data_list" data-block-id={block.block_id}>
      <ul className="c2a-data-list">
        {items.map((item: any, idx: number) => (
          <li key={idx} className="c2a-list-item">
            <span className="c2a-list-title">{item.title || ''}</span>
            {item.subtitle && <span className="c2a-list-subtitle">{item.subtitle}</span>}
          </li>
        ))}
      </ul>
    </div>
  );
};

const FormDefinitionBlock: React.FC<{ block: Block }> = ({ block }) => {
  const fields = (block.content as any).fields || [];
  const submitLabel = (block.content as any).submit_label || 'Submit';

  return (
    <div className="c2a-block-form_definition" data-block-id={block.block_id}>
      <form className="c2a-form">
        {fields.map((field: any, idx: number) => (
          <div key={idx} className="c2a-form-field">
            <label>{field.label}</label>
            <input 
              type={field.type || 'text'} 
              name={field.name}
              required={field.required || false}
              placeholder={field.placeholder || ''}
            />
          </div>
        ))}
        <button type="submit" className="c2a-form-submit-btn">
          {submitLabel}
        </button>
      </form>
    </div>
  );
};

const CustomComponentBlock: React.FC<{ block: Block }> = ({ block }) => {
  const componentName = (block.content as any).component_name || 'unknown';
  const dataPayload = (block.content as any).data_payload || {};

  return (
    <div className="c2a-block-custom_component" data-block-id={block.block_id} data-component={componentName}>
      <div className="c2a-custom-component-placeholder">
        Custom Component: {componentName}
        <pre>{JSON.stringify(dataPayload, null, 2)}</pre>
      </div>
    </div>
  );
};

// ============================================================================
// 4. Action Button Component
// ============================================================================

interface ActionButtonProps {
  action: Action;
  onClick: () => void;
  isExecuting: boolean;
}

const ActionButton: React.FC<ActionButtonProps> = ({ action, onClick, isExecuting }) => {
  const getButtonClass = () => {
    let baseClass = 'c2a-action-btn';
    if (action.style) {
      baseClass += ` c2a-action-btn-${action.style}`;
    }
    if (action.disabled || isExecuting) {
      baseClass += ' c2a-action-btn-disabled';
    }
    return baseClass;
  };

  const renderLabel = () => {
    if (isExecuting) {
      return '⏳ Executing...';
    }
    return action.label;
  };

  return (
    <button
      className={getButtonClass()}
      onClick={onClick}
      disabled={action.disabled || isExecuting}
      data-action-id={action.action_id}
      data-intent={action.intent}
    >
      {action.icon && <span className="c2a-action-icon">{action.icon}</span>}
      <span className="c2a-action-label">{renderLabel()}</span>
    </button>
  );
};

export default C2ARenderer;
