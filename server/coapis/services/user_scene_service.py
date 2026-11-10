"""
用户场景服务
管理用户启用的场景和自定义场景
"""

import json
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class UserSceneService:
    """用户场景服务

    仓储选择按 **版本 + 仓储能力**（见 __init__ 注释，与 SceneAgentService /
    TagService 同一把尺子）：企业版用 PostgreSQL 仓储，社区版用 M1 域D 的
    SQLite 仓储；工厂未初始化（如单测）或能力不满足时退回 JSON 文件兜底。
    """
    
    def __init__(self, data_dir: str):
        self.data_dir = Path(data_dir)
        self.user_scenes_file = self.data_dir / "user_scenes.json"
        self.scenes_file = self.data_dir / "scenes.json"
        self._us_repo = None
        self._scene_repo = None
        # 选仓判据 = **版本 + 仓储能力**，不是「企业包能否 import」。
        # 与 SceneAgentService / TagService 同批治理（2026-11-10「进入场景失败」
        # 根因）：社区镜像同样打包 coapis/enterprise/ 源码，is_enterprise_installed()
        # 在社区版恒为 True，旧写法因此走「企业版」分支把 SQLite 仓当 PG 仓，
        # 日志还写着 "using enterprise PostgreSQL repositories" —— 排查时指错方向。
        try:
            from ..foundation.repository_factory import RepositoryFactory
            if RepositoryFactory.is_initialized():
                edition = RepositoryFactory.get_edition()
                us_repo = RepositoryFactory.get_user_scene_repository()
                scene_repo = RepositoryFactory.get_scene_repository()
                # 能力自检：本服务只用到用户配置的 get/save 与系统场景的 get_all。
                # 缺任一方法 → 退回 JSON 兜底，绝不让「用户点开才 500」发生。
                missing = []
                if us_repo is not None and not all(
                        hasattr(us_repo, m) for m in ("get", "save")):
                    missing.append(f"user_scene={type(us_repo).__name__}")
                if scene_repo is not None and not hasattr(scene_repo, "get_all"):
                    missing.append(f"scene={type(scene_repo).__name__}")
                if missing:
                    logger.warning(
                        "UserSceneService repositories lack contract methods %s "
                        "(edition=%s) -> falling back to JSON files",
                        ", ".join(missing), edition,
                    )
                else:
                    self._us_repo = us_repo
                    self._scene_repo = scene_repo
                    logger.info(
                        "UserSceneService using %s (user_scene=%s, scene=%s, edition=%s)",
                        "enterprise PostgreSQL repositories" if edition == "enterprise"
                        else "community SQLite repositories",
                        type(us_repo).__name__ if us_repo is not None else "None",
                        type(scene_repo).__name__ if scene_repo is not None else "None",
                        edition,
                    )
        except Exception as e:
            logger.warning(
                f"Failed to get user-scene repositories: {e}, falling back to JSON")
            self._us_repo = None
            self._scene_repo = None

    def _load_user_scenes(self) -> Dict[str, Any]:
        """加载用户场景数据"""
        if not self.user_scenes_file.exists():
            return {
                "version": "1.0",
                "user_scenes": []
            }
        
        with open(self.user_scenes_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    def _save_user_scenes(self, data: Dict[str, Any]):
        """保存用户场景数据"""
        with open(self.user_scenes_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    
    def get_user_scenes(self, user_id: str) -> Dict[str, Any]:
        """获取用户的场景配置"""
        if self._us_repo is not None:
            row = self._us_repo.get(user_id)
            if row:
                return {
                    'enabled_scenes': row.get('enabled_scenes', []),
                    'custom_scenes': row.get('custom_scenes', []),
                    'preferences': row.get('preferences', {})
                }
            # 默认返回空配置
            return {
                'enabled_scenes': [],
                'custom_scenes': [],
                'preferences': {}
            }
        data = self._load_user_scenes()
        
        for user_scene in data.get('user_scenes', []):
            if user_scene.get('user_id') == user_id:
                return {
                    'enabled_scenes': user_scene.get('enabled_scenes', []),
                    'custom_scenes': user_scene.get('custom_scenes', []),
                    'preferences': user_scene.get('preferences', {})
                }
        
        # 默认返回空配置
        return {
            'enabled_scenes': [],
            'custom_scenes': [],
            'preferences': {}
        }
    
    def set_user_scenes(self, user_id: str, scenes_data: Dict[str, Any]) -> bool:
        """设置用户的场景配置"""
        if self._us_repo is not None:
            now = datetime.now(timezone.utc).isoformat()
            self._us_repo.save({
                'user_id': user_id,
                'enabled_scenes': scenes_data.get('enabled_scenes', []),
                'custom_scenes': scenes_data.get('custom_scenes', []),
                'preferences': scenes_data.get('preferences', {}),
                'created_at': now,
                'updated_at': now,
            })
            return True
        data = self._load_user_scenes()

        # 查找现有记录
        found = False
        for user_scene in data.get('user_scenes', []):
            if user_scene.get('user_id') == user_id:
                user_scene['enabled_scenes'] = scenes_data.get('enabled_scenes', [])
                user_scene['custom_scenes'] = scenes_data.get('custom_scenes', [])
                user_scene['preferences'] = scenes_data.get('preferences', {})
                user_scene['updated_at'] = datetime.now().isoformat()
                found = True
                break
        
        # 创建新记录
        if not found:
            data.setdefault('user_scenes', []).append({
                'user_id': user_id,
                'enabled_scenes': scenes_data.get('enabled_scenes', []),
                'custom_scenes': scenes_data.get('custom_scenes', []),
                'preferences': scenes_data.get('preferences', {}),
                'created_at': datetime.now().isoformat(),
                'updated_at': datetime.now().isoformat()
            })
        
        self._save_user_scenes(data)
        return True
    
    @staticmethod
    def _filter_usable_scenes(scenes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """剔除已删除/停用场景。

        仓储层 ``get_all()`` 不带状态过滤（SQLite 实现等价于 ``list_scenes()``），
        软删场景会原样返回 → 推荐位把已删除场景端给用户。过滤统一放这里，
        仓储与 JSON 两条数据源口径一致。
        """
        return [
            s for s in scenes
            if (s.get("status") or "active") not in ("deleted", "disabled")
        ]

    def get_all_scenes(self) -> List[Dict[str, Any]]:
        """获取所有系统场景（不含已删除/停用）"""
        if self._scene_repo is not None:
            return self._filter_usable_scenes(self._scene_repo.get_all())
        if not self.scenes_file.exists():
            return []

        with open(self.scenes_file, 'r', encoding='utf-8') as f:
            scenes_data = json.load(f)

        return self._filter_usable_scenes(scenes_data.get('scenes', []))
    
    def get_recommended_scenes(self, user_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        """根据用户偏好推荐场景"""
        user_config = self.get_user_scenes(user_id)
        enabled_ids = set(user_config.get('enabled_scenes', []))
        
        # 获取所有场景
        all_scenes = self.get_all_scenes()
        
        # 过滤未启用的
        available_scenes = [s for s in all_scenes if s.get('id') not in enabled_ids]
        
        # 按使用次数排序
        available_scenes.sort(key=lambda x: x.get('usage_count', 0), reverse=True)
        
        # 返回top N
        return available_scenes[:limit]
