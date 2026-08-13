// Message types for enterprise message system

export interface MessageStats {
  total_received: number;
  unread_count: number;
  today_new: number;
  processing_pending: number;
}

export interface MessageCategoryStat {
  category: string;
  count: number;
}

export interface MessageListItem {
  id: string; // UUID
  title: string;
  summary: string;
  business_type: 'approval_request' | 'callback_notification' | 'external_system_status' | 'ai_agent_task' | 'system_notification';
  workflow_status: 'pending_approval' | 'processing' | 'callback_pending' | 'callback_success' | 'completed' | 'rejected' | 'failed';
  source_type: string;
  priority: 'high' | 'medium' | 'low';
  is_read: boolean;
  created_at: string; // ISO datetime string
  updated_at?: string;
}

export interface MessageListQuery {
  business_type?: string;
  workflow_status?: string;
  is_read?: boolean;
  page: number;
  size: number;
}

export interface MessageListResponse {
  items: MessageListItem[];
  total: number;
  page: number;
  size: number;
}