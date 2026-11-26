"""口令哈希的唯一实现（single source of truth）。

历史上本仓库存在 4 份互相分叉的口令哈希实现——``app/auth.py``、
``user_system/service.py``、``foundation/user_repository_impl.py``，以及企业版
``enterprise/database/repositories/user_repository.py`` 的内联副本——而仓库里
**没有任何用例覆盖口令校验**，因此行为漂移长期无人发现。本模块把它们收敛为
一份，其余位置一律薄壳转发，不得再各自实现。

规则（务必保持）：

1. 新口令一律走 bcrypt。bcrypt 的盐内嵌在哈希串里，不需要单独的 salt 列，
   因此企业版 ``users`` 表（无 salt 列）也能原生支持。
2. 旧式 ``SHA-256(salt + password)`` 仅用于校验存量记录，不再用于新建。
3. **校验路径绝不生成盐**。``hash_password`` 把 ``salt is None`` 解释为
   「生成一个新盐并改走 bcrypt」；校验时若沿用这个语义，每次都会现算一个
   随机摘要，与库中存量摘要恒不相等，账号会被永久锁死。故校验侧对缺失的盐
   一律按空串兜底。
4. 存量 SHA-256 记录在用户登录成功时惰性升级为 bcrypt（见 ``needs_rehash``），
   无需强制改密、无需停机迁移。
"""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from typing import Optional

__all__ = [
    "hash_password",
    "verify_password",
    "needs_rehash",
    "is_bcrypt",
    "generate_salt",
]

# 完整 bcrypt 摘要：$2<b>$/12$/ + 22 位盐 + 31 位摘要 = 60 字符。
# bcrypt 的 Rust 实现在摘要长度不足时会直接 panic（PanicException，非
# ValueError），故校验前必须先做格式判定，不能让畸形摘要进到 checkpw。
_BCRYPT_RE = re.compile(r"^\$2[abxy]?\$\d{2}\$[./A-Za-z0-9]{53}$")


def generate_salt() -> str:
    """生成新式随机盐（仅旧式 SHA-256 路径需要）。"""
    return secrets.token_hex(16)


def is_bcrypt(stored_hash: str) -> bool:
    """摘要是否为**格式完整**的 bcrypt（其盐内嵌在串中，校验时不需要外部 salt）。

    这里做完整格式判定而非仅看前缀：长度不足或字符非法的摘要会被 bcrypt 的
    Rust 实现直接 panic，必须在上游拦掉。
    """
    return bool(stored_hash) and _BCRYPT_RE.match(stored_hash) is not None


def hash_password(password: str, salt: Optional[str] = None) -> tuple[str, str]:
    """哈希口令，返回 ``(摘要, 盐)``。

    - ``salt is None`` → 新口令，走 bcrypt，返回 ``(bcrypt摘要, "$2b$")``。
      bcrypt 摘要自带盐，返回值里的 ``"$2b$"`` 只是占位，供仍带 salt 列的
      存储（社区版 SQLite）保持非空约束。
    - ``salt`` 给定 → 旧式 ``SHA-256(salt + password)``，原样返回该盐。
      仅为兼容存量数据与既有调用方保留，**新代码不要显式传 salt**。
    """
    if salt is None:
        import bcrypt

        hashed = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt())
        return hashed.decode("utf-8"), "$2b$"
    digest = hashlib.sha256((salt + password).encode("utf-8")).hexdigest()
    return digest, salt


def verify_password(password: str, stored_hash: str, salt: Optional[str] = None) -> bool:
    """校验口令，兼容 bcrypt（新）与 SHA-256（旧）两种摘要。

    ``salt`` 允许为 ``None``：企业版 ``users`` 表没有 salt 列，盐存在
    ``preferences`` JSON 里，迁移进来的老账号可能根本没有盐。此时按空串处理，
    **绝不能**交给 ``hash_password`` 去生成新盐（见模块文档第 3 条）。
    """
    if not stored_hash:
        return False
    if is_bcrypt(stored_hash):
        import bcrypt

        try:
            return bcrypt.checkpw(password.encode("utf-8"), stored_hash.encode("utf-8"))
        except (KeyboardInterrupt, SystemExit):
            raise
        except BaseException:
            # bcrypt 4.x 的 Rust 实现在摘要异常时抛 PanicException，它直接派生自
            # BaseException（`except Exception` 抓不到）；5.x 则抛 ValueError。
            # 两种都必须吞掉——口令校验绝不能把异常抛进登录接口变成 500。
            return False
    digest, _ = hash_password(password, salt or "")
    return hmac.compare_digest(digest, stored_hash)


def needs_rehash(stored_hash: str) -> bool:
    """存量摘要是否应升级为 bcrypt。

    在登录成功之后调用：若为真，用本次明文口令重新 ``hash_password(pwd)``
    并写回 ``password_hash`` 即可。bcrypt 摘要自带盐，因此写回时**不需要**
    （也不应依赖）salt 列——企业版仓储的更新白名单里没有 salt，传了会被
    静默丢弃，但不影响正确性。
    """
    return bool(stored_hash) and not is_bcrypt(stored_hash)
