import { useState, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate, useSearchParams } from "react-router-dom";
import { Button, Form, Input } from "antd";
import { useAppMessage } from "../../hooks/useAppMessage";
import { LockOutlined, UserOutlined } from "@ant-design/icons";
import { authApi } from "../../api/modules/auth";
import { useAgentStore } from "../../stores/agentStore";
import { useTheme } from "../../contexts/ThemeContext";

export default function LoginPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const { isDark } = useTheme();
  const [loading, setLoading] = useState(false);
  const [isRegister, setIsRegister] = useState(false);
  const [hasUsers, setHasUsers] = useState(true);
  const { message } = useAppMessage();

  useEffect(() => {
    authApi
      .getStatus()
      .then((res) => {
        if (!res.enabled) {
          navigate("/chat", { replace: true });
          return;
        }
        setHasUsers(res.has_users);
        if (!res.has_users) {
          setIsRegister(true);
        }
      })
      .catch(() => {});
  }, [navigate]);

  const { setSelectedAgent } = useAgentStore();
  const onFinish = async (values: { username: string; password: string; remember_me?: boolean }) => {
    setLoading(true);
    try {
      const raw = searchParams.get("redirect") || "/chat";
      const redirect =
        raw.startsWith("/") && !raw.startsWith("//") ? raw : "/chat";

      // 记住我: expires_in=0 表示永久 token（100年），不勾选则用默认7天
      const expires_in = values.remember_me ? 0 : undefined;
      
      // 使用 AuthStorage 统一管理登录状态
      const { AuthStorage } = await import('../../utils/authStorage');

      if (isRegister) {
        const res = await authApi.register(values.username, values.password);
        if (res.token) {
          // 使用 AuthStorage 登录
          AuthStorage.login(res.token, values.username, {
            remember: values.remember_me || false,
            display_name: values.username,
          });
          window.currentUserId = values.username;
          window.currentChannel = "";  // 控制台不设 channel，显示所有来源聊天
          // 用后端返回的 default_agent_id 重设 selectedAgent，断开旧 localStorage 污染链
          if (res.default_agent_id) {
            setSelectedAgent(res.default_agent_id);
          }
          // Store first_login flag for onboarding
          if (res.first_login) {
            localStorage.setItem("coapis_first_login", "true");
          }
          message.success(t("login.registerSuccess"));
          navigate(redirect, { replace: true });
        }
      } else {
        const res = await authApi.login(values.username, values.password, expires_in);
        if (res.token) {
          // 使用 AuthStorage 登录
          AuthStorage.login(res.token, values.username, {
            remember: values.remember_me || false,
            display_name: values.username,
          });
          window.currentUserId = values.username;
          window.currentChannel = "";  // 控制台不设 channel，显示所有来源聊天
          // 用后端返回的 default_agent_id 重设 selectedAgent，断开旧 localStorage 污染链
          if (res.default_agent_id) {
            setSelectedAgent(res.default_agent_id);
          }
          // Store first_login flag for onboarding
          if (res.first_login) {
            localStorage.setItem("coapis_first_login", "true");
          }
          navigate(redirect, { replace: true });
        } else {
          message.info(t("login.authNotEnabled"));
          navigate(redirect, { replace: true });
        }
      }
    } catch (err) {
      message.error(
        isRegister
          ? err instanceof Error
            ? err.message
            : t("login.registerFailed")
          : t("login.failed"),
      );
    } finally {
      setLoading(false);
    }
  };

  return (
    <div
      style={{
        height: "100vh",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        background: isDark
          ? "linear-gradient(135deg, #0f0c29 0%, #302b63 50%, #24243e 100%)"
          : "linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%)",
      }}
    >
      <div
        style={{
          width: 400,
          padding: 32,
          borderRadius: 12,
          background: isDark ? "#1f1f1f" : "#fff",
          boxShadow: isDark
            ? "0 4px 24px rgba(0,0,0,0.4)"
            : "0 4px 24px rgba(0,0,0,0.1)",
        }}
      >
        <div style={{ textAlign: "center", marginBottom: 32 }}>
          <img
            src="/coapis_logo.png"
            alt="CoApis"
            style={{ height: 96, marginBottom: 12 }}
          />
          <h2 style={{ margin: 0, fontWeight: 600, fontSize: 20 }}>
            {isRegister ? t("login.registerTitle") : t("login.title")}
          </h2>
          {!hasUsers && (
            <p
              style={{
                margin: "8px 0 0",
                color: isDark ? "rgba(255,255,255,0.45)" : "#666",
                fontSize: 13,
              }}
            >
              {t("login.firstUserHint")}
            </p>
          )}
        </div>

        <Form
          layout="vertical"
          onFinish={onFinish}
          autoComplete="off"
          size="large"
        >
          <Form.Item
            name="username"
            rules={[{ required: true, message: t("login.usernameRequired") }]}
          >
            <Input
              prefix={
                <UserOutlined
                  style={{
                    color: isDark ? "rgba(255,255,255,0.45)" : undefined,
                  }}
                />
              }
              placeholder={t("login.usernamePlaceholder")}
              autoFocus
            />
          </Form.Item>

          <Form.Item
            name="password"
            rules={[{ required: true, message: t("login.passwordRequired") }]}
          >
            <Input.Password
              prefix={
                <LockOutlined
                  style={{
                    color: isDark ? "rgba(255,255,255,0.45)" : undefined,
                  }}
                />
              }
              placeholder={t("login.passwordPlaceholder")}
            />
          </Form.Item>

          <Form.Item name="remember_me" valuePropName="checked" style={{ marginBottom: 8 }}>
            <label style={{ fontSize: 13, cursor: "pointer" }}>
              <input type="checkbox" style={{ marginRight: 6 }} />
              {t("login.rememberMe") || "记住我"}
            </label>
          </Form.Item>

          <Form.Item style={{ marginBottom: 0, marginTop: 8 }}>
            <Button
              type="primary"
              htmlType="submit"
              loading={loading}
              block
              style={{ height: 44, borderRadius: 8, fontWeight: 500 }}
            >
              {isRegister ? t("login.register") : t("login.submit")}
            </Button>
          </Form.Item>
        </Form>
      </div>
    </div>
  );
}
