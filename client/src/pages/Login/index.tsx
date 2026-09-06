import { useState, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate, useSearchParams } from "react-router-dom";
import { Button, Form, Input } from "antd";
import { useAppMessage } from "../../hooks/useAppMessage";
import { LockOutlined, UserOutlined } from "@ant-design/icons";
import { authApi, ExternalSystemInfo } from "../../api/modules/auth";
import { useAgentStore } from "../../stores/agentStore";
import { useTheme } from "../../contexts/ThemeContext";
import { AuthStorage } from "../../utils/authStorage";

export default function LoginPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const { isDark } = useTheme();
  const [loading, setLoading] = useState(false);
  const [isRegister, setIsRegister] = useState(false);
  const [hasUsers, setHasUsers] = useState(true);
  const [externalSystems, setExternalSystems] = useState<ExternalSystemInfo[]>([]);
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

    // 登录页下方"其他登录方式"：动态拉取已配置的外部系统（无配置则不显示）
    authApi
      .getExternalSystems()
      .then((list) => setExternalSystems(list || []))
      .catch(() => {});
  }, [navigate]);

  const [credSys, setCredSys] = useState<ExternalSystemInfo | null>(null);

  const handleExternalLogin = (sys: ExternalSystemInfo) => {
    if (sys.login_type === "credential") {
      // 复用主输入框：点中选中该系统（再点一次取消，回到 CoApis 登录），不弹窗
      setCredSys(credSys?.provider_id === sys.provider_id ? null : sys);
      return;
    }
    // SSO 跳转：整页去外部系统登录页（用户在对方页面输账号密码，登录后 302 回 /login/callback）
    authApi
      .getExternalLoginState(sys.provider_id)
      .then(({ login_url }) => {
        window.location.href = login_url;
      })
      .catch((err: unknown) => {
        message.error(
          err instanceof Error ? err.message : t("login.externalLoginFailed"),
        );
      });
  };

  const { setSelectedAgent } = useAgentStore();
  const onFinish = async (values: { username: string; password: string; remember_me?: boolean }) => {
    setLoading(true);
    try {
      const raw = searchParams.get("redirect") || "/chat";
      const redirect =
        raw.startsWith("/") && !raw.startsWith("//") ? raw : "/chat";

      // 记住我: expires_in=0 表示永久 token（100年），不勾选则用默认7天
      const expires_in = values.remember_me ? 0 : undefined;

      // 选中了外部系统（凭证直登）：复用本输入框，走 credential-login
      if (credSys) {
        const res = await authApi.credentialLogin(
          credSys.provider_id,
          values.username,
          values.password,
          redirect,
        );
        if (res.token) {
          AuthStorage.login(res.token, res.username, {
            remember: false,
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
          message.success(res.auto_created
            ? (t("login.callbackAutoCreated") || `已自动创建账号 ${res.display_name || res.username}`)
            : (t("login.callbackSuccess") || "登录成功"));
          navigate(redirect, { replace: true });
        }
        return;
      }

      if (isRegister) {
        const res = await authApi.register(values.username, values.password);
        if (res.token) {
          // 使用 AuthStorage 登录，传入后端返回的默认智能体 ID
          AuthStorage.login(res.token, values.username, {
            remember: values.remember_me || false,
            display_name: values.username,
            default_agent_id: res.default_agent_id,
          });
          window.currentUserId = values.username;
          window.currentChannel = "";  // 控制台不设 channel，显示所有来源聊天
          if (res.default_agent_id) {
            setSelectedAgent(res.default_agent_id);
          }
          // Store first_login flag for onboarding
          if (res.first_login) {
            localStorage.setItem("coapis_first_login", "true");
          }
          message.success(t("login.registerSuccess"));
          navigate(redirect, { replace: true });
        } else {
          message.info(t("login.authNotEnabled"));
          navigate(redirect, { replace: true });
        }
      } else {
        const res = await authApi.login(values.username, values.password, expires_in);
        if (res.token) {
          // 使用 AuthStorage 登录，传入后端返回的默认智能体 ID
          AuthStorage.login(res.token, values.username, {
            remember: values.remember_me || false,
            display_name: values.username,
            default_agent_id: res.default_agent_id,
          });
          window.currentUserId = values.username;
          window.currentChannel = "";  // 控制台不设 channel，显示所有来源聊天
          if (res.default_agent_id) {
            setSelectedAgent(res.default_agent_id);
          }
          // Store first_login flag for onboarding
          if (res.first_login) {
            localStorage.setItem("coapis_first_login", "true");
          }
          message.success(t("login.success"));
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
              placeholder={credSys ? "外部系统用户名" : t("login.usernamePlaceholder")}
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
              placeholder={credSys ? "外部系统密码" : t("login.passwordPlaceholder")}
            />
          </Form.Item>

          {!credSys && (
            <Form.Item name="remember_me" valuePropName="checked" style={{ marginBottom: 8 }}>
              <label style={{ fontSize: 13, cursor: "pointer" }}>
                <input type="checkbox" style={{ marginRight: 6 }} />
                {t("login.rememberMe") || "记住我"}
              </label>
            </Form.Item>
          )}

          <Form.Item style={{ marginBottom: 0, marginTop: 8 }}>
            <Button
              type="primary"
              htmlType="submit"
              loading={loading}
              block
              style={{ height: 44, borderRadius: 8, fontWeight: 500 }}
            >
              {credSys
                ? `登录（${credSys.name}）`
                : isRegister
                  ? t("login.register")
                  : t("login.submit")}
            </Button>
          </Form.Item>
        </Form>

        {externalSystems.length > 0 && (
          <div style={{ marginTop: 24 }}>
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: 12,
                margin: "0 0 16px",
              }}
            >
              <div
                style={{
                  flex: 1,
                  height: 1,
                  background: isDark ? "rgba(255,255,255,0.15)" : "#e8e8e8",
                }}
              />
              <span
                style={{
                  fontSize: 12,
                  color: isDark ? "rgba(255,255,255,0.45)" : "#999",
                  whiteSpace: "nowrap",
                }}
              >
                {t("login.otherLoginMethods")}
              </span>
              <div
                style={{
                  flex: 1,
                  height: 1,
                  background: isDark ? "rgba(255,255,255,0.15)" : "#e8e8e8",
                }}
              />
            </div>
            <div
              style={{
                display: "flex",
                justifyContent: "center",
                flexWrap: "wrap",
                gap: 12,
              }}
            >
              {externalSystems.map((sys) => (
                <Button
                  key={sys.provider_id}
                  onClick={() => handleExternalLogin(sys)}
                  style={{
                    padding: "6px 18px",
                    borderRadius: 8,
                    background:
                      credSys?.provider_id === sys.provider_id
                        ? "#FF7F16"
                        : isDark
                          ? "rgba(255,255,255,0.08)"
                          : "#fafafa",
                    color:
                      credSys?.provider_id === sys.provider_id
                        ? "#fff"
                        : undefined,
                  }}
                >
                  {sys.icon ? `${sys.icon} ` : ""}
                  {sys.name}
                </Button>
              ))}
              {credSys && (
                <p
                  style={{
                    margin: "10px 0 0",
                    fontSize: 12,
                    color: isDark ? "rgba(255,255,255,0.45)" : "#999",
                    textAlign: "center",
                  }}
                >
                  在上方输入{credSys.name}的账号密码即可登录，再次点击可切换回 CoApis 登录
                </p>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
