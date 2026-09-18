"""
用户场景服务
管理用户启用的场景和自定义场景
"""

import json
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone


class UserSceneService:
    """用户场景服务"""
    
    def __init__(self, data_dir: str):
        self.data_dir = Path(data_dir)
        self.user_scenes_file = self.data_dir / "user_scenes.json"
        self.scenes_file = self.data_dir / "scenes.json"
        # M1 域D：社区版 SQLite 仓储
        self._us_repo = None
        self._scene_repo = None
        try:
            from ..foundation.repository_factory import RepositoryFactory
            if (RepositoryFactory.is_initialized()
                    and RepositoryFactory.get_edition() == "community"):
                self._us_repo = RepositoryFactory.get_user_scene_repository()
                self._scene_repo = RepositoryFactory.get_scene_repository()
        except Exception:
            # 工厂未初始化（如单测）或非社区版 → 回退 JSON 路径
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
    
    def get_all_scenes(self) -> List[Dict[str, Any]]:
        """获取所有系统场景"""
        if self._scene_repo is not None:
            return self._scene_repo.get_all()
        if not self.scenes_file.exists():
            return []
        
        with open(self.scenes_file, 'r', encoding='utf-8') as f:
            scenes_data = json.load(f)
        
        return scenes_data.get('scenes', [])
    
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
