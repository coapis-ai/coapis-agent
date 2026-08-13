import { useState, useEffect } from "react";
import { Layout, Spin } from "antd";
import MessageStatisticsPanel from "./components/MessageStatisticsPanel";
import CategoryStatisticsPanel from "./components/CategoryStatisticsPanel";
import MessageListTable from "./components/MessageListTable";
import type { MessageStats } from "./components/MessageStatisticsPanel";
import type { CategoryStats } from "./components/CategoryStatisticsPanel";
import type { MessageItem } from "./components/MessageListTable";
import { messageService } from "@/api/modules/message";

const { Content } = Layout;

export default function MessagesPage() {
  const [stats, setStats] = useState<MessageStats | null>(null);
  const [categories, setCategories] = useState<CategoryStats[]>([]);
  const [messages, setMessages] = useState<MessageItem[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [loading, setLoading] = useState(false);

  // Load statistics
  useEffect(() => {
    loadStats();
    loadCategories();
  }, []);

  const loadStats = async () => {
    try {
      const data = await messageService.getStats();
      setStats({
        total_messages: data.total_received,
        unread_messages: data.unread_count,
        today_new_messages: data.today_new,
        processed_messages: data.processing_pending,
      });
    } catch (error) {
      console.error("Failed to load stats:", error);
    }
  };

  const loadCategories = async () => {
    try {
      const data = await messageService.getCategoryStats();
      const mockCategories: CategoryStats[] = data.map((item) => ({
        category_name: item.category,
        unread_count: item.count,
        read_count: 0,
      }));
      setCategories(mockCategories);
    } catch (error) {
      console.error("Failed to load categories:", error);
    }
  };

  const loadMessages = async () => {
    setLoading(true);
    try {
      const response = await messageService.getList({
        business_type: undefined,
        workflow_status: undefined,
        is_read: undefined,
        page,
        size: pageSize,
      });
      setMessages(response.items.map((item) => ({
        id: item.id,
        title: item.title,
        content: item.summary,
        channel: item.business_type,
        priority: item.priority,
        status: item.is_read ? 'read' : 'unread',
        created_at: item.created_at,
      })));
      setTotal(response.total);
    } catch (error) {
      console.error("Failed to load messages:", error);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadMessages();
  }, [page, pageSize]);

  const handlePageChange = (newPage: number, newPageSize: number) => {
    setPage(newPage);
    setPageSize(newPageSize);
  };

  const handleMessageClick = (messageId: string) => {
    // TODO: Navigate to message detail page /messages/:id
    console.log("Message clicked:", messageId);
  };

  return (
    <Layout style={{ minHeight: "100vh" }}>
      <Content style={{ padding: 24, background: "#f0f2f5" }}>
        {loading && !stats ? (
          <Spin size="large" style={{ display: "block", margin: "100px auto" }} />
        ) : (
          <>
            {/* 统计面板 */}
            {stats && <MessageStatisticsPanel stats={stats} />}
            
            {/* 分类统计 */}
            <CategoryStatisticsPanel 
              categories={categories} 
              onCategoryClick={(categoryName) => {
                console.log("Category clicked:", categoryName);
              }}
            />

            {/* 消息列表 */}
            <MessageListTable
              messages={messages}
              total={total}
              page={page}
              pageSize={pageSize}
              loading={loading}
              onRowClick={handleMessageClick}
              onPageChange={handlePageChange}
            />
          </>
        )}
      </Content>
    </Layout>
  );
}
