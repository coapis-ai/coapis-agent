// Message detail and timeline types for enterprise message system

export interface TimelineItem {
  event_time: string; // ISO datetime string
  event_type: 'received' | 'ai_classified' | 'mark_read' 
             | 'approval_submitted' | 'approval_approved' | 'approval_rejected' 
             | 'callback_sent' | 'callback_success' | 'callback_failed';
  description: string;
  operator?: string;
}

export interface CallbackInfo {
  callback_url?: string;
  callback_status?: 'pending' | 'success' | 'failed';
  retry_count?: number;
  last_callback_time?: string;
}

export interface ApprovalInfo {
  approval_workflow_id?: string;
  current_node?: string;
  approver_list?: string[];
  approval_actions?: Array<{ action: 'approve' | 'reject', operator: string, time: string }>;
}

export interface MessageDetail {
  id: string; // UUID
  title: string;
  summary: string;
  content: string;
  business_type: 'approval_request' | 'callback_notification' | 'external_system_status' | 'ai_agent_task' | 'system_notification';
  workflow_status: 'pending_approval' | 'processing' | 'callback_pending' | 'callback_success' | 'completed' | 'rejected' | 'failed';
  source_type: string;
  priority: 'high' | 'medium' | 'low';
  is_read: boolean;
  created_at: string; // ISO datetime string
  updated_at?: string;
  
  // Extended business fields
  callback_info?: CallbackInfo;
  approval_info?: ApprovalInfo;
  
  timeline_events: TimelineItem[];
}

export interface MarkAsReadRequest {
  message_id: string;
}