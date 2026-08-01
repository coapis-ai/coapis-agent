#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Add community menu tags to tags.json"""

import json
from pathlib import Path

tags_file = Path("/apps/ai/coapis-dev/tags.json")
with open(tags_file, 'r', encoding='utf-8') as f:
    data = json.load(f)

tags = data.get("tags", [])

menu_tags = [
    {
        "id": "menu-chat",
        "name": "聊天",
        "icon": "MessageOutlined",
        "type": "menu",
        "description": "AI 对话与助手交互",
        "keywords": ["对话", "助手", "chat"],
        "related_skills": [],
        "sort_order": 1,
        "show_in_menu": True,
        "enabled": True,
        "created_at": "2026-08-01T00:00:00.000000",
        "updated_at": "2026-08-01T00:00:00.000000",
        "metadata": {
            "path": "/chat",
            "labelKey": "nav.chat",
            "permission": "chat",
            "isActive": True
        }
    },
    {
        "id": "menu-workbench",
        "name": "工作场景",
        "icon": "AppstoreOutlined",
        "type": "menu",
        "description": "场景化工作台与智能体",
        "keywords": ["场景", "工作台", "workbench"],
        "related_skills": [],
        "sort_order": 2,
        "show_in_menu": True,
        "enabled": True,
        "created_at": "2026-08-01T00:00:00.000000",
        "updated_at": "2026-08-01T00:00:00.000000",
        "metadata": {
            "path": "/workbench",
            "labelKey": "nav.workbench",
            "permission": "scene",
            "isActive": True,
            "childrenSource": "tags"
        }
    },
    {
        "id": "menu-myspace",
        "name": "我的空间",
        "icon": "FolderOutlined",
        "type": "menu",
        "description": "个人文件与知识库管理",
        "keywords": ["文件", "空间", "myspace"],
        "related_skills": [],
        "sort_order": 3,
        "show_in_menu": True,
        "enabled": True,
        "created_at": "2026-08-01T00:00:00.000000",
        "updated_at": "2026-08-01T00:00:00.000000",
        "metadata": {
            "path": "/workspace/myspace",
            "labelKey": "nav.myspace",
            "permission": "myspace",
            "isActive": True
        }
    },
    {
        "id": "menu-settings",
        "name": "设置",
        "icon": "SettingOutlined",
        "type": "menu",
        "description": "系统配置与个人设置",
        "keywords": ["设置", "配置", "settings"],
        "related_skills": [],
        "sort_order": 4,
        "show_in_menu": True,
        "enabled": True,
        "created_at": "2026-08-01T00:00:00.000000",
        "updated_at": "2026-08-01T00:00:00.000000",
        "metadata": {
            "path": "/settings",
            "labelKey": "nav.settings",
            "permission": "profile",
            "isActive": True
        }
    }
]

new_tags = [t for t in tags if t.get("type") != "menu"]
new_tags.extend(menu_tags)
new_tags.sort(key=lambda t: t.get("sort_order", 0))

data["tags"] = new_tags

with open(tags_file, 'w', encoding='utf-8') as f:
    json.dump(data, f, ensure_ascii=False, indent=4)

print(f"Added {len(menu_tags)} menu tags to tags.json")
print(f"Total tags: {len(new_tags)}")
