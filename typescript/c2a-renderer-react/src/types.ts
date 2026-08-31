/**
 * C2A (Chat-to-Action) Interactive Message Protocol - React Type Definitions
 *
 * Self-contained copy of the C2A protocol types so that this package can be
 * consumed as a plain npm `file:` dependency without resolving the
 * unpublished `@coapis/c2a-core-types` workspace package.
 *
 * Keep in sync with `../c2a-core-types/src/index.ts`.
 */

export type C2AProtocolVersion = 'c2a-v1.0';

export interface ContextRef {
  session_id: string;
  task_id?: string | null;
  scene_id?: string | null;
}

export interface WorkflowState {
  current_node?: string | null;
  next_nodes?: string[];
  completion_ratio?: string | null;
}

export interface Attachment {
  id: string;
  name: string;
  url: string;
  type: string;
}

export interface Metadata {
  generated_by: string;
  generated_at?: string;
  ttl_seconds?: number | null;
  source_system?: string | null;
  doc_version?: string | number;
  permissions_required?: string[];
  attachments?: Attachment[];
}

export interface BlockContent {
  [key: string]: any;
}

// Row Action Template for data_table blocks
export interface RowActionTemplate {
  action_id: string;
  label: string;
  /** 'link' makes rows/cells clickable; 'button' renders an action-column button. */
  style?: 'link' | 'button';
  business_intent: string;
  /** URL with single-brace {field} (or legacy {{field}}) placeholders. */
  url_template?: string | null;
  /**
   * Header name of the column rendered as an inline hyperlink (e.g. "title").
   * When set and the cell is non-empty, only that cell is clickable;
   * otherwise the whole row remains clickable (backward compatible).
   */
  link_column?: string | null;
  api_endpoint_mapping?: string;
  params_mapping?: Record<string, string>;
}

export interface DataTableBlockContent extends BlockContent {
  data: {
    headers: string[];
    rows: string[][];
  };
  /** Name of the hidden id column used to build row links. */
  id_field?: string | null;
  /** Per-row {id_field: value} maps so links work even with the id column hidden. */
  row_values?: Array<Record<string, any>>;
  row_actions?: Record<string, RowActionTemplate>;
}

export interface Block {
  block_id: string;
  type: 'text_markdown' | 'data_table' | 'data_list' | 'form_definition' | 'custom_component';
  content: BlockContent;
}

export interface ActionSecurity {
  requires_auth: boolean;
  required_permissions?: string[];
  confirmation_prompt?: string | null;
}

export type ActionIntent =
  | 'api_call'
  | 'function_invoke'
  | 'web_redirect'
  | 'workflow_trigger'
  | 'form_submit'
  | 'custom_extension';

export type ActionTypeStyle =
  | 'primary'
  | 'secondary'
  | 'danger'
  | 'success'
  | 'warning'
  | 'text';

export interface Action {
  action_id: string;
  label: string;
  icon?: string | null;
  style?: ActionTypeStyle;
  disabled?: boolean;
  intent: ActionIntent;
  payload: Record<string, any>;
  security?: ActionSecurity;
}

export type C2AStateStatus =
  | 'idle'
  | 'generating'
  | 'rendered'
  | 'interactive'
  | 'executing'
  | 'completed'
  | 'failed';

export interface State {
  status: C2AStateStatus;
  error_code?: string | null;
  error_message?: string | null;
}

// Suggestion for LLM guided interactions
export interface Suggestion {
  suggestion_id: string;
  label: string;
  business_intent: string;
  context_data?: Record<string, any>;
}

export interface C2AMessage {
  protocol_version: C2AProtocolVersion;
  message_id: string;
  context_ref: ContextRef;
  metadata?: Metadata;
  blocks: Block[];
  actions: Action[];
  state: State;
  suggestions?: Suggestion[];
  extensions?: Record<string, any>;
}

// Callback type for action execution
export interface C2AActionExecutor {
  executeAction(actionId: string, action: Action, contextRef: ContextRef): Promise<void>;
}
