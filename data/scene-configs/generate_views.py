#!/usr/bin/env python3
"""
场景配置生成脚本
从 scenes.json 和 categories.json 生成两个维度的场景列表
"""

import json
from pathlib import Path
from typing import Dict, List, Any


def load_json(file_path: Path) -> Dict[str, Any]:
    """加载 JSON 文件"""
    with open(file_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_json(data: Dict[str, Any], file_path: Path) -> None:
    """保存 JSON 文件"""
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def generate_nature_view(scenes: List[Dict], categories: Dict) -> Dict[str, Any]:
    """生成按性质分类的场景列表"""
    
    nature_categories = categories['dimensions']['nature']['categories']
    
    # 初始化分类字典
    nature_view = {
        "dimension": "nature",
        "dimension_name": "按性质分类",
        "categories": []
    }
    
    # 为每个分类添加场景列表
    for category in nature_categories:
        category_scenes = []
        
        # 找到属于该分类的所有场景
        for scene in scenes:
            if scene['properties']['nature'] == category['id']:
                # 添加场景基本信息
                category_scenes.append({
                    "id": scene['id'],
                    "name": scene['name'],
                    "description": scene['description'],
                    "icon": scene['icon'],
                    "agent_id": scene['agent_id'],
                    "is_generic": scene['properties']['is_generic'],
                    "frequency": scene['properties']['frequency'],
                    "tags": scene.get('tags', {})
                })
        
        # 添加到视图
        nature_view['categories'].append({
            "id": category['id'],
            "name": category['name'],
            "icon": category['icon'],
            "description": category['description'],
            "sort_order": category['sort_order'],
            "scene_count": len(category_scenes),
            "scenes": category_scenes
        })
    
    return nature_view


def generate_domain_view(scenes: List[Dict], categories: Dict) -> Dict[str, Any]:
    """生成按领域分类的场景列表"""
    
    domain_categories = categories['dimensions']['domain']['categories']
    
    # 初始化分类字典
    domain_view = {
        "dimension": "domain",
        "dimension_name": "按领域分类",
        "categories": []
    }
    
    # 为每个领域添加场景列表
    for domain in domain_categories:
        domain_scenes = []
        
        # 找到属于该领域的所有场景
        for scene in scenes:
            scene_domains = scene['properties']['domains']
            
            # 检查场景是否属于该领域（通用场景或专属场景）
            if 'all' in scene_domains or domain['id'] in scene_domains:
                # 添加场景基本信息
                domain_scenes.append({
                    "id": scene['id'],
                    "name": scene['name'],
                    "description": scene['description'],
                    "icon": scene['icon'],
                    "agent_id": scene['agent_id'],
                    "is_generic": scene['properties']['is_generic'],
                    "is_domain_specific": domain['id'] in scene_domains and 'all' not in scene_domains,
                    "frequency": scene['properties']['frequency'],
                    "tags": scene.get('tags', {}),
                    "domain_context": domain.get('context', {}) if not scene['properties']['is_generic'] else None
                })
        
        # 添加到视图
        domain_view['categories'].append({
            "id": domain['id'],
            "name": domain['name'],
            "icon": domain['icon'],
            "description": domain['description'],
            "sort_order": domain['sort_order'],
            "scene_count": len(domain_scenes),
            "context": domain.get('context', {}),
            "scenes": domain_scenes
        })
    
    return domain_view


def main():
    """主函数"""
    print("=" * 80)
    print("场景配置生成脚本")
    print("=" * 80)
    
    # 文件路径
    base_dir = Path(__file__).parent
    scenes_file = base_dir / "scenes.json"
    categories_file = base_dir / "categories.json"
    
    # 加载数据
    print("\n加载配置文件...")
    scenes_data = load_json(scenes_file)
    categories_data = load_json(categories_file)
    
    scenes = scenes_data['scenes']
    print(f"  场景数量: {len(scenes)}")
    
    nature_categories = categories_data['dimensions']['nature']['categories']
    domain_categories = categories_data['dimensions']['domain']['categories']
    print(f"  性质分类数量: {len(nature_categories)}")
    print(f"  领域分类数量: {len(domain_categories)}")
    
    # 生成性质分类视图
    print("\n生成按性质分类的场景列表...")
    nature_view = generate_nature_view(scenes, categories_data)
    nature_file = base_dir / "view_nature.json"
    save_json(nature_view, nature_file)
    print(f"  ✅ 已保存: {nature_file}")
    
    # 统计每个分类的场景数量
    print("\n  性质分类统计:")
    for category in nature_view['categories']:
        print(f"    - {category['name']}: {category['scene_count']} 个场景")
    
    # 生成领域分类视图
    print("\n生成按领域分类的场景列表...")
    domain_view = generate_domain_view(scenes, categories_data)
    domain_file = base_dir / "view_domain.json"
    save_json(domain_view, domain_file)
    print(f"  ✅ 已保存: {domain_file}")
    
    # 统计每个领域的场景数量
    print("\n  领域分类统计:")
    for domain in domain_view['categories']:
        generic_count = sum(1 for s in domain['scenes'] if s['is_generic'])
        specific_count = domain['scene_count'] - generic_count
        print(f"    - {domain['name']}: {domain['scene_count']} 个场景 (通用{generic_count}, 专属{specific_count})")
    
    # 生成统计报告
    print("\n" + "=" * 80)
    print("生成完成统计")
    print("=" * 80)
    
    # 统计通用场景
    generic_scenes = [s for s in scenes if s['properties']['is_generic']]
    print(f"\n通用场景数量: {len(generic_scenes)}")
    for scene in generic_scenes:
        print(f"  - {scene['name']} (支持 {len(scene['properties']['domains'])} 个领域)")
    
    # 统计专属场景
    specific_scenes = [s for s in scenes if not s['properties']['is_generic']]
    print(f"\n专属场景数量: {len(specific_scenes)}")
    for scene in specific_scenes:
        print(f"  - {scene['name']} (专属 {scene['properties']['nature_name']})")
    
    print("\n✅ 完成！")


if __name__ == "__main__":
    main()
