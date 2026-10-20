import { useCallback, useEffect, useRef, useState } from "react";
import { Badge, Tooltip } from "antd";
import { BellOutlined } from "@ant-design/icons";
import { useNavigate } from "react-router-dom";
import { messageService } from "../../api/modules/message";

/**
 * 顶栏通知铃铛（E1 通知栏地基）
 *
 * 设计要点：
 * - 只做「未读角标 + 一键进入消息中心」，不在顶栏堆列表，保持默认极简；
 *   需要看内容时点进消息中心（分层暴露：入口常驻，详情按需）。
 * - 轮询 60s；页面从后台切回时立即刷新，避免角标长期过期。
 * - 拉取失败静默降级为无角标，绝不打扰主流程（聊天优先）。
 */
const POLL_MS = 60_000;

export function NotificationBell() {
  const navigate = useNavigate();
  const [unread, setUnread] = useState(0);
  const timer = useRef<number | null>(null);

  const refresh = useCallback(async () => {
    try {
      const res = await messageService.getStats();
      if (res?.success) {
        setUnread(Number(res.data?.unread_count ?? 0) || 0);
      }
    } catch {
      // 静默：通知角标属于锦上添花，不能影响主界面
    }
  }, []);

  useEffect(() => {
    refresh();
    timer.current = window.setInterval(refresh, POLL_MS);
    const onVisible = () => {
      if (document.visibilityState === "visible") refresh();
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      if (timer.current !== null) window.clearInterval(timer.current);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [refresh]);

  return (
    <Tooltip title={unread > 0 ? `${unread} 条未读消息` : "消息中心"}>
      <button
        type="button"
        onClick={() => navigate("/messages")}
        aria-label="消息中心"
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          width: 32,
          height: 32,
          padding: 0,
          border: "none",
          borderRadius: 6,
          background: "transparent",
          color: "#595959",
          fontSize: 16,
          cursor: "pointer",
        }}
      >
        <Badge count={unread} size="small" offset={[2, -2]}>
          <BellOutlined style={{ fontSize: 17 }} />
        </Badge>
      </button>
    </Tooltip>
  );
}

export default NotificationBell;
