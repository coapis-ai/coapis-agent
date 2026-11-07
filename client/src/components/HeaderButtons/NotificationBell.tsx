import { useCallback, useEffect, useRef, useState } from "react";
import { Badge, Tooltip } from "antd";
import { BellOutlined } from "@ant-design/icons";
import { useNavigate } from "react-router-dom";
import { messageService } from "../../api/modules/message";
import { rootApi } from "../../api/modules/root";
import { isEnterpriseEdition } from "../../lib/edition";

/**
 * 顶栏通知铃铛（E1 通知栏地基）
 *
 * 设计要点：
 * - 只做「未读角标 + 一键进入消息中心」，不在顶栏堆列表，保持默认极简；
 *   需要看内容时点进消息中心（分层暴露：入口常驻，详情按需）。
 * - 轮询 60s；页面从后台切回时立即刷新，避免角标长期过期。
 * - 拉取失败静默降级为无角标，绝不打扰主流程（聊天优先）。
 *
 * 版本闸门（社区版必须零请求）：社区版没有 `/api/ent/messages/*` 这组路由
 * （`server/ent/plugins/ent_router.py` 只在企业镜像装载），社区版轮询必然 404，
 * 且组件挂载即触发 → 控制台持续刷红。判定**不新增任何变量**：首选
 * `/api/version` 回带的 `edition`（真源＝后端 `COAPIS_EDITION` 环境变量），
 * 字段缺失或请求失败时回退既有运行期探测 `lib/edition`；两者都判不出时按
 * 社区版处理（宁可不轮询，绝不刷 404）。
 */
const POLL_MS = 60_000;

let enterpriseProbe: Promise<boolean> | null = null;

/** 是否企业版部署（进程内只判定一次；依据见上方注释）。 */
function isEnterpriseDeployment(): Promise<boolean> {
  if (enterpriseProbe === null) {
    enterpriseProbe = rootApi
      .getVersion()
      .then((res) => {
        const edition = (res as { edition?: unknown } | null)?.edition;
        if (typeof edition === "string") return edition === "enterprise";
        // 后端未带 edition（旧版本）→ 回退运行期探测
        return isEnterpriseEdition();
      })
      .catch(() => isEnterpriseEdition());
  }
  return enterpriseProbe;
}

export function NotificationBell() {
  const navigate = useNavigate();
  const [unread, setUnread] = useState(0);
  const timer = useRef<number | null>(null);

  const refresh = useCallback(async () => {
    try {
      // /api/ent/messages/stats 直接返回 MessageStats 本体（无 success/data 信封）。
      // 之前按信封读 → 恒 undefined → 角标永远是 0，且 tsc 直接编译失败。
      const res = await messageService.getStats();
      setUnread(Number(res?.unread_count ?? 0) || 0);
    } catch {
      // 静默：通知角标属于锦上添花，不能影响主界面
    }
  }, []);

  useEffect(() => {
    const cleanups: Array<() => void> = [];
    // 闸门：社区版（无 /api/ent 路由）一次请求都不发，避免 404 刷屏
    isEnterpriseDeployment().then((enterprise) => {
      if (!enterprise) return;
      refresh();
      timer.current = window.setInterval(refresh, POLL_MS);
      const onVisible = () => {
        if (document.visibilityState === "visible") refresh();
      };
      document.addEventListener("visibilitychange", onVisible);
      cleanups.push(() =>
        document.removeEventListener("visibilitychange", onVisible),
      );
    });
    return () => {
      if (timer.current !== null) window.clearInterval(timer.current);
      cleanups.forEach((fn) => fn());
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
