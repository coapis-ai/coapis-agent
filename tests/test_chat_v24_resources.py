"""v24 · 聊天资源四改的回归锁（小蜜蜂 2026-11-09）

锁住四件事，全部用「源码即事实」的方式断言（与 tests/test_myfiles_search.py
同风格：不连服务、不猜行为，改坏了就直接红）：

1. 聊天侧资源接口**不得带出软删行**（include_deleted 必须全 False）；
2. 台账读面（resource_ledger）默认值保持 True —— 软删行只在管理面可见；
3. 聊天里不得再有「判断」入口，判断台账必须挂在「我的空间」；
4. 左栏资源面板与聊天答案条的缩进/宽度口径（不得回到 17px 缩进 + 8px 右隙）。
"""

from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CHATS = REPO / "server" / "coapis" / "app" / "routers" / "chats.py"
BAR = REPO / "client" / "src" / "pages" / "Chat" / "components" / "CoApisChatResourceBar.tsx"
BAR_CSS = BAR.with_name("CoApisChatResourceBar.module.css")
INLINE_LESS = (
    REPO
    / "client"
    / "src"
    / "pages"
    / "Chat"
    / "components"
    / "ChatSessionResources"
    / "inline.module.less"
)
CHAT_INDEX = REPO / "client" / "src" / "pages" / "Chat" / "index.tsx"
MYSPACE = REPO / "client" / "src" / "pages" / "MySpace" / "index.tsx"
JUDGMENT = REPO / "client" / "src" / "pages" / "MySpace" / "JudgmentPanel.tsx"
ZH_LOC = REPO / "client" / "src" / "locales" / "zh.json"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _chat_resources_fn() -> str:
    """只取「会话资源列表」这一个函数体，避免全文搜到无关的 include_deleted。"""
    src = CHATS.read_text(encoding="utf-8")
    start = src.index("async def list_chat_resources(")
    nxt = src.find("@router.", start + 10)
    return src[start : (nxt if nxt > 0 else len(src))]


def test_chat_resources_never_include_deleted():
    """聊天侧 6 处取数必须过滤软删行（问题 4）。"""
    body = _chat_resources_fn()
    # 只数代码，不数注释（注释里写着「此前 6 处全部 include_deleted=True」，
    # 那是给人看的说明，不是取数口径）。
    code = "\n".join(
        ln for ln in body.split("\n") if not ln.strip().startswith("#")
    )
    n_false = code.count("include_deleted=False")
    n_true = code.count("include_deleted=True")
    assert n_true == 0, f"聊天侧仍有 {n_true} 处 include_deleted=True（已删除文件会进 UI）"
    assert n_false >= 6, f"聊天侧过滤点应为 6 处，实测 {n_false} 处"


def test_ledger_admin_view_still_shows_deleted():
    """台账管理面（我的空间 · 资源台账）仍要能看到软删行——聊天侧屏蔽、
    管理面保留，两侧各用各的尺子。"""
    ledger = (REPO / "server" / "coapis" / "foundation" / "resource_ledger.py").read_text(
        encoding="utf-8"
    )
    i = ledger.index("def list_resources_for_chat(")
    assert "include_deleted: bool = False" in ledger[i : i + 400]
    files = (REPO / "server" / "coapis" / "app" / "routers" / "files.py").read_text(
        encoding="utf-8"
    )
    seg = files[files.index('router.get("/resources")') :]
    assert "include_deleted=False" not in seg[:3000], "台账管理面不得过滤软删行"


def test_chat_has_no_judgment_entry():
    """判断是审计日志，聊天侧不得再有入口（问题 2/3）。"""
    bar = BAR.read_text(encoding="utf-8")
    idx = CHAT_INDEX.read_text(encoding="utf-8")
    assert "onJudgment" not in bar, "答案条仍有判断回调"
    assert '"decision.entry"' not in bar, "答案条仍渲染判断入口"
    assert "CoApisDecisionPanel" not in idx, "聊天页仍挂载判断浮窗"
    assert "onJudgment" not in idx, "聊天页仍传入判断回调"


