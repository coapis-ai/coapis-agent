#!/usr/bin/env python3
"""
用户专业标签数据库迁移脚本
添加 user_tags 表和扩展 tags 表

使用方法：
    python scripts/migrate_user_tags.py /apps/ai/coapis [--dry-run]
"""

import sys
import os
import json
from pathlib import Path
from datetime import datetime

def migrate_database(data_dir: str, dry_run: bool = False):
    """迁移数据库"""
    
    print(f"开始迁移数据库...")
    print(f"数据目录: {data_dir}")
    print(f"预览模式: {dry_run}")
    
    # 1. 检查tags.json是否存在
    tags_file = Path(data_dir) / "tags.json"
    
    if not tags_file.exists():
        print(f"❌ tags.json 不存在: {tags_file}")
        return False
    
    # 2. 读取现有标签
    with open(tags_file, 'r', encoding='utf-8') as f:
        tags_data = json.load(f)
    
    print(f"当前标签数量: {len(tags_data.get('tags', []))}")
    
    # 3. 添加新字段到标签
    updated = False
    for tag in tags_data.get('tags', []):
        if 'category' not in tag:
            tag['category'] = 'business'  # 默认分类
            updated = True
        if 'icon' not in tag:
            tag['icon'] = '🏷️'  # 默认图标
            updated = True
        if 'description' not in tag:
            tag['description'] = tag.get('name', '')
            updated = True
    
    if updated:
        print("✅ 已添加标签新字段（category, icon, description）")
    
    # 4. 添加初始专业标签
    new_tags = [
        # 业务职能
        {"id": "hr", "name": "人力资源", "category": "business", "icon": "👥", "description": "人力资源管理"},
        {"id": "finance", "name": "财务管理", "category": "business", "icon": "💰", "description": "财务会计管理"},
        {"id": "project", "name": "项目管理", "category": "business", "icon": "📋", "description": "项目进度管理"},
        {"id": "legal", "name": "法务合规", "category": "business", "icon": "⚖️", "description": "法律合规事务"},
        {"id": "marketing", "name": "市场营销", "category": "business", "icon": "📣", "description": "市场营销推广"},
        {"id": "sales", "name": "销售管理", "category": "business", "icon": "💼", "description": "销售客户管理"},
        {"id": "service", "name": "客户服务", "category": "business", "icon": "🎧", "description": "客户服务支持"},
        {"id": "supply", "name": "供应链", "category": "business", "icon": "🚚", "description": "供应链管理"},
        
        # 行业领域
        {"id": "finance_industry", "name": "金融", "category": "industry", "icon": "🏦", "description": "金融行业"},
        {"id": "manufacturing", "name": "制造", "category": "industry", "icon": "🏭", "description": "制造业"},
        {"id": "retail", "name": "零售", "category": "industry", "icon": "🛒", "description": "零售行业"},
        {"id": "healthcare", "name": "医疗", "category": "industry", "icon": "🏥", "description": "医疗健康"},
        {"id": "education_industry", "name": "教育", "category": "industry", "icon": "🎓", "description": "教育培训"},
        {"id": "government", "name": "政府", "category": "industry", "icon": "🏛️", "description": "政府机构"},
        {"id": "tech_industry", "name": "科技", "category": "industry", "icon": "💻", "description": "科技互联网"},
        
        # 技术方向
        {"id": "frontend", "name": "前端开发", "category": "tech", "icon": "🎨", "description": "前端技术"},
        {"id": "backend", "name": "后端开发", "category": "tech", "icon": "⚙️", "description": "后端技术"},
        {"id": "data", "name": "数据分析", "category": "tech", "icon": "📊", "description": "数据分析"},
        {"id": "ai", "name": "AI/算法", "category": "tech", "icon": "🤖", "description": "人工智能"},
        {"id": "devops", "name": "运维", "category": "tech", "icon": "🔧", "description": "运维开发"},
        {"id": "qa", "name": "测试", "category": "tech", "icon": "🔍", "description": "质量测试"},
        {"id": "product", "name": "产品", "category": "tech", "icon": "💡", "description": "产品设计"},
        {"id": "design", "name": "设计", "category": "tech", "icon": "🎨", "description": "UI/UX设计"},
    ]
    
    # 检查是否已存在
    existing_ids = {tag['id'] for tag in tags_data.get('tags', [])}
    tags_to_add = [tag for tag in new_tags if tag['id'] not in existing_ids]
    
    if tags_to_add:
        tags_data.setdefault('tags', []).extend(tags_to_add)
        print(f"✅ 添加了 {len(tags_to_add)} 个新标签")
    
    # 5. 保存tags.json
    if not dry_run:
        # 备份原文件
        backup_file = tags_file.with_suffix('.json.backup')
        if tags_file.exists() and not backup_file.exists():
            import shutil
            shutil.copy(tags_file, backup_file)
            print(f"✅ 已备份原文件: {backup_file}")
        
        # 写入新文件
        with open(tags_file, 'w', encoding='utf-8') as f:
            json.dump(tags_data, f, ensure_ascii=False, indent=2)
        print(f"✅ 已更新 tags.json")
    else:
        print("⚠️  预览模式：未保存文件")
    
    # 6. 创建user_tags.json（用户标签关联表）
    user_tags_file = Path(data_dir) / "user_tags.json"
    
    if not user_tags_file.exists():
        user_tags_data = {
            "version": "1.0",
            "description": "用户专业标签关联表",
            "user_tags": []
        }
        
        if not dry_run:
            with open(user_tags_file, 'w', encoding='utf-8') as f:
                json.dump(user_tags_data, f, ensure_ascii=False, indent=2)
            print(f"✅ 已创建 user_tags.json")
        else:
            print("⚠️  预览模式：未创建 user_tags.json")
    else:
        print(f"✅ user_tags.json 已存在")
    
    print("\n迁移完成！")
    return True


def main():
    if len(sys.argv) < 2:
        print("使用方法: python migrate_user_tags.py <data_dir> [--dry-run]")
        print("示例: python migrate_user_tags.py /apps/ai/coapis")
        print("      python migrate_user_tags.py /apps/ai/coapis --dry-run")
        sys.exit(1)
    
    data_dir = sys.argv[1]
    dry_run = '--dry-run' in sys.argv
    
    if not os.path.exists(data_dir):
        print(f"❌ 数据目录不存在: {data_dir}")
        sys.exit(1)
    
    success = migrate_database(data_dir, dry_run)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
