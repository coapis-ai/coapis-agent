/**
 * C2A (Chat-to-Action) Interactive Message Protocol - Vue 3 Type Definitions
 * 
 * This module provides the TypeScript interfaces for the C2A protocol,
 * mirroring the Python c2a_protocol.models implementation.
 */

import { C2AMessage as CoreC2AMessage } from '@coapis/c2a-core-types';

export interface C2AMessage extends CoreC2AMessage {}

export interface ContextRef {
  session_id: string;
  task_id?: string;
}

export interface C2AButton {
  id: string;
  label: string;
  scope: 'card' | 'row';
  url_template: string;
  style?: 'primary' | 'secondary' | 'danger' | 'success' | 'warning' | 'text';
}

export interface Metadata {
  generated_by: string;
  generated_at: string;
  ttl_seconds?: number;
  /** AI 辅助决策文本。 */
  summary?: string | null;
  /** 纯导航按钮（label + url + scope）。 */
  buttons?: C2AButton[];
}

export interface BlockContent {
  data: Record<string, any>;
}

export interface Block {
  block_id: string;
  type: 'text_markdown' | 'data_table' | 'data_list' | 'form_definition' | 'custom_component';
  content: BlockContent;
}

export interface ActionSecurity {
  requires_auth: boolean;
  required_permissions: string[];
  confirmation_prompt?: string;
}

export interface Action {
  action_id: string;
  label: string;
  icon?: string;
  style: 'primary' | 'secondary' | 'danger' | 'success' | 'warning' | 'text';
  disabled: boolean;
  intent: 'api_call' | 'function_invoke' | 'web_redirect' | 'workflow_trigger' | 'form_submit' | 'custom_extension';
  payload: Record<string, any>;
  security: ActionSecurity;
}

export interface State {
  status: 'idle' | 'generating' | 'rendered' | 'interactive' | 'executing' | 'completed' | 'failed';
  error_code?: string;
  error_message?: string;
}

// Export the main C2AMessage type for Vue components
export { C2AMessage, Block, Action, State, ContextRef, Metadata, BlockContent, ActionSecurity };
