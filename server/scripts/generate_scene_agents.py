#!/usr/bin/env python3
"""
场景智能体批量生成脚本
从 data/industries/ 读取场景数据，批量创建场景智能体配置
"""

import json
import os
from pathlib import Path
from datetime import datetime

# 工作目录
WORKING_DIR = Path(os.environ.get('WORKING_DIR', '/apps/ai/coapis'))
INDUSTRIES_DIR = Path(__file__).parent.parent.parent / 'data' / 'industries'
AGENTS_DIR = WORKING_DIR / 'agents'

def load_industries_overview():
    """加载行业领域概览"""
    overview_file = INDUSTRIES_DIR / 'overview.json'
    with open(overview_file, 'r', encoding='utf-8') as f:
        return json.load(f)

def load_domain_scenes(domain_code):
    """加载领域场景数据"""
    scenes_file = INDUSTRIES_DIR / domain_code / 'scenes.json'
    with open(scenes_file, 'r', encoding='utf-8') as f:
        return json.load(f)

def generate_agent_id(scene_id):
    """生成智能体ID"""
    return f"scene-{scene_id}"

def generate_agent_config(scene_data, domain_data):
    """生成智能体配置"""
    agent_id = generate_agent_id(scene_data['id'])
    
    # 基础配置
    config = {
        "id": agent_id,
        "name": scene_data['name'],
        "description": scene_data['description'],
        "model": "gpt-4",  # 默认模型
        "system_prompt": scene_data.get('system_prompt', ''),
        "welcome_message": scene_data.get('welcome_message', ''),
        
        # 场景信息
        "scene_info": {
            "scene_id": scene_data['id'],
            "scene_type": scene_data['type'],
            "category": scene_data['category'],
            "subcategory": scene_data.get('subcategory', ''),
            "domain_code": domain_data['code'],
            "domain_name": domain_data['name'],
            "tags": scene_data.get('tags', []),
            "priority": scene_data.get('priority', 'medium')
        },
        
        # 技能配置
        "skills": scene_data.get('skills', []),
        
        # 知识要求
        "knowledge_requirements": scene_data.get('knowledge_requirements', []),
        
        # 元数据
        "metadata": {
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "created_by": "system",
            "version": "1.0",
            "source": "industries_data"
        },
        
        # 进化配置
        "evolution": {
            "enabled": True,
            "memory_file": "MEMORY.md",
            "max_memory_size": 100,
            "auto_evolve": True
        },
        
        # 工具配置
        "tools": {
            "enabled": True,
            "whitelist": [],
            "blacklist": []
        }
    }
    
    return config

def create_agent_directory(agent_id):
    """创建智能体目录"""
    agent_dir = AGENTS_DIR / agent_id
    agent_dir.mkdir(parents=True, exist_ok=True)
    return agent_dir

def save_agent_config(agent_dir, config):
    """保存智能体配置"""
    config_file = agent_dir / 'agent.json'
    with open(config_file, 'w', encoding='utf-8') as f:
        json.dump(config, f, ensure_ascii=False, indent=2)

def create_memory_file(agent_dir):
    """创建记忆文件"""
    memory_file = agent_dir / 'MEMORY.md'
    if not memory_file.exists():
        memory_file.write_text('# 场景智能体记忆\n\n## 共享进化记忆\n\n此记忆将被所有使用该场景的用户共享。\n', encoding='utf-8')

def generate_all_agents():
    """批量生成所有场景智能体"""
    print("=" * 80)
    print("场景智能体批量生成")
    print("=" * 80)
    
    # 加载概览
    overview = load_industries_overview()
    print(f"\n总计领域: {overview['statistics']['total_domains']}")
    print(f"总计场景: {overview['statistics']['total_scenes']}")
    
    # 统计信息
    stats = {
        'total_domains': 0,
        'total_scenes': 0,
        'created_agents': 0,
        'skipped_agents': 0,
        'errors': []
    }
    
    # 遍历每个领域
    for domain in overview['domains']:
        if domain['status'] != 'completed':
            continue
        
        stats['total_domains'] += 1
        print(f"\n{'=' * 80}")
        print(f"领域: {domain['name']} ({domain['code']})")
        print(f"场景数量: {domain['scene_count']}")
        print(f"{'=' * 80}")
        
        # 加载领域数据
        try:
            scenes_data = load_domain_scenes(domain['code'])
            domain_data = scenes_data
            
            # 遍历每个场景
            for scene in scenes_data['scenes']:
                stats['total_scenes'] += 1
                agent_id = generate_agent_id(scene['id'])
                
                print(f"\n场景: {scene['name']} ({scene['id']})")
                print(f"  类型: {scene['type']} | 分类: {scene['category']}")
                print(f"  智能体ID: {agent_id}")
                
                # 创建智能体目录
                agent_dir = create_agent_directory(agent_id)
                
                # 生成配置
                config = generate_agent_config(scene, domain_data)
                
                # 保存配置
                save_agent_config(agent_dir, config)
                
                # 创建记忆文件
                create_memory_file(agent_dir)
                
                stats['created_agents'] += 1
                print(f"  ✅ 已创建")
        
        except Exception as e:
            error_msg = f"领域 {domain['code']} 处理失败: {str(e)}"
            stats['errors'].append(error_msg)
            print(f"  ❌ 错误: {str(e)}")
    
    # 输出统计
    print(f"\n{'=' * 80}")
    print("生成完成统计")
    print(f"{'=' * 80}")
    print(f"总领域数: {stats['total_domains']}")
    print(f"总场景数: {stats['total_scenes']}")
    print(f"创建智能体: {stats['created_agents']}")
    print(f"跳过智能体: {stats['skipped_agents']}")
    
    if stats['errors']:
        print(f"\n错误列表:")
        for error in stats['errors']:
            print(f"  - {error}")
    
    return stats

if __name__ == '__main__':
    generate_all_agents()
