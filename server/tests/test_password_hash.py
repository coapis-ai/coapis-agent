"""口令哈希回归测试：锁定唯一实现，并防止再次分叉。

背景：本仓库曾存在 4 份互相分叉的口令哈希实现（``app/auth.py``、
``app/user_store.py``、``user_system/service.py``、
``foundation/user_repository_impl.py``，外加企业版仓储的一份内联副本），
而**没有任何用例覆盖口令校验**，因此行为漂移长期无人发现。现已收敛为
``coapis/foundation/password.py`` 一份，其余位置薄壳转发。

本文件锁两件事：
1. 唯一实现的行为契约——尤其是「校验路径绝不生成盐」这条，一旦回退，
   存量 SHA-256 账号会因每次现算随机摘要而恒不匹配，表现为登录必败；
2. 各转发点必须指向同一函数对象，防止有人再复制一份实现回去。
"""
from __future__ import annotations

import hashlib

import pytest

from coapis.foundation import password as pw


def _sha256(salt: str, password: str) -> str:
    return hashlib.sha256((salt + password).encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# 1. 唯一实现的行为契约
# ---------------------------------------------------------------------------


def test_new_password_uses_bcrypt() -> None:
    """新建口令一律 bcrypt，且摘要自带盐、不依赖外部 salt 列。"""
    hashed, salt = pw.hash_password("admin123")
    assert hashed.startswith("$2b$")
    assert salt == "$2b$"  # 占位值，仅为满足仍带 salt 列的存储的非空约束
    assert pw.is_bcrypt(hashed)


def test_explicit_salt_keeps_legacy_sha256() -> None:
    """显式传 salt 时保持旧式 SHA-256 语义，兼容存量数据与既有调用方。"""
    hashed, returned = pw.hash_password("admin123", "deadbeef")
    assert hashed == _sha256("deadbeef", "admin123")
    assert returned == "deadbeef"
    assert not pw.is_bcrypt(hashed)


def test_bcrypt_roundtrip_and_wrong_password() -> None:
    hashed, _ = pw.hash_password("s3cret")
    assert pw.verify_password("s3cret", hashed) is True
    assert pw.verify_password("wrong", hashed) is False


def test_legacy_hash_with_salt_verifies() -> None:
    """存量记录（带盐）必须能校验通过。"""
    stored = _sha256("cafe01", "oldpassword")
    assert pw.verify_password("oldpassword", stored, "cafe01") is True
    assert pw.verify_password("wrong", stored, "cafe01") is False


@pytest.mark.parametrize("salt", [None, ""])
def test_legacy_hash_without_salt_verifies(salt) -> None:
    """存量记录无盐时必须按空盐兜底校验通过。

    这是最关键的回归点：企业版 users 表无 salt 列（盐在 preferences JSON 里），
    迁移进来的老账号可能没有盐。若校验路径把 ``salt=None`` 交给
    ``hash_password``，它会「生成一个新盐并改走 bcrypt」，每次现算的随机摘要
    恒不等于库中存量摘要，账号即被永久锁死。
    """
    stored = _sha256("", "admin123")
    assert pw.verify_password("admin123", stored, salt) is True


def test_empty_stored_hash_never_matches() -> None:
    """空摘要一律校验失败，不得抛异常。"""
    assert pw.verify_password("anything", "") is False
    assert pw.verify_password("anything", "", None) is False


@pytest.mark.parametrize(
    "stored",
    [
        "$2b$12$truncated",  # 长度不足：bcrypt 4.x 的 Rust 实现会 panic
        "$2b$12$" + "a" * 52,  # 少一位
        "$2b$12$" + "a" * 54,  # 多一位
        "$2b$12$" + "!" * 53,  # 非法字符（base64 字母表之外）
        "$2b$12",  # 只有前缀
        "not-a-hash",
    ],
)
def test_malformed_bcrypt_hash_fails_gracefully(stored: str) -> None:
    """格式异常的 bcrypt 摘要应返回 False，而不是抛异常。

    bcrypt 4.x（企业版镜像在用）的 Rust 实现在摘要长度不足时抛
    ``PanicException``，它直接派生自 ``BaseException``，``except Exception``
    抓不到——早先就是靠 ``is_bcrypt`` 只看前缀而放行了畸形摘要。现在
    ``is_bcrypt`` 做完整格式判定，必须在进入 ``checkpw`` 之前拦掉。
    """
    assert pw.is_bcrypt(stored) is False
    assert pw.verify_password("x", stored) is False


def test_wellformed_bcrypt_hash_is_recognised() -> None:
    """完整格式的摘要必须判定为 bcrypt，别把拦截做过头。"""
    hashed, _ = pw.hash_password("admin123")
    assert len(hashed) == 60
    assert pw.is_bcrypt(hashed) is True


# ---------------------------------------------------------------------------
# 2. 惰性升级
# ---------------------------------------------------------------------------


def test_needs_rehash_only_for_legacy() -> None:
    """仅存量 SHA-256 需要升级；bcrypt 已是目标格式。"""
    assert pw.needs_rehash(_sha256("cafe01", "x")) is True
    assert pw.needs_rehash(_sha256("", "x")) is True
    assert pw.needs_rehash(pw.hash_password("x")[0]) is False
    assert pw.needs_rehash("") is False


def test_upgrade_keeps_password_verifiable() -> None:
    """升级后新摘要仍可用同一口令校验，且不再需要升级。"""
    old_hash, _ = pw.hash_password("admin123", "cafe01")  # 存量 SHA-256
    assert pw.needs_rehash(old_hash) is True

    new_hash, _ = pw.hash_password("admin123")  # 登录成功后重新哈希
    assert pw.verify_password("admin123", new_hash) is True
    assert pw.needs_rehash(new_hash) is False


# ---------------------------------------------------------------------------
# 3. 防分叉：所有转发点必须指向同一实现
# ---------------------------------------------------------------------------

_FORWARDERS = [
    ("coapis.app.auth", "_hash_password", "verify_password"),
    ("coapis.app.user_store", "_hash_password", "verify_password"),
    ("coapis.user_system.service", "_hash_password", "verify_password"),
]


@pytest.mark.parametrize("module_name,hash_attr,verify_attr", _FORWARDERS)
def test_forwarders_point_to_single_implementation(
    module_name, hash_attr, verify_attr
) -> None:
    """各模块的口令函数必须是 ``foundation.password`` 的同一对象。

    若本测试失败，说明有人又在某个模块里复制了一份实现——这正是历史上
    4 份实现互相分叉、且因零用例覆盖而无人发现的根因。
    """
    import importlib

    mod = importlib.import_module(module_name)
    assert getattr(mod, hash_attr) is pw.hash_password, (
        f"{module_name}.{hash_attr} 不再是唯一实现，疑似被复制回内联版本"
    )
    assert getattr(mod, verify_attr) is pw.verify_password, (
        f"{module_name}.{verify_attr} 不再是唯一实现，疑似被复制回内联版本"
    )


def test_enterprise_repository_has_no_inline_hashing() -> None:
    """企业版仓储不得再内联实现口令哈希，必须复用社区版唯一实现。"""
    import importlib.util

    spec = importlib.util.find_spec("coapis.enterprise")
    if spec is None or spec.origin is None:
        pytest.skip("企业版包未安装，跳过")

    from pathlib import Path

    repo_file = Path(spec.origin).parent / "database/repositories/user_repository.py"
    if not repo_file.exists():
        pytest.skip("企业版用户仓储文件不存在，跳过")

    source = repo_file.read_text(encoding="utf-8")
    assert "def _hash_password" not in source, "企业版仓储又内联了哈希实现"
    assert "def verify_password" not in source, "企业版仓储又内联了校验实现"
    assert "bcrypt.hashpw" not in source, "企业版仓储绕过唯一实现直接调 bcrypt"
