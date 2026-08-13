// Message service for enterprise message system

import { request } from '../request';
import type { MessageStats, MessageCategoryStat, MessageListQuery, MessageListResponse } from '../types/message';

export const messageService = {
  getStats: async (): Promise<MessageStats> => {
    return request.get('/api/ent/messages/stats');
  },

  getCategoryStats: async (): Promise<MessageCategoryStat[]> => {
    return request.get('/api/ent/messages/categories/stats');
  },

  getList: async (query: MessageListQuery): Promise<MessageListResponse> => {
    return request.post('/api/ent/messages/list', query);
  }
};