def test_judgment_ledger_lives_in_myspace():
    """判断台账搬到「我的空间」，且字段用后端真实列（问题 3 不留尾巴）。"""
    panel = JUDGMENT.read_text(encoding="utf-8")
    idx = MYSPACE.read_text(encoding="utf-8")
    assert "JudgmentPanel" in idx and "'judgment'" in idx
    assert "dataIndex: 'created_at'" in panel, "时间列必须用后端真实列 created_at"
    assert "dataIndex: 'ts'" not in panel, "ts 这一列库里没有"
    assert "row.reason" in panel, "判由必须用真实列 reason"
    assert "AuditOutlined" in panel


def test_chat_resource_bar_chips_are_filters() -> None:
    """v25：chip 就是这一组的开关（名字 + 数量 + ▾），收起态不渲染任何列表。

    小蜜蜂 2026-11-09 说「下拉直接放在引用、产出上面，各自点击展示各自的」。
    v24 做成「chip 筛子 + 右侧展开按钮」，2026-11-10 复盘发现真问题：同一个
    面板里 **三个开关（chip / 展开 / 查看全部）管一件事**，chip 与展开各说
    各话。v25 收敛为：chip 自己带 ▾，点一下展开这一组、再点收起；独立的
    「展开/收起」按钮删除；「查看全部」改名「会话全部资源」。

    源码级断言：本仓库前端无测试运行器，形状锁在这里。
    """
    comp = _read(BAR)
    css = _read(BAR_CSS)
    zh = _read(ZH_LOC)

    # ① 一次只渲染 chip 点开的那一组（tab === "all" 收起态什么都不渲染）
    assert "if (tab !== source) return null;" in comp
    # ② 组列表只在 chip 展开时渲染
    assert '{tab !== "all" && (' in comp
    # ③ 单一状态机：tab 三态 + noCap（放开「每组最多 8 行」的限制）
    assert 'const [tab, setTab] = useState<Tab>("all")' in comp
    assert "const [noCap, setNoCap] = useState(false)" in comp
    assert "toggleTab" in comp
    # ④ chip 上带下拉符号，展开时转 180°
    assert "styles.chipCaret" in comp
    assert 'data-open={open ? "true" : "false"}' in comp
    assert "chip-caret" in css
    assert 'chip-caret[data-open="true"]' in css
    # ⑤ 计数为 0 的组不出现这颗 chip；空组不渲染
    assert "if (count === 0) return null;" in comp
    assert "if (!list.length) return null;" in comp
    # ⑥ 展开态高亮由 chip 自己表达
    assert "styles.groupChipActive" in comp
    # ⑦ 会话级入口在头部
    assert "onShowAll" in comp
    # ⑧ 无「判断」入口（判官审计不外显）
    assert "judge" not in comp
    # ⑨ v25：面板里不得再有第二个展开开关，也不得有组头（与 chip 重复）
    assert "styles.collapse" not in comp
    assert "styles.groupHead" not in comp
    # ⑩ v25 命名口径：本轮资源 / 会话全部资源
    assert 't("chat.resources.barTitleRound"' in comp
    assert 't("chat.resources.viewAllSession"' in comp
    assert '"barTitleRound": "本轮资源"' in zh
    assert '"viewAllSession": "会话全部资源"' in zh



def test_left_panel_indent_is_flush_with_card():
    """左栏资源面板：与会话卡片同宽、左边缩进 6px（问题 1/3）。"""
    less = INLINE_LESS.read_text(encoding="utf-8")
    assert "padding-left: 17px" not in less, "缩进回到 17px（4 个字口径）"
    assert less.count("padding-left: 6px") >= 2, "两处 .list 必须同为 6px"
    head = less[less.index(".panel {") : less.index(".panel {") + 200]
    assert "margin: 0 0 6px 0" in head, "面板右边不得再留 8px 空隙"
    assert "padding-left: 0" in head, "面板自身不得再有左内边距"
    # 宽度：flex 项必须拉满整行，否则两组各自只有内容宽（实测 204px < 卡片 283px）
    assert ".body,\n.group,\n.list,\n.row" in less, "body/group/list/row 必须统一拉满"
    assert "flex: 1 1 100%" in less, ".wrap 的 flex 项必须占满整行"
