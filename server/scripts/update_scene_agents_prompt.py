#!/usr/bin/env python3
"""
更新场景智能体的 system_prompt

从 scenes.json 读取 system_prompt，更新到对应的 agent.json
"""

import json
from pathlib import Path

def main():
    """主函数"""
    
    data_dir = Path("/apps/ai/coapis")
    scenes_file = data_dir / "scenes.json"
    agents_dir = data_dir / "agents"
    
    # 读取场景数据
    with open(scenes_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    scenes = {s["id"]: s for s in data.get("scenes", [])}
    
    print(f"Found {len(scenes)} scenes in scenes.json")
    
    # 统计
    updated_count = 0
    skipped_count = 0
    
    # 遍历所有场景智能体目录
    for agent_dir in agents_dir.iterdir():
        if not agent_dir.is_dir():
            continue
        
        if not agent_dir.name.startswith("scene-"):
            continue
        
        agent_file = agent_dir / "agent.json"
        if not agent_file.exists():
            continue
        
        # 读取智能体配置
        with open(agent_file, "r", encoding="utf-8") as f:
            agent_config = json.load(f)
        
        # 获取场景ID
        agent_id = agent_config.get("id", "")
        if not agent_id.startswith("scene-"):
            continue
        
        scene_id = agent_id.replace("scene-", "")
        
        # 查找对应的场景数据
        if scene_id not in scenes:
            print(f"  [{agent_id}] No matching scene in scenes.json")
            skipped_count += 1
            continue
        
        scene_data = scenes[scene_id]
        system_prompt = scene_data.get("system_prompt", "")
        
        if not system_prompt:
            print(f"  [{agent_id}] Scene has no system_prompt")
            skipped_count += 1
            continue
        
        # 更新智能体配置
        if "capabilities" not in agent_config:
            agent_config["capabilities"] = {}
        
        old_prompt = agent_config["capabilities"].get("system_prompt", "")
        agent_config["capabilities"]["system_prompt"] = system_prompt
        
        # 保存
        with open(agent_file, "w", encoding="utf-8") as f:
            json.dump(agent_config, f, indent=2, ensure_ascii=False)
        
        updated_count += 1
        print(f"  [{agent_id}] Updated: {len(old_prompt)} → {len(system_prompt)} chars")
    
    print(f"\nSummary:")
    print(f"  Updated: {updated_count}")
    print(f"  Skipped: {skipped_count}")


if __name__ == "__main__":
    main()
