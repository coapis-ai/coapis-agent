#!/usr/bin/env python3
"""
批量生成场景系统提示词

问题：所有场景的 system_prompt 字段都是空的
解决：根据场景名称和描述生成默认的系统提示词
"""

import json
from pathlib import Path

def generate_system_prompt(scene_name: str, description: str, skills: list) -> str:
    """生成场景系统提示词"""
    
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
    
    prompt = f"""你是{scene_name}专家助手。

## 角色定位
{description}

## 核心能力
"""
    
    if skill_list:
        prompt += "、".join(skill_list)
    else:
        prompt += "专业咨询、文档处理、问题解答"
    
    prompt += """

## 服务原则
1. **专业性**：提供专业、准确的建议和解决方案
2. **友好性**：以友好、耐心的态度服务用户
3. **实用性**：提供可操作、可落地的建议
4. **及时性**：快速响应用户需求

## 回答风格
- 简洁明了，突出重点
- 结构清晰，便于理解
- 主动提供相关建议
- 适时追问以明确需求
"""
    
    return prompt


def main():
    """主函数"""
    
    # 数据目录
    data_dir = Path("/apps/ai/coapis")
    scenes_file = data_dir / "scenes.json"
    
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
    
    print(f"Found {len(scenes)} scenes")
    
    # 统计
    empty_count = 0
    updated_count = 0
    
    # 为每个场景生成系统提示词
    for scene in scenes:
        scene_id = scene.get("id", "")
        scene_name = scene.get("name", "")
        description = scene.get("description", "")
        skills = scene.get("skills", [])
        system_prompt = scene.get("system_prompt", "")
        
        # 如果 system_prompt 为空，生成默认提示词
        if not system_prompt:
            empty_count += 1
            
            # 生成系统提示词
            new_prompt = generate_system_prompt(scene_name, description, skills)
            
            # 更新场景数据
            scene["system_prompt"] = new_prompt
            updated_count += 1
            
            print(f"  [{scene_id}] {scene_name}: generated {len(new_prompt)} chars")
        else:
            print(f"  [{scene_id}] {scene_name}: already has prompt ({len(system_prompt)} chars)")
    
    # 保存更新后的数据
    with open(scenes_file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    
    print(f"\nSummary:")
    print(f"  Total scenes: {len(scenes)}")
    print(f"  Empty prompts: {empty_count}")
    print(f"  Updated: {updated_count}")
    print(f"  Saved to: {scenes_file}")


if __name__ == "__main__":
    main()
