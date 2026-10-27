# -*- coding: utf-8 -*-
"""会话资源三层呈现的挂载与契约验收（方案 §3.2 / §12.4）。

验收项**逐条对应设计方案**，不额外加设计里没有的要求：

    L0 左栏        —— 会话树 + L3 常驻入口（D3 下线顶栏按钮后唯一固定入口）
    L1 产出卡      —— 本轮产出：名称 + 大小·时间 + [预览][下载][转格式▾] + 版本徽标
    L2 资源条      —— 输入框上方：引用 + 产出，尾部「查看全部」
    L3 会话抽屉    —— 左栏入口 / 「查看全部」打开；状态标签用后端真实词表

四条历史事故都锁在这里：
  ① 组件写了却没挂载（资源条恒空）；
  ② 前端自造状态词表（published/ephemeral/derived/gone），后端发不出 → 死分支；
  ③ 顶栏资源按钮按 D3 下线后，L3 只剩「查看全部」这一个入口，而 L1/L2 无数据时
     整条不渲染 → 台账里有资源的老会话永远打不开抽屉；
  ④ 生产端 `_annotate_turn_resources` 零调用 → metadata.resources 恒空。
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

CLIENT = Path(__file__).resolve().parents[3] / "client" / "src"
RUNNER = Path(__file__).resolve().parents[2] / "coapis" / "app" / "runner" / "runner.py"

# 后端台账真实词表（chat_resources 的 status 列）
REAL_VOCAB = {"official", "draft", "orphan", "archived", "deleted", "missing"}
# 前端自造词：后端永远不会发出来，出现即死分支
FAKE_VOCAB = ("published", "ephemeral", "derived", "gone")


def _read(rel: str) -> str:
    path = CLIENT / rel
    assert path.exists(), f"缺少文件 {rel}"
    return path.read_text(encoding="utf-8")


def _shows_all(src: str) -> bool:
    """「查看全部」是否接上抽屉开关。

    抽屉按 D3（浮层可关）改成了**开/关切换** `setResourcesOpen((v) => !v)`，
    字面量 `setResourcesOpen(true)` 已不存在。守卫要锁的是「接上了开关」这件事，
    不是某个具体写法，故两种形态都算通过。
    """
    return bool(
        re.search(
            r"onShowAll=\{\(\)\s*=>\s*setResourcesOpen\((?:true|\(v\)\s*=>\s*!v)\)\}",
            src,
        ),
    )


def _code_only(src: str) -> str:
    """剥掉注释后再做词表断言。

    注释里出现 "gone" 不是缺陷（它正是在说明「已删除」），把它当违规会让验收
    测试自己制造假红——这条白烧过一轮。
    """
    src = re.sub(r"/\*.*?\*/", " ", src, flags=re.S)
    src = re.sub(r"^\s*//.*$", " ", src, flags=re.M)
    return src


def _status_keys(src: str) -> set[str]:
    """取组件状态词表的键集合——与后端词表做**集合相等**，不做子串扫描。"""
    block = re.search(r"STATUS_META[^=]*=\s*\{(.*?)\n\}", src, flags=re.S)
    assert block, "未找到 STATUS_META 状态词表"
    return set(re.findall(r"^\s*([a-z_]+):\s*\{", block.group(1), flags=re.M))


# ── 挂载 ──────────────────────────────────────────────────────────────


def test_resource_bar_mounted_above_input():
    """L2 资源条必须挂在聊天区与输入框之间（方案 §3.2）。"""
    src = _read("pages/Chat/index.tsx")
    assert "CoApisChatResourceBar" in src, "资源条组件未导入"
    assert "<CoApisChatResourceBar" in src, "资源条组件未挂载"
    assert _shows_all(src), "资源条未接「查看全部」→ L3"


def test_producer_card_merged_into_resource_bar():
    """「本轮产出」卡已按合并决策下线，产出由 L2 资源条单点承载。

    用户拍板：「本来产出」与「本轮资源」两张卡内容重复，合并为一张、保留「本轮资源」。
    这条断言是合并的守卫——产出卡组件文件保留（别处可复用），但聊天页不得再挂载它，
    否则两卡重复的旧问题会复活。
    """
    src = _read("pages/Chat/index.tsx")
    assert "<CoApisChatResources" not in src, "产出卡被挂回聊天页，两卡重复的问题复活"
    assert "<CoApisChatResourceBar" in src, "产出卡下线后必须由 L2 资源条承载产出"
    assert "onLocate={handleLocateResource}" in src, "资源条必须接住产出卡的「定位到消息」"


def test_drawer_mounted():
    """L3 会话资源抽屉必须挂载。"""
    src = _read("pages/Chat/index.tsx")
    assert "CoApisResourceDrawer" in src, "资源抽屉组件未导入"
    assert "<CoApisResourceDrawer" in src, "资源抽屉组件未挂载"


def test_ledger_hook_mounted():
    """台账还原钩子必须挂载（刷新后资源不丢）。"""
    src = _read("pages/Chat/index.tsx")
    assert "useChatResourceLedger" in src, "台账还原钩子未接入"
    assert "metaOf" in src, "未把台账 metaOf 传给资源组件"
    assert "attachChat" in src, "上传附件未带会话身份"


def test_locate_to_message_wired():
    """L2 产出的「定位到消息」必须接线（方案 §3.2 产出动作）。

    历史事故：Chat 页写好了 handleLocateResource 却没交给任何组件——函数存在、
    按钮不存在，等于没做。
    """
    bar = _read("pages/Chat/components/CoApisChatResourceBar.tsx")
    assert "onLocate" in bar, "资源条没有「定位到消息」"
    chat = _read("pages/Chat/index.tsx")
    assert "handleLocateResource" in chat, "Chat 页没有定位实现"
    assert "onLocate={handleLocateResource}" in chat, "定位实现未接到资源条"


# ── 入口（D3 / D-b）──────────────────────────────────────────────────


def test_l3_entry_from_sidebar():
    """L3 常驻入口在左栏（D-b）——具体落点是左栏当前会话的资源下拉。

    D3 已下线顶栏资源按钮，而 L1/L2 无数据时整条不渲染——入口若只挂在它们尾部，
    台账里有资源的老会话就永远打不开抽屉。左栏是常驻列，入口挂这里才成立；
    左栏内部不重复做一套图标，逐条表格由 Inline 面板的「查看全部」(onShowAll)
    打开页面级抽屉。断言这条链路，不断言某个具体图标名。
    """
    sidebar = _read("pages/Chat/components/ChatSessionSidebar/index.tsx")
    inline = _read("pages/Chat/components/ChatSessionResources/Inline.tsx")
    chat = _read("pages/Chat/index.tsx")
    assert "ChatSessionResourcesInline" in sidebar, "左栏没挂当前会话的资源下拉"
    assert "onShowAll" in inline, "Inline 面板没有打开抽屉的回调"
    assert "resourcesOpen" in chat and "setResourcesOpen" in chat, "Chat 页没有抽屉开关"
    assert "CoApisResourceDrawer" in chat, "Chat 页没挂 L3 抽屉"
    assert "open={resourcesOpen}" in chat, "L3 抽屉未接上抽屉开关"

    chat = _read("pages/Chat/index.tsx")
    assert _shows_all(chat), "左栏「查看全部」未接抽屉"

    # 折叠态只留展开按钮：D2 明确「左栏顶部不放资源入口」，D3 明确顶栏不得有资源按钮，
    # 收起左栏等于收起整条会话列表，资源入口跟着收起是设计本意，不是缺陷。
    start = sidebar.index("if (collapsed)")
    rail = sidebar[start: sidebar.index("styles.sidebar", start)]
    assert "onShowAll" not in rail, "左栏折叠态塞了资源入口（违背 D2）"


def test_l3_entry_not_in_header():
    """D3：顶栏不得再有资源按钮，也不得留悬空 prop（下线就要下线干净）。"""
    header = _read("pages/Chat/components/ChatSessionHeader/index.tsx")
    assert "onResources" not in header, "顶栏资源入口未下线（违背 D3）"
    assert "FolderOpen" not in header, "顶栏资源图标未下线（违背 D3）"
    chat = _read("pages/Chat/index.tsx")
    assert "onResources={" not in chat.replace(
        "onResources={() => setResourcesOpen(true)}", ""
    ), "Chat 页向顶栏传了悬空的资源回调"


# ── 契约 ─────────────────────────────────────────────────────────────


def test_direct_link_not_tokenized():
    """直链不得把 JWT 拼进 URL（方案 §12.3）。"""
    for rel in (
        "pages/Chat/components/CoApisChatResources.tsx",
        "pages/Chat/components/CoApisChatResourceBar.tsx",
        "pages/Chat/components/ChatSessionResources/index.tsx",
    ):
        src = _code_only(_read(rel))
        assert "getAccessToken()" not in src, f"{rel} 把 token 拼进了直链"


@pytest.mark.parametrize("rel", (
    "pages/Chat/components/CoApisChatResourceBar.tsx",
    "pages/Chat/components/ChatSessionResources/index.tsx",
))
def test_status_vocabulary_matches_backend(rel: str):
    """状态词表必须与后端**集合相等**（核查 R3）。

    后端发不出前端自造的词 → 那些分支是永远走不到的死代码，且「已删除」永远
    显示不出来；反过来后端会发而前端没映射的状态就显示成空白。
    """
    src = _code_only(_read(rel))
    assert _status_keys(src) == REAL_VOCAB, (
        f"{rel} 状态词表与后端不一致：{sorted(_status_keys(src))} vs {sorted(REAL_VOCAB)}"
    )
    for word in FAKE_VOCAB:
        assert f'"{word}"' not in src, f"{rel} 残留前端自造状态词 {word}"


def test_producer_card_fields_match_design():
    """L1 产出卡字段按方案 §3.2：名称 + 大小·时间 + 预览/下载/转格式 + 版本徽标。

    软删项灰显并标注「已删除」（R3），用后端真实词 statusDeleted。
    """
    src = _code_only(_read("pages/Chat/components/CoApisChatResources.tsx"))
    for token in ("styles.meta", "styles.itemDead", "styles.name",
                  "styles.versionTag", "chat.resources.preview",
                  "chat.resources.download", "chat.resources.convert",
                  "chat.resources.statusDeleted"):
        assert token in src, f"L1 产出卡缺方案要求的 {token}"
    for word in FAKE_VOCAB:
        assert f'"{word}"' not in src, f"L1 产出卡残留前端自造状态词 {word}"


# ── 生产端 ───────────────────────────────────────────────────────────


def test_turn_resources_annotated_on_production_path():
    """生产端必须真的调用 `_annotate_turn_resources`（核查 P0-1）。

    函数存在 ≠ 生效。这条断言只数调用点，不数定义。
    """
    src = RUNNER.read_text(encoding="utf-8")
    calls = [
        ln for ln in src.splitlines()
        if "_annotate_turn_resources(" in ln and not ln.strip().startswith("def ")
    ]
    assert calls, "_annotate_turn_resources 在生产路径上零调用 → 资源条恒空"
    assert "_turn_resources_from_ledger(" in src, "刷新后无台账兜底 → 历史轮资源条空"
