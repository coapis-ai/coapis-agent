import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useAppMessage } from "../../hooks/useAppMessage";
import { authApi } from "../../api/modules/auth";
import { useAgentStore } from "../../stores/agentStore";
import { useTheme } from "../../contexts/ThemeContext";
import { AuthStorage } from "../../utils/authStorage";

/**
 * 外部系统 SSO 回调落地页（模型A）。
 *
 * 外部系统登录成功后 302 回到本页面，query 携带：
 *   external_id, name(=external_name), timestamp, signature, state, redirect?
 * 本页读取后 POST /auth/external/login 完成验签 + 建用户 + 拿真 token，
 * 然后以与账号密码登录完全一致的方式完成登录跳转。
 *
 * 页面只出现一次（state 一次性），失败时展示错误并给出返回登录页的入口。
 */
export default function LoginCallbackPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const { isDark } = useTheme();
  const { message } = useAppMessage();
  const { setSelectedAgent } = useAgentStore();

  const [status, setStatus] = useState<"loading" | "error">("loading");
  const [errorMsg, setErrorMsg] = useState("");
  const ranRef = useRef(false);

  useEffect(() => {
    if (ranRef.current) return; // StrictMode 双保险
    ranRef.current = true;

    const externalId = searchParams.get("external_id");
    const signature = searchParams.get("signature");
    const state = searchParams.get("state");
    const timestampRaw = searchParams.get("timestamp");

    const rawRedirect = searchParams.get("redirect") || "/chat";
    const redirect =
      rawRedirect.startsWith("/") && !rawRedirect.startsWith("//")
        ? rawRedirect
        : "/chat";

    if (!externalId || !signature || !state || !timestampRaw) {
      setStatus("error");
      setErrorMsg(t("login.callbackMissingParams"));
      return;
    }

    const doLogin = async () => {
      try {
        // provider 缺省：后端从 state 还原（本页面无需知道是哪个系统）
        const res = await authApi.externalLogin({
          external_id: externalId,
          external_name: searchParams.get("name") || searchParams.get("external_name") || undefined,
          timestamp: parseInt(timestampRaw, 10),
          signature: signature,
          state: state,
          redirect,
        });
        if (res.token) {
          AuthStorage.login(res.token, res.username, {
            remember: true, // 外部系统登录默认保持会话（与"记住我"一致）
            display_name: res.display_name || res.username,
            default_agent_id: res.default_agent_id,
          });
          window.currentUserId = res.username;
          window.currentChannel = "";
          if (res.default_agent_id) {
            setSelectedAgent(res.default_agent_id);
          }
          if (res.first_login) {
            localStorage.setItem("coapis_first_login", "true");
          }
          if (res.auto_created) {
            message.success(t("login.callbackAutoCreated", { name: res.display_name || res.username }));
          } else {
            message.success(t("login.callbackSuccess"));
          }
          navigate(res.redirect || redirect, { replace: true });
        } else {
          setStatus("error");
          setErrorMsg(t("login.callbackNoToken"));
        }
      } catch (err) {
        setStatus("error");
        setErrorMsg(err instanceof Error ? err.message : t("login.callbackFailed"));
      }
    };

    doLogin();
  }, [searchParams, navigate, t, message, setSelectedAgent]);

  const bg = isDark
    ? "linear-gradient(135deg, #0f0c29 0%, #302b63 50%, #24243e 100%)"
    : "linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%)";
  const cardBg = isDark ? "#1f1f1f" : "#fff";
  const subColor = isDark ? "rgba(255,255,255,0.45)" : "#666";

  return (
    <div
      style={{
        height: "100vh",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        background: bg,
      }}
    >
      <div
        style={{
          width: 400,
          padding: 32,
          borderRadius: 12,
          background: cardBg,
          boxShadow: isDark
            ? "0 4px 24px rgba(0,0,0,0.4)"
            : "0 4px 24px rgba(0,0,0,0.1)",
          textAlign: "center",
        }}
      >
        {status === "loading" && (
          <>
            <div
              style={{
                width: 40,
                height: 40,
                margin: "0 auto 16px",
                border: "3px solid " + (isDark ? "rgba(255,255,255,0.2)" : "#e8e8e8"),
                borderTopColor: "#FF7F16",
                borderRadius: "50%",
                animation: "coapis-login-cb-spin 0.8s linear infinite",
              }}
            />
            <style>{`@keyframes coapis-login-cb-spin { to { transform: rotate(360deg); } }`}</style>
            <h3 style={{ margin: "0 0 8px", fontSize: 16, fontWeight: 600 }}>
              {t("login.callbackLoading")}
            </h3>
            <p style={{ margin: 0, fontSize: 13, color: subColor }}>
              {t("login.callbackLoadingHint")}
            </p>
          </>
        )}

        {status === "error" && (
          <>
            <div style={{ fontSize: 40, marginBottom: 12 }}>⚠️</div>
            <h3 style={{ margin: "0 0 8px", fontSize: 16, fontWeight: 600 }}>
              {t("login.callbackFailedTitle")}
            </h3>
            <p style={{ margin: "0 0 20px", fontSize: 13, color: subColor, wordBreak: "break-all" }}>
              {errorMsg}
            </p>
            <button
              onClick={() => navigate("/login", { replace: true })}
              style={{
                padding: "8px 24px",
                borderRadius: 8,
                border: "none",
                background: "#FF7F16",
                color: "#fff",
                fontSize: 14,
                cursor: "pointer",
              }}
            >
              {t("login.callbackBackToLogin")}
            </button>
          </>
        )}
      </div>
    </div>
  );
}
