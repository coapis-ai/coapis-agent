"""
场景管理API
支持多维度分类和场景查询
"""

from fastapi import APIRouter, Query, HTTPException
from typing import Optional, List, Dict, Any
import json
from pathlib import Path

router = APIRouter(prefix="/api/scenes", tags=["scenes"])

# 数据文件路径
DATA_DIR = Path(__file__).parent.parent / "data" / "scene-configs"


def load_json(file_path: Path) -> Dict[str, Any]:
    """加载JSON文件"""
    with open(file_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_json(data: Dict[str, Any], file_path: Path) -> None:
    """保存JSON文件"""
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


@router.get("/categories")
async def get_categories():
    """
    获取分类配置
    
    返回两个维度的分类：
    - nature: 通用分类（7个）
    - domain: 领域分类（10个）
    """
    try:
        data = load_json(DATA_DIR / "categories.json")
        return {
            "success": True,
            "data": data
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"加载分类配置失败: {str(e)}")


@router.get("")
async def get_scenes(
    dimension: Optional[str] = Query(None, description="维度：nature(通用分类) 或 domain(领域分类)"),
    category: Optional[str] = Query(None, description="分类ID")
):
    """
    获取场景列表
    
    参数：
    - dimension: 维度（nature/domain），可选
    - category: 分类ID，可选
    
    返回：
    - 如果不指定参数：返回所有场景
    - 如果指定dimension：返回该维度下的分类和场景
    - 如果指定category：返回该分类下的场景
    """
    try:
        # 加载场景配置
        scenes_data = load_json(DATA_DIR / "scenes.json")
        scenes = scenes_data['scenes']
        
        # 加载分类配置
        categories_data = load_json(DATA_DIR / "categories.json")
        
        # 场景过滤逻辑
        if category:
            # 按分类过滤
            if dimension == "nature":
                # 通用分类：查询 category.nature == categoryId
                filtered_scenes = [
                    s for s in scenes 
                    if s['category']['nature'] == category
                ]
            elif dimension == "domain":
                # 领域分类：查询 category.domains 包含 categoryId
                filtered_scenes = [
                    s for s in scenes 
                    if category in s['category']['domains']
                ]
            else:
                # 未指定维度，尝试匹配两种分类
                filtered_scenes = [
                    s for s in scenes 
                    if s['category']['nature'] == category or category in s['category']['domains']
                ]
        else:
            # 不指定分类，返回所有场景
            filtered_scenes = scenes
        
        # 如果指定维度，返回分类信息
        if dimension and not category:
            categories = categories_data['dimensions'].get(dimension, {}).get('categories', [])
            
            # 为每个分类添加场景列表
            result_categories = []
            for cat in categories:
                if dimension == "nature":
                    # 通用分类
                    cat_scenes = [
                        {
                            "id": s['id'],
                            "name": s['name'],
                            "description": s['description'],
                            "icon": s['icon'],
                            "is_generic": s['is_generic'],
                            "frequency": s['properties']['frequency']
                        }
                        for s in scenes 
                        if s['category']['nature'] == cat['id']
                    ]
                else:
                    # 领域分类
                    cat_scenes = [
                        {
                            "id": s['id'],
                            "name": s['name'],
                            "description": s['description'],
                            "icon": s['icon'],
                            "is_generic": s['is_generic'],
                            "frequency": s['properties']['frequency']
                        }
                        for s in scenes 
                        if cat['id'] in s['category']['domains']
                    ]
                
                result_categories.append({
                    **cat,
                    "scene_count": len(cat_scenes),
                    "scenes": cat_scenes
                })
            
            return {
                "success": True,
                "data": {
                    "dimension": dimension,
                    "dimension_name": categories_data['dimensions'].get(dimension, {}).get('name', ''),
                    "categories": result_categories
                }
            }
        
        # 返回场景列表
        return {
            "success": True,
            "data": {
                "total": len(filtered_scenes),
                "scenes": [
                    {
                        "id": s['id'],
                        "name": s['name'],
                        "description": s['description'],
                        "icon": s['icon'],
                        "agent_id": s['agent_id'],
                        "is_generic": s['is_generic'],
                        "category": s['category'],
                        "frequency": s['properties']['frequency'],
                        "skills": s.get('skills', []),
                        "tags": s.get('tags', {})
                    }
                    for s in filtered_scenes
                ]
            }
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"加载场景配置失败: {str(e)}")


@router.get("/{scene_id}")
async def get_scene(scene_id: str):
    """
    获取场景详情
    
    参数：
    - scene_id: 场景ID
    
    返回：场景的完整配置信息
    """
    try:
        scenes_data = load_json(DATA_DIR / "scenes.json")
        scenes = scenes_data['scenes']
        
        # 查找场景
        for scene in scenes:
            if scene['id'] == scene_id:
                return {
                    "success": True,
                    "data": scene
                }
        
        raise HTTPException(status_code=404, detail=f"场景不存在: {scene_id}")
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"加载场景配置失败: {str(e)}")


@router.get("/statistics/summary")
async def get_statistics():
    """
    获取统计信息
    
    返回：
    - 总场景数
    - 通用场景数
    - 专属场景数
    - 各分类下的场景数
    """
    try:
        scenes_data = load_json(DATA_DIR / "scenes.json")
        scenes = scenes_data['scenes']
        
        categories_data = load_json(DATA_DIR / "categories.json")
        
        # 统计
        total = len(scenes)
        generic = len([s for s in scenes if s['is_generic']])
        specific = total - generic
        
        # 按通用分类统计
        nature_stats = {}
        for scene in scenes:
            nature = scene['category']['nature']
            if nature:
                nature_stats[nature] = nature_stats.get(nature, 0) + 1
        
        # 按领域分类统计
        domain_stats = {}
        for scene in scenes:
            for domain in scene['category']['domains']:
                domain_stats[domain] = domain_stats.get(domain, 0) + 1
        
        return {
            "success": True,
            "data": {
                "total": total,
                "generic": generic,
                "specific": specific,
                "nature_stats": nature_stats,
                "domain_stats": domain_stats
            }
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"统计失败: {str(e)}")


# 管理员API（需要权限）

@router.post("")
async def create_scene(scene_data: Dict[str, Any]):
    """
    创建场景（管理员权限）
    
    参数：
    - scene_data: 场景配置数据
    """
    # TODO: 实现场景创建逻辑
    raise HTTPException(status_code=501, detail="功能开发中")


@router.put("/{scene_id}")
async def update_scene(scene_id: str, scene_data: Dict[str, Any]):
    """
    更新场景（管理员权限）
    
    参数：
    - scene_id: 场景ID
    - scene_data: 场景配置数据
    """
    # TODO: 实现场景更新逻辑
    raise HTTPException(status_code=501, detail="功能开发中")


@router.delete("/{scene_id}")
async def delete_scene(scene_id: str):
    """
    删除场景（管理员权限）
    
    参数：
    - scene_id: 场景ID
    """
    # TODO: 实现场景删除逻辑
    raise HTTPException(status_code=501, detail="功能开发中")
