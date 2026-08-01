#!/usr/bin/env python3
"""
重新生成场景智能体的 AGENTS.md

架构修正：
- 场景智能体的系统提示词应该在 AGENTS.md 中
- AGENTS.md 只包含场景特定的内容（角色定位、核心能力、专业领域）
- 不包含通用内容（安全、协作等，这些在用户智能体中）

流程：
1. 从 scenes.json 读取场景配置
2. 生成简洁的场景系统提示词
3. 更新 scenes.json 的 system_prompt 字段
4. 创建场景智能体的 AGENTS.md
"""

import json
from pathlib import Path


def generate_scene_system_prompt(scene_name: str, description: str, skills: list) -> str:
    """生成简洁的场景系统提示词
    
    只包含：
    - 角色定位
    - 核心能力
    - 专业领域知识
    
    不包含：安全、协作、回答风格等通用内容
    """
    
    # 技能映射
    skill_names = {
        "audio-transcription": "会议录音转写",
        "docx": "Word文档处理",
        "pdf": "PDF文档处理",
        "xlsx": "Excel表格处理",
        "document-analysis": "文档分析",
        "workflow": "工作流程管理",
        "data-analysis": "数据分析",
        "compliance-check": "合规性检查",
        "content-extraction": "内容提取",
        "summarization": "内容摘要",
    }
    
    # 生成技能列表
    skill_list = [skill_names.get(s, s) for s in skills if s]
    
    # 生成简洁的系统提示词
    prompt = f"# {scene_name}\n\n"
    prompt += f"## 角色定位\n\n{description}\n\n"
    
    if skill_list:
        prompt += f"## 核心能力\n\n"
        for skill in skill_list:
            prompt += f"- {skill}\n"
        prompt += "\n"
    
    return prompt


def main():
    """主函数"""
    
    # 开发环境数据目录
    data_dir = Path("/apps/ai/coapis-dev")
    scenes_file = data_dir / "scenes.json"
    agents_dir = data_dir / "agents"
    
    if not scenes_file.exists():
        print(f"Error: scenes.json not found at {scenes_file}")
        return
    
    # 读取场景数据
    with open(scenes_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    scenes = data.get("scenes", [])
    
    if not scenes:
        print("Error: No scenes found in scenes.json")
        return
    
    print(f"Found {len(scenes)} scenes in scenes.json\n")
    
    # 统计
    updated_scenes = 0
    updated_agents = 0
    
    # 为每个场景生成系统提示词
    for scene in scenes:
        scene_id = scene.get("id", "")
        scene_name = scene.get("name", "")
        description = scene.get("description", "")
        skills = scene.get("skills", [])
        
        if not scene_id:
            continue
        
        # 生成系统提示词
        system_prompt = generate_scene_system_prompt(scene_name, description, skills)
        
        # 更新 scenes.json
        scene["system_prompt"] = system_prompt
        updated_scenes += 1
        
        # 更新场景智能体的 AGENTS.md
        agent_dir = agents_dir / f"scene-{scene_id}"
        if agent_dir.exists():
            agents_md_path = agent_dir / "AGENTS.md"
            agents_md_path.write_text(system_prompt, encoding="utf-8")
            updated_agents += 1
            print(f"  [{scene_id}] {scene_name}: updated AGENTS.md ({len(system_prompt)} chars)")
        else:
            print(f"  [{scene_id}] {scene_name}: no agent directory")
    
    # 保存更新后的 scenes.json
    with open(scenes_file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    
    print(f"\nSummary:")
    print(f"  Updated scenes.json: {updated_scenes}")
    print(f"  Updated AGENTS.md: {updated_agents}")
    print(f"  Saved to: {scenes_file}")


if __name__ == "__main__":
    main()
