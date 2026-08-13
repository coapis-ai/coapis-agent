// Message detail service for enterprise message system

import { request } from '../request';
import type { MessageDetail, MarkAsReadRequest } from '../types/message_detail';

export const messageDetailService = {
  getDetail: async (messageId: string): Promise<MessageDetail> => {
    return request.get(`/api/ent/messages/${messageId}`);
  },

  markAsRead: async (requestBody: MarkAsReadRequest): Promise<{ status: string }> => {
    return request.post('/api/ent/messages/mark-as-read', requestBody);
  }
};