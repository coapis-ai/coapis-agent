import { useState, useEffect } from "react";
import { Layout, Spin, message as antdMessage } from "antd";
import MessageStatisticsPanel from "./components/MessageStatisticsPanel";
import CategoryStatisticsPanel from "./components/CategoryStatisticsPanel";
import MessageListTable from "./components/MessageListTable";
import type { MessageStats } from "./components/MessageStatisticsPanel";
import type { CategoryStats } from "./components/CategoryStatisticsPanel";
import type { MessageItem } from "./components/MessageListTable";

const { Content } = Layout;

export default function MessagesPage() {
  const [stats, setStats] = useState<MessageStats | null>(null);
  const [categories, setCategories] = useState<CategoryStats[]>([]);
  const [messages, setMessages] = useState<MessageItem[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);
  const [loading, setLoading] = useState(false);

  // Load statistics
  useEffect(() => {
    loadStats();
    loadCategories();
  }, []);

  const loadStats = async () => {
    try {
      // TODO: Replace with actual API call to /api/messages/stats/personal
      const mockStats: MessageStats = {
        total_messages: 156,
        unread_messages: 23,
        today_new_messages: 8,
        processed_messages: 133,
      };
      setStats(mockStats);
    } catch (error) {
      console.error("Failed to load stats:", error);
    }
  };

  const loadCategories = async () => {
    try {
      // TODO: Replace with actual API call to /api/messages/categories/stats
      const mockCategories: CategoryStats[] = [
        { category_name: "系统通知", unread_count: 5, read_count: 42 },
        { category_name: "任务分配", unread_count: 8, read_count: 31 },
        { category_name: "审批提醒", unread_count: 3, read_count: 15 },
        { category_name: "AI代理消息", unread_count: 7, read_count: 28 },
        { category_name: "外部系统集成通知", unread_count: 0, read_count: 17 },
      ];
      setCategories(mockCategories);
    } catch (error) {
      console.error("Failed to load categories:", error);
    }
  };

  const loadMessages = async () => {
    setLoading(true);
    try {
      // TODO: Replace with actual API call to /api/messages?page=&pageSize=...
      const mockMessages: MessageItem[] = [
        { id: "msg-001", title: "系统维护通知", content: "今晚23:00进行系统维护", channel: "system", priority: "high", status: "unread", created_at: new Date().toISOString() },
        { id: "msg-002", title: "任务已完成", content: "数据同步任务已执行完成", channel: "task", priority: "medium", status: "read", created_at: new Date(Date.now() - 3600000).toISOString() },
      ];
      setMessages(mockMessages);
      setTotal(156);
    } catch (error) {
      console.error("Failed to load messages:", error);
      antdMessage.error("加载消息列表失败");
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
