-- ============================================================
-- CoApis 社区版 · SQLite 数据库结构（唯一事实来源）
-- 决策 D-8（2026-09-15）：数据库结构必须生成 SQL 脚本，放在初始化中。
-- 执行方（均为幂等，可重复执行）：
--   1. foundation/migrations.py::_create_schema   —— 首次启动初始化
--   2. foundation/user_repository_sqlite.py::_create_tables —— 访问兜底
-- ============================================================

PRAGMA journal_mode = WAL;

-- ---------------- 用户主表 ----------------
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    salt TEXT NOT NULL,
    display_name TEXT,
    email TEXT,
    avatar_url TEXT,
    token_quota_monthly INTEGER DEFAULT 1000000,
    token_used_monthly INTEGER DEFAULT 0,
    role TEXT DEFAULT 'user',
    is_active INTEGER DEFAULT 1,
    created_at REAL,
    updated_at REAL,
    last_login_at REAL,
    muga_key TEXT,
    password_set_by_user INTEGER DEFAULT 0,
    onboarding_completed INTEGER DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);
CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
CREATE INDEX IF NOT EXISTS idx_users_created ON users(created_at);

-- ---------------- 用户设置（key-value） ----------------
CREATE TABLE IF NOT EXISTS user_settings (
    user_id TEXT NOT NULL,
    setting_key TEXT NOT NULL,
    setting_value TEXT,
    updated_at REAL,
    PRIMARY KEY (user_id, setting_key)
);

-- ---------------- 用户偏好（整包 JSON） ----------------
CREATE TABLE IF NOT EXISTS user_preferences (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    username TEXT,
    settings TEXT,
    updated_at REAL,
    UNIQUE(user_id)
);

-- ---------------- API 密钥 ----------------
CREATE TABLE IF NOT EXISTS api_keys (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    name TEXT NOT NULL,
    key_prefix TEXT NOT NULL,
    key_hash TEXT NOT NULL,
    scopes TEXT DEFAULT '[]',
    is_active INTEGER DEFAULT 1,
    created_at REAL,
    last_used_at REAL
);
CREATE INDEX IF NOT EXISTS idx_api_keys_user ON api_keys(user_id);

-- ---------------- 审计日志 ----------------
CREATE TABLE IF NOT EXISTS audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT,
    username TEXT,
    action TEXT NOT NULL,
    resource_type TEXT,
    resource_id TEXT,
    details TEXT,
    ip_address TEXT,
    user_agent TEXT,
    created_at REAL
);
CREATE INDEX IF NOT EXISTS idx_audit_logs_user ON audit_logs(user_id);
CREATE INDEX IF NOT EXISTS idx_audit_logs_action ON audit_logs(action);
CREATE INDEX IF NOT EXISTS idx_audit_logs_created ON audit_logs(created_at);

-- ---------------- 积分流水 ----------------
CREATE TABLE IF NOT EXISTS point_transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    amount INTEGER NOT NULL,
    balance_after INTEGER NOT NULL,
    transaction_type TEXT NOT NULL,
    description TEXT,
    reference_id TEXT,
    created_at REAL
);
CREATE INDEX IF NOT EXISTS idx_points_user ON point_transactions(user_id);

-- ---------------- Token 用量 ----------------
CREATE TABLE IF NOT EXISTS token_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    username TEXT,
    agent_id TEXT,
    model TEXT NOT NULL,
    input_tokens INTEGER DEFAULT 0,
    output_tokens INTEGER DEFAULT 0,
    total_tokens INTEGER DEFAULT 0,
    cost_cents REAL DEFAULT 0,
    created_at REAL
);
CREATE INDEX IF NOT EXISTS idx_token_usage_user ON token_usage(user_id);
CREATE INDEX IF NOT EXISTS idx_token_usage_created ON token_usage(created_at);

-- ---------------- 迁移状态（完成标记，F6） ----------------
CREATE TABLE IF NOT EXISTS migration_state (
    key TEXT PRIMARY KEY,
    value TEXT,
    updated_at REAL
);

-- ---------------- 外部系统绑定（SSO） ----------------
-- DDL kept in sync with SqliteExternalIdentityStore._ensure_table:
-- user_id is the local *username* (community convention, see
-- external_auth.py which reads binding["user_id"] as a username).
CREATE TABLE IF NOT EXISTS external_bindings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    external_system TEXT NOT NULL,
    external_user_id TEXT NOT NULL,
    display_name TEXT NOT NULL DEFAULT '',
    email TEXT NOT NULL DEFAULT '',
    extra_data TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    UNIQUE(external_system, external_user_id)
);
CREATE INDEX IF NOT EXISTS idx_bindings_user ON external_bindings(user_id);
