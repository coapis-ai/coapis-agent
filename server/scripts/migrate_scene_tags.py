#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""场景数据迁移脚本：将 category 字段映射到 primary_tag_id

迁移内容：
1. 添加 primary_tag_id 字段（从 category 映射）
2. 添加 tag_ids 字段（初始化为 [primary_tag_id]）
3. 添加 short_description 字段（从 description 截取）
4. 添加 usage_count 字段（初始化为 0）

向后兼容：
- 保留旧的 category 和 tags 字段
- 不删除任何现有数据
"""

import json
import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any

# Category 映射表：旧 category 字段 → 新 primary_tag_id
CATEGORY_MAP = {
    "办公通用": "office-common",
    "审批服务": "approval-service",
    "规划编制": "planning-compilation",
    "监管执法": "supervision-enforcement",
    "数据分析": "data-analysis",
    "应急处置": "emergency-handling",
    "自然资源": "natural-resources",
    "生态环境": "ecological-environment",
    "农业农村": "agriculture-rural",
    "发展改革": "development-reform",
    "城乡建设": "housing-construction",
    "教育管理": "education",
    "林草湿荒": "forestry-grassland",
    "文化旅游": "culture-tourism",
    "卫生健康": "health",
    "综合执法": "comprehensive-enforcement",
    "公共服务": "public-service",
}


def migrate_scene(scene: Dict[str, Any]) -> Dict[str, Any]:
    """迁移单个场景数据
    
    Args:
        scene: 场景数据字典
        
    Returns:
        迁移后的场景数据
    """
    # 1. 添加 primary_tag_id 字段
    old_category = scene.get("category", "")
    primary_tag_id = CATEGORY_MAP.get(old_category, "office-common")  # 默认使用办公通用
    
    scene["primary_tag_id"] = primary_tag_id
    
    # 2. 添加 tag_ids 字段
    if "tag_ids" not in scene:
        scene["tag_ids"] = [primary_tag_id]
    
    # 3. 添加 short_description 字段
    if "short_description" not in scene:
        desc = scene.get("description", "")
        # 截取前50个字符作为简短描述
        scene["short_description"] = desc[:50] if len(desc) > 50 else desc
    
    # 4. 添加 usage_count 字段
    if "usage_count" not in scene:
        scene["usage_count"] = 0
    
    # 5. 更新时间戳
    scene["updated_at"] = datetime.now().isoformat()
    
    return scene


def migrate_scenes(data_dir: Path, dry_run: bool = False) -> None:
    """迁移所有场景数据
    
    Args:
        data_dir: 数据目录路径
        dry_run: 是否只预览不保存
    """
    scenes_file = data_dir / "scenes.json"
    
    if not scenes_file.exists():
        print(f"❌ 场景文件不存在: {scenes_file}")
        return
    
    # 读取场景文件
    with open(scenes_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    scenes = data.get("scenes", [])
    print(f"📊 读取场景数量: {len(scenes)}")
    print("-" * 80)
    
    # 统计信息
    stats = {
        "total": len(scenes),
        "migrated": 0,
        "skipped": 0,
        "errors": 0,
    }
    
    # 迁移每个场景
    for scene in scenes:
        scene_id = scene.get("id", "unknown")
        old_category = scene.get("category", "")
        
        # 检查是否已经迁移
        if "primary_tag_id" in scene:
            stats["skipped"] += 1
            print(f"  ⊙ {scene_id}: 已迁移 (primary_tag_id={scene['primary_tag_id']})")
            continue
        
        # 执行迁移
        try:
            migrate_scene(scene)
            stats["migrated"] += 1
            
            primary_tag_id = scene["primary_tag_id"]
            if primary_tag_id in CATEGORY_MAP.values():
                print(f"  ✓ {scene_id}: {old_category} → {primary_tag_id}")
            else:
                print(f"  ⚠ {scene_id}: {old_category} → {primary_tag_id} (使用默认值)")
        except Exception as e:
            stats["errors"] += 1
            print(f"  ✗ {scene_id}: 迁移失败 - {e}")
    
    print("-" * 80)
    print(f"📈 迁移统计:")
    print(f"  总数: {stats['total']}")
    print(f"  成功: {stats['migrated']}")
    print(f"  跳过: {stats['skipped']}")
    print(f"  错误: {stats['errors']}")
    
    if dry_run:
        print("\n⚠️  预览模式：未保存数据")
        return
    
    # 保存更新后的场景
    with open(scenes_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    
    print(f"\n✅ 迁移完成，数据已保存到: {scenes_file}")


def verify_migration(data_dir: Path) -> None:
    """验证迁移结果
    
    Args:
        data_dir: 数据目录路径
    """
    scenes_file = data_dir / "scenes.json"
    
    with open(scenes_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    scenes = data.get("scenes", [])
    
    print("🔍 验证迁移结果:")
    print("-" * 80)
    
    # 检查所有场景是否都有 primary_tag_id
    missing_primary_tag = []
    invalid_primary_tag = []
    
    for scene in scenes:
        scene_id = scene.get("id", "unknown")
        
        if "primary_tag_id" not in scene:
            missing_primary_tag.append(scene_id)
        elif scene["primary_tag_id"] not in CATEGORY_MAP.values():
            invalid_primary_tag.append((scene_id, scene["primary_tag_id"]))
    
    if missing_primary_tag:
        print(f"❌ 缺少 primary_tag_id 的场景: {missing_primary_tag}")
    else:
        print(f"✅ 所有场景都有 primary_tag_id 字段")
    
    if invalid_primary_tag:
        print(f"⚠️  无效 primary_tag_id 的场景:")
        for scene_id, tag_id in invalid_primary_tag:
            print(f"    {scene_id}: {tag_id}")
    else:
        print(f"✅ 所有 primary_tag_id 都有效")
    
    # 统计 tag_ids
    scenes_with_tag_ids = sum(1 for s in scenes if "tag_ids" in s)
    print(f"✅ 有 tag_ids 字段的场景: {scenes_with_tag_ids}/{len(scenes)}")
    
    # 统计 short_description
    scenes_with_short_desc = sum(1 for s in scenes if "short_description" in s)
    print(f"✅ 有 short_description 字段的场景: {scenes_with_short_desc}/{len(scenes)}")
    
    # 统计 usage_count
    scenes_with_usage = sum(1 for s in scenes if "usage_count" in s)
    print(f"✅ 有 usage_count 字段的场景: {scenes_with_usage}/{len(scenes)}")
    
    print("-" * 80)
    print("✅ 验证完成")


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="场景数据迁移脚本")
    parser.add_argument(
        "data_dir",
        nargs="?",
        default="/apps/ai/coapis",
        help="数据目录路径（默认: /apps/ai/coapis）"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只预览不保存"
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="验证迁移结果"
    )
    
    args = parser.parse_args()
    data_dir = Path(args.data_dir)
    
    print(f"📁 数据目录: {data_dir}")
    print()
    
    if args.verify:
        verify_migration(data_dir)
    else:
        migrate_scenes(data_dir, dry_run=args.dry_run)